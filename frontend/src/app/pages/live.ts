import { DatePipe } from '@angular/common';
import { Component, computed, effect, ElementRef, inject, signal, viewChild } from '@angular/core';
import { Api } from '../api';
import { Live } from '../live';
import { LiveEvent, ScheduleSection, SearchConfig, Stage, STAGES } from '../types';

const LABELS: Record<Stage, string> = {
  discover: 'Find jobs',
  enrich: 'Read descriptions',
  rank: 'Filter & rank (free)',
  score: 'AI scoring',
  apply: 'Apply',
};

interface RecentRun {
  id: number;
  status: string;
  started_at: string;
  pause_reason: string | null;
}

@Component({
  selector: 'app-live',
  imports: [DatePipe],
  template: `
    <h1>Live run</h1>

    <section class="card mt-6 space-y-4">
      <fieldset [disabled]="running()">
        <legend class="label">Stages to run</legend>
        <div class="flex flex-wrap gap-4">
          @for (s of stages; track s) {
            <label class="flex items-center gap-2 text-sm">
              <input type="checkbox" [checked]="chosen().has(s)" (change)="toggle(s)"> {{ label(s) }}
            </label>
          }
        </div>
        <label class="mt-3 flex items-center gap-2 text-sm">
          <input type="checkbox" [checked]="fresh()" (change)="fresh.set(!fresh())"> Start a new run (otherwise an unfinished run resumes)
        </label>
      </fieldset>
      <div class="flex gap-3">
        <button class="btn btn-primary" (click)="start()" [disabled]="running() || !chosen().size || busy()">Start</button>
        <button class="btn btn-danger" (click)="cancel()" [disabled]="!running()">Stop</button>
      </div>
      @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
      @if (paused(); as p) {
        <div class="alert alert-info">Run {{ p.id }} is paused: {{ p.pause_reason }}. Start again later to continue scoring.</div>
      }
    </section>

    <section class="card mt-6 space-y-4">
      <h2>Schedule</h2>
      @if (schedule(); as sc) {
        <label class="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" role="switch" [checked]="sc.enabled" (change)="edit({ enabled: !sc.enabled })">
          Run automatically while LinKit All is open
        </label>
        <p class="text-xs text-slate-500">Scheduled runs use the same settings as manual ones: dry run unless you turned live applying on, with the same caps.</p>
        <fieldset class="space-y-4" [disabled]="!sc.enabled">
          <div>
            <legend class="label">Days</legend>
            <div class="flex flex-wrap gap-2">
              @for (d of dayNames; track $index) {
                <button type="button" class="rounded-full border px-3 py-1 text-sm disabled:opacity-50"
                        [class]="sc.days.includes($index) ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 text-slate-600 dark:border-slate-600 dark:text-slate-300'"
                        [attr.aria-pressed]="sc.days.includes($index)" (click)="toggleDay($index)">{{ d }}</button>
              }
            </div>
          </div>
          <div>
            <legend class="label">Times (your local time)</legend>
            <div class="flex flex-wrap items-center gap-3">
              @for (t of sc.times; track $index) {
                <span class="flex items-center gap-1">
                  <input type="time" class="input w-32" [value]="t" [attr.aria-label]="'Run time ' + ($index + 1)" (change)="setTime($index, $event)">
                  <button type="button" class="btn" (click)="removeTime($index)" [disabled]="sc.times.length < 2" [attr.aria-label]="'Remove time ' + t">Remove</button>
                </span>
              }
              <button type="button" class="btn" (click)="addTime()" [disabled]="sc.times.length >= 6">Add time</button>
            </div>
          </div>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" [checked]="sc.new_run" (change)="edit({ new_run: !sc.new_run })"> Start a new run each time (otherwise an unfinished run resumes)
          </label>
        </fieldset>
        <div class="flex flex-wrap items-center gap-4">
          <button class="btn btn-primary" (click)="saveSchedule()" [disabled]="!scheduleDirty()">Save schedule</button>
          @if (sc.enabled && !scheduleDirty() && nextRuns().length) {
            <span class="text-sm text-slate-600 dark:text-slate-400">
              Next:
              @for (t of nextRuns(); track t; let last = $last) { {{ t | date: 'EEE d MMM, HH:mm' }}@if (!last) {; } }
            </span>
          }
        </div>
        @if (scheduleError()) { <div class="alert alert-error">{{ scheduleError() }}</div> }
      }
    </section>

    @if (live.run(); as run) {
      @if (run.run_id) {
        <section class="mt-6">
          <h2>Run {{ run.run_id }} @if (run.running) { <span class="text-sm font-normal text-emerald-600">running</span> }</h2>
          <ol class="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            @for (s of run.stages; track s) {
              <li class="card p-4" [class.ring-2]="run.stage === s && run.running" [class.ring-brand-500]="run.stage === s && run.running">
                <div class="flex items-center justify-between">
                  <span class="font-medium">{{ label(s) }}</span>
                  <span class="text-xs" [class]="stageClass(s)">{{ stageStatus(s) }}</span>
                </div>
                @if (run.results[s]; as r) {
                  <p class="mt-2 text-xs text-slate-600 dark:text-slate-400">{{ summary(s, r) }}</p>
                }
              </li>
            }
          </ol>
          @if (run.error) { <div class="alert alert-error mt-3">{{ run.error }}</div> }
        </section>
      }
    }

    <section class="mt-6">
      <h2>Activity</h2>
      <div #log class="card mt-3 h-[45vh] overflow-auto p-3 font-mono text-xs" role="log" aria-live="polite">
        @for (e of live.events(); track $index) {
          <div class="flex gap-3 py-0.5" [class]="eventClass(e)">
            <span class="shrink-0 text-slate-400">{{ e.at | date: 'HH:mm:ss' }}</span>
            <span class="min-w-0 break-words">{{ describe(e) }}</span>
          </div>
        } @empty {
          <p class="text-slate-500">Nothing yet. Start a run to see live progress.</p>
        }
      </div>
    </section>
  `,
})
export class LivePage {
  protected readonly live = inject(Live);
  private readonly api = inject(Api);
  protected readonly stages = STAGES;
  protected readonly applyLive = signal(false);
  protected readonly chosen = signal(new Set<Stage>(STAGES));
  protected readonly fresh = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly paused = signal<RecentRun | null>(null);
  protected readonly dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  protected readonly schedule = signal<ScheduleSection | null>(null);
  protected readonly scheduleDirty = signal(false);
  protected readonly scheduleError = signal('');
  protected readonly nextRuns = signal<string[]>([]);
  protected readonly running = computed(() => !!this.live.run()?.running);
  private readonly log = viewChild<ElementRef<HTMLElement>>('log');

