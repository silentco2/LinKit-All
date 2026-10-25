import { Injectable, signal } from '@angular/core';
import { LiveEvent, LiveShot, RunState } from './types';

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

  constructor() {
    this.connect();
  }

  private connect(): void {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${proto}://${location.host}/api/events`);
    socket.onopen = () => {
      this.connected.set(true);
      this.events.set([]); // the server replays its recent history
    };
    socket.onclose = () => {
      this.connected.set(false);
      setTimeout(() => this.connect(), 2000);
    };
    socket.onmessage = (msg) => this.handle(JSON.parse(msg.data));
  }

  private handle(event: LiveEvent & Partial<RunState>): void {
    if (event.type === 'live_shot') { // every ~3 s: shown in the browser view, not in the activity log
      this.shot.set(event as LiveShot);
      return;
    }
    this.events.update((list) => [...list.slice(-499), event]);
    if (event.type === 'run') {
      const { running = false, run_id = null, stages = [], stage = null, started_at = null, error = null, results = {} } = event;
      this.run.set({ running, run_id, stages, stage, started_at, error, results });
      if (!running) this.shot.set(null);
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
}
