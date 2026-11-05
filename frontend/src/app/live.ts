import { inject, Injectable, signal } from '@angular/core';
import { Api } from './api';
import { JobDetail, LiveEvent, LiveShot, RunState } from './types';

/** WebSocket /api/events with auto-reconnect; keeps recent events and the run state. */
@Injectable({ providedIn: 'root' })
export class Live {
  readonly events = signal<LiveEvent[]>([]);
  readonly run = signal<RunState | null>(null);
  /** Newest browser frame while the apply stage runs; null otherwise. */
  readonly shot = signal<LiveShot | null>(null);
  readonly connected = signal(false);
  /** Bumped whenever a stage or run ends, so pages can reload their data. */
  readonly changed = signal(0);
  /** Titles of the jobs an apply run works on, so its log can say "Stripe — Backend Engineer" and not a job number. */
  readonly jobs = signal<Record<number, { title: string; company: string }>>({});
  private readonly api = inject(Api);
  /** Jobs whose "Filling ..." line is already in the log (from `apply_job_start`, or from their first browser frame). */
  private readonly announced = new Set<number>();

  constructor() {
    this.connect();
  }

  private connect(): void {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${proto}://${location.host}/api/events`);
    socket.onopen = () => {
      this.connected.set(true);
      this.events.set([]); // the server replays its recent history
      this.announced.clear();
      this.run.set(null); // a restarted server replays nothing: take the run state from the replay or /status
      this.changed.update((n) => n + 1);
    };
    socket.onclose = () => {
      this.connected.set(false);
      setTimeout(() => this.connect(), 2000);
    };
    socket.onmessage = (msg) => this.handle(JSON.parse(msg.data));
  }

  private handle(event: LiveEvent & Partial<RunState>): void {
    if (event.type === 'live_shot') { // every ~3 s: shown in the browser view, not in the activity log
      const shot = event as LiveShot;
      this.shot.set(shot);
      this.jobs.update((m) => ({ ...m, [shot.job_id]: { title: shot.title, company: shot.company } }));
      if (!this.announced.has(shot.job_id)) { // an older server sends no apply_job_start: the first frame of a job says "Filling ..."
        this.announced.add(shot.job_id);
        this.add({ at: event.at, type: 'log', level: 'INFO', code: 'apply_filling', params: { job: shot.job_id } });
      }
      return;
    }
    if (event.type === 'log' && event.code === 'apply_job_start') {
      const job = Number(event.params?.['job']);
      const title = String(event.params?.['title'] ?? '');
      if (job && title) {
        this.announced.add(job);
        this.jobs.update((m) => ({ ...m, [job]: { title, company: String(event.params?.['company'] ?? '') } }));
      }
    }
    if (event.type === 'log' && event.code === 'apply_job') void this.nameJob(Number(event.params?.['job']));
    this.add(event);
    if (event.type === 'run') {
      const { running = false, stopping = false, run_id = null, stages = [], stage = null, started_at = null, error = null, results = {}, reason_code = null, reason_params = {}, status } = event;
      this.run.set({ running, stopping: running && stopping, run_id, stages, stage, started_at, error, reason_code, reason_params, status, results });
      if (!running) this.shot.set(null);
      if (event.status === 'started' || !running) this.announced.clear();
    } else if (event.type === 'stage') {
      this.run.update((r) =>
        r && {
          ...r,
          stage: event.status === 'started' ? event.stage! : r.stage,
          results: event.result ? { ...r.results, [event.stage!]: event.result } : r.results,
        },
      );
    }
    if (event.type !== 'log' && event.status !== 'started') this.changed.update((n) => n + 1);
  }

  private add(event: LiveEvent): void {
    this.events.update((list) => [...list.slice(-499), event]);
  }

  /** A job that finished without a browser frame (closed, skipped) has no title yet: ask once. */
  private async nameJob(id: number): Promise<void> {
    if (!id || this.jobs()[id]) return;
    try {
      const j = await this.api.get<JobDetail>(`/jobs/${id}`);
      this.jobs.update((m) => ({ ...m, [id]: { title: j.title, company: j.company } }));
    } catch {
      // the line then says "a job"
    }
  }
}