  constructor() {
    this.api.get<{ apply_live: boolean }>('/status').then((st) => this.applyLive.set(st.apply_live)).catch(() => undefined);
    this.loadSchedule();
    effect(() => {
      this.live.events(); // keep the log scrolled to the newest line
      const el = this.log()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
    effect(() => {
      this.live.changed();
      this.api.get<{ recent: RecentRun[] }>('/runs').then((r) => this.paused.set(r.recent.find((x) => x.status === 'paused') ?? null));
    });
  }

  private async loadSchedule(): Promise<void> {
    try {
      const [cfg, next] = await Promise.all([
        this.api.get<SearchConfig>('/search'),
        this.api.get<{ next_runs: string[] }>('/schedule'),
      ]);
      this.schedule.set(cfg.schedule);
      this.nextRuns.set(next.next_runs);
    } catch (e) {
      this.scheduleError.set((e as Error).message);
    }
  }

  edit(patch: Partial<ScheduleSection>): void {
    this.schedule.update((s) => s && { ...s, ...patch });
    this.scheduleDirty.set(true);
  }

  toggleDay(d: number): void {
    const days = this.schedule()?.days ?? [];
    this.edit({ days: days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort() });
  }

  setTime(i: number, ev: Event): void {
    const value = (ev.target as HTMLInputElement).value;
    if (value) this.edit({ times: (this.schedule()?.times ?? []).map((t, j) => (j === i ? value : t)) });
  }

  addTime(): void {
    const times = this.schedule()?.times ?? [];
    this.edit({ times: [...times, times.includes('18:00') ? '12:00' : '18:00'] });
  }

  removeTime(i: number): void {
    this.edit({ times: (this.schedule()?.times ?? []).filter((_, j) => j !== i) });
  }

  async saveSchedule(): Promise<void> {
    const schedule = this.schedule();
    if (!schedule) return;
    this.scheduleError.set('');
    try {
      // the whole config is one document: read it fresh so other pages' edits are not overwritten
      const cfg = await this.api.get<SearchConfig>('/search');
      const saved = await this.api.put<SearchConfig>('/search', { ...cfg, schedule });
      this.schedule.set(saved.schedule);
      this.scheduleDirty.set(false);
      this.nextRuns.set((await this.api.get<{ next_runs: string[] }>('/schedule')).next_runs);
    } catch (e) {
      this.scheduleError.set((e as Error).message);
    }
  }

  label(s: Stage): string {
    return s === 'apply' ? `Apply (${this.applyLive() ? 'live' : 'dry run'})` : LABELS[s];
  }

  toggle(s: Stage): void {
    this.chosen.update((set) => {
      const next = new Set(set);
      if (!next.delete(s)) next.add(s);
      return next;
    });
  }

  async start(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.post('/runs', { stages: [...this.chosen()], new: this.fresh() });
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  async cancel(): Promise<void> {
    await this.api.post('/runs/cancel');
  }

  stageStatus(s: Stage): string {
    const run = this.live.run();
    if (!run) return '';
    const last = [...this.live.events()].reverse().find((e) => e.type === 'stage' && e.stage === s);
    if (run.results[s]) return 'done';
    if (last?.status === 'failed') return 'failed';
    if (run.running && run.stage === s) return 'running…';
    return run.running ? 'waiting' : 'not run';
  }

  stageClass(s: Stage): string {
    return { done: 'text-emerald-600', failed: 'text-rose-600', 'running…': 'text-brand-600' }[this.stageStatus(s)] ?? 'text-slate-400';
  }

  summary(s: Stage, r: Record<string, unknown>): string {
    const n = (k: string) => Number(r[k] ?? 0);
    switch (s) {
      case 'discover': {
        const errors = Object.keys((r['errors'] as object) ?? {}).length;
        return `${n('new')} new jobs, ${n('duplicates')} duplicates${errors ? `, ${errors} sources failed` : ''}`;
      }
      case 'enrich':
        return `${n('enriched')} descriptions ready`;
      case 'rank':
        return `${n('ranked')} ranked, ${n('filtered_out')} filtered out`;
      case 'score':
        return `${n('high')} high, ${n('mid')} to review, ${n('low')} low${n('not_scored') ? `, ${n('not_scored')} not scored yet` : ''}`;
      case 'apply': {
        const parts = [
          n('dry_run') && `${n('dry_run')} filled (dry run)`,
          `${n('applied')} applied`,
          `${n('needs_user')} need you`,
          `${n('failed')} failed`,
          `${n('skipped')} skipped`,
        ];
        return parts.filter(Boolean).join(', ');
      }
    }
  }

  describe(e: LiveEvent): string {
    if (e.type === 'log') return e.message ?? '';
    if (e.type === 'stage') return `${this.label(e.stage!)}: ${e.status}${e.error ? ` (${e.error})` : ''}`;
    return `Run ${e.status}${e.error ? `: ${e.error}` : ''}`;
  }

  eventClass(e: LiveEvent): string {
    if (e.level === 'WARNING' || e.status === 'failed') return 'text-amber-700 dark:text-amber-400';
    if (e.level === 'ERROR') return 'text-rose-700 dark:text-rose-400';
    if (e.type !== 'log') return 'font-semibold text-slate-900 dark:text-white';
    return 'text-slate-600 dark:text-slate-400';
  }
}
