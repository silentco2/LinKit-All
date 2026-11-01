import { Component, computed, effect, ElementRef, inject, signal, viewChild } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, ApiError } from '../api';
import { LibreOfficeCard } from '../components/libreoffice-card';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { dayOf, DtPipe, fmtDate, fmtNum, labelOr, localeOf } from '../locale';
import { LiveEvent, RunState, runKind, ScheduleSection, SEARCH_STAGES, SearchConfig, Stage, STAGES } from '../types';

const STAGE_KEY: Record<Exclude<Stage, 'apply'>, string> = {
  discover: 'live.stage.discover',
  enrich: 'live.stage.enrich',
  rank: 'live.stage.rank',
  score: 'live.stage.score',
};
const STATE_KEY = {
  done: 'live.state.done',
  failed: 'live.state.failed',
  running: 'live.state.running',
  paused: 'live.state.paused',
  waiting: 'live.state.waiting',
  notRun: 'live.state.notRun',
};
const STAGES_KEY = 'linkit.stages'; // the steps ticked under Advanced: a per-viewer convenience
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']; // Python weekday order, as the schedule stores it

interface RecentRun {
  id: number;
  status: string;
  started_at: string;
  kind: 'search' | 'apply' | 'mixed';
  pause_reason: string | null;
  reason_code: string | null;
  reason_params: Record<string, unknown>;
}

/** The steps ticked last time; the search when nothing was stored (or storage is blocked). */
function rememberedStages(): Set<Stage> {
  try {
    const v = JSON.parse(localStorage.getItem(STAGES_KEY) ?? '[]');
    const ok = Array.isArray(v) ? STAGES.filter((s) => v.includes(s)) : [];
    if (ok.length) return new Set(ok);
  } catch {
    // storage blocked or garbled: the default
  }
  return new Set(SEARCH_STAGES);
}

@Component({
  selector: 'app-live',
  imports: [DtPipe, LibreOfficeCard, RouterLink, TPipe],
  template: `
    <section class="card space-y-4">
      <div class="flex flex-wrap gap-3">
        <button class="btn btn-primary" (click)="start()" [disabled]="running() || !chosen().size || busy()">{{ startLabel() | t }}</button>
        <button class="btn btn-danger" (click)="cancel()" [disabled]="!running() || live.run()?.stopping">{{ (live.run()?.stopping ? 'live.stopping' : 'live.stop') | t }}</button>
      </div>
      <details>
        <summary class="cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-300">{{ 'activity.advanced' | t }}</summary>
        <fieldset class="mt-3" [disabled]="running()">
          <legend class="label">{{ 'live.stages' | t }}</legend>
          <div class="flex flex-wrap gap-4">
            @for (s of stages; track s) {
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" [checked]="chosen().has(s)" (change)="toggle(s)"> {{ label(s) }}
              </label>
            }
          </div>
          <label class="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" [checked]="fresh()" (change)="fresh.set(!fresh())"> {{ 'live.fresh' | t }}
          </label>
        </fieldset>
      </details>
      @if (error()) { <div class="alert alert-error" dir="auto">{{ error() }}</div> }
      @if (needsLibreOffice()) { <app-libreoffice-card /> }
      @if (paused(); as p) {
        <div class="alert alert-warn space-y-2" role="status">
          <p><strong>{{ runTitle(p.kind, p.id) }}</strong> {{ 'live.paused.is' | t }} <span dir="auto">{{ reasonText(p.reason_code, p.reason_params, p.pause_reason ?? '') }}</span></p>
          @if (p.reason_code === 'ai_usage_limit') { <p><a [routerLink]="'/settings/ai'">{{ 'run.fix.ai' | t }}</a></p> }
          @if (p.reason_code === 'needs_libreoffice') { <app-libreoffice-card /> }
          <p class="text-xs">{{ 'live.paused.resume' | t }}</p>
        </div>
      }
    </section>

    <details id="schedule" class="card mt-6" [open]="openSchedule">
      <summary class="cursor-pointer text-lg font-semibold text-slate-900 dark:text-white">{{ 'live.schedule.title' | t }}</summary>
      <div class="mt-4 space-y-4">
      @if (schedule(); as sc) {
        <label class="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" role="switch" [checked]="sc.enabled" (change)="edit({ enabled: !sc.enabled })">
          {{ 'live.schedule.auto' | t }}
        </label>
        <p class="text-xs text-slate-500">{{ 'live.schedule.hint' | t }}</p>
        <fieldset class="space-y-4" [disabled]="!sc.enabled">
          <div>
            <legend class="label">{{ 'live.schedule.days' | t }}</legend>
            <div class="flex flex-wrap gap-2">
              @for (d of dayKeys; track $index) {
                <button type="button" class="rounded-full border px-3 py-1 text-sm disabled:opacity-50"
                        [class]="sc.days.includes($index) ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 text-slate-600 dark:border-slate-600 dark:text-slate-300'"
                        [attr.aria-pressed]="sc.days.includes($index)" (click)="toggleDay($index)">{{ 'live.day.' + d | t }}</button>
              }
            </div>
          </div>
          <div>
            <legend class="label">{{ 'live.schedule.times' | t }}</legend>
            <div class="flex flex-wrap items-center gap-3">
              @for (t of sc.times; track $index) {
                <span class="flex items-center gap-1">
                  <input type="time" class="input w-32" [value]="t" dir="ltr" [attr.aria-label]="'live.schedule.runTime' | t: { n: $index + 1 }" (change)="setTime($index, $event)">
                  <button type="button" class="btn" (click)="removeTime($index)" [disabled]="sc.times.length < 2" [attr.aria-label]="'live.schedule.removeTime' | t: { time: t }">{{ 'live.schedule.remove' | t }}</button>
                </span>
              }
              <button type="button" class="btn" (click)="addTime()" [disabled]="sc.times.length >= 6">{{ 'live.schedule.add' | t }}</button>
            </div>
          </div>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" [checked]="sc.new_run" (change)="edit({ new_run: !sc.new_run })"> {{ 'live.schedule.newRun' | t }}
          </label>
        </fieldset>
        <div class="flex flex-wrap items-center gap-4">
          <button class="btn btn-primary" (click)="saveSchedule()" [disabled]="!scheduleDirty()">{{ 'live.schedule.save' | t }}</button>
          @if (sc.enabled && !scheduleDirty() && nextRuns().length) {
            <span class="text-sm text-slate-600 dark:text-slate-400">
              {{ 'live.schedule.next' | t }}
              @for (t of nextRuns(); track t; let last = $last) { <bdi>{{ t | dt: 'when' }}</bdi>@if (!last) {<ng-container>{{ 'live.schedule.sep' | t }}</ng-container>} }
            </span>
          }
        </div>
        @if (scheduleError()) { <div class="alert alert-error" dir="auto">{{ scheduleError() }}</div> }
      }
      </div>
    </details>

    @if (live.run(); as run) {
      @if (run.run_id) {
        <section class="mt-6">
          <h2>{{ runTitle(kindOf(run), run.run_id) }} @if (run.running) { <span class="text-sm font-normal text-emerald-600">{{ 'live.running' | t }}</span> }</h2>
          <ol class="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            @for (s of run.stages; track s) {
              <li class="card p-4" [class.ring-2]="run.stage === s && run.running" [class.ring-brand-500]="run.stage === s && run.running">
                <div class="flex items-center justify-between">
                  <span class="font-medium">{{ label(s) }}</span>
                  <span class="text-xs" [class]="stageClass(s)">{{ stageText(s) }}</span>
                </div>
                @if (run.results[s]; as r) {
                  <p class="mt-2 text-xs text-slate-600 dark:text-slate-400">{{ summary(s, r) }}</p>
                }
              </li>
            }
          </ol>
          @if (run.error && paused()?.id !== run.run_id) { <div class="alert alert-error mt-3" dir="auto">{{ reasonText(run.reason_code, run.reason_params, run.error) }}</div> }
        </section>
      }
    }

    @if (applyRunning()) {
      <section class="card mt-6 space-y-3">
        <h2>{{ 'live.view.title' | t }}</h2>
        @if (live.shot(); as s) {
          <p class="text-sm font-medium" dir="auto">{{ 'live.view.job' | t: { title: s.title, company: s.company } }}</p>
          <img class="w-full rounded-lg border border-slate-200 dark:border-slate-700" [src]="s.url" [alt]="'live.view.alt' | t">
        } @else {
          <p class="text-sm text-slate-500">{{ 'live.view.waiting' | t }}</p>
        }
        <p class="text-xs text-slate-500">{{ 'live.view.caption' | t }}</p>
      </section>
    }

    <section class="mt-6">
      <h2>{{ 'live.activity' | t }}</h2>
      <div #log class="card mt-3 h-[45vh] overflow-auto p-3 font-mono text-xs" role="log" aria-live="polite">
        @for (e of live.events(); track $index) {
          <div class="flex gap-3 py-0.5" [class]="eventClass(e)">
            <span class="shrink-0 text-slate-400" dir="ltr">{{ e.at | dt: 'time' }}</span>
            <span class="min-w-0 break-words" dir="auto">{{ describe(e) }}</span>
          </div>
        } @empty {
          <p class="text-slate-500">{{ 'live.empty' | t }}</p>
        }
      </div>
    </section>
  `,
})
export class LivePage {
  protected readonly live = inject(Live);
  private readonly api = inject(Api);
  protected readonly stages = STAGES;
  /** Home's "More schedule options" link lands here with #schedule: open the block and scroll to it. */
  protected readonly openSchedule = inject(ActivatedRoute).snapshot.fragment === 'schedule';
  protected readonly applyLive = signal(false);
  protected readonly chosen = signal(rememberedStages()); // the default Start is the search; apply is Advanced
  /** The Start button says what it will do. */
  protected readonly startLabel = computed(() => {
    const kind = runKind([...this.chosen()]);
    return kind === 'apply' ? 'live.start.apply' : kind === 'mixed' ? 'live.start.mixed' : 'smart.find';
  });
  /** A run was refused for want of LibreOffice (409 + code): the offer shows instead of an error. */
  protected readonly needsLibreOffice = signal(false);
  protected readonly fresh = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly paused = signal<RecentRun | null>(null);
  protected readonly dayKeys = DAYS;
  private readonly i18n = inject(I18n);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly schedule = signal<ScheduleSection | null>(null);
  protected readonly scheduleDirty = signal(false);
  protected readonly scheduleError = signal('');
  protected readonly nextRuns = signal<string[]>([]);
  protected readonly running = computed(() => !!this.live.run()?.running);
  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  protected readonly applyRunning = computed(() => !!this.live.run()?.running && this.live.run()?.stage === 'apply');

  constructor() {
    this.api.get<{ apply_live: boolean }>('/status').then((st) => this.applyLive.set(st.apply_live)).catch(() => undefined);
    this.loadSchedule();
    if (this.openSchedule) setTimeout(() => document.getElementById('schedule')?.scrollIntoView(), 300);
    effect(() => {
      this.live.events(); // keep the log scrolled to the newest line
      const el = this.log()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
    effect(() => {
      this.live.changed();
      this.api.get<{ recent: RecentRun[] }>('/runs').then((r) => this.paused.set(r.recent.find((x) => x.status === 'paused') ?? null)).catch(() => undefined);
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

  protected num = (n: number | null): string => fmtNum(this.loc(), n);

  label(s: Stage): string {
    return this.i18n.t(s === 'apply' ? (this.applyLive() ? 'live.stage.applyLive' : 'live.stage.applyDry') : STAGE_KEY[s]);
  }

  toggle(s: Stage): void {
    this.chosen.update((set) => {
      const next = new Set(set);
      if (!next.delete(s)) next.add(s);
      try {
        localStorage.setItem(STAGES_KEY, JSON.stringify([...next]));
      } catch {
        // the choice then lasts until the tab closes
      }
      return next;
    });
  }

  protected kindOf = (run: RunState): 'search' | 'apply' | 'mixed' => runKind(run.stages);

  /** "Search 3" / "Applying 4" / "Search and apply 5". */
  protected runTitle(kind: 'search' | 'apply' | 'mixed', id: number | null): string {
    return this.i18n.t('live.runTitle.' + kind, { id: this.num(id) });
  }

  /** Why a run stopped or paused, in the UI language; the server's English text when it sent no code we know. */
  protected reasonText(code: string | null | undefined, params: Record<string, unknown> | undefined, fallback: string): string {
    if (!code) return fallback;
    const p = { ...params };
    let key = code;
    if (code === 'ai_usage_limit') {
      p['provider'] = this.i18n.provider(String(p['provider'] ?? ''));
      const until = dayOf(typeof p['until'] === 'string' ? p['until'] : null);
      if (until) p['until'] = fmtDate(this.loc(), until, 'date');
      else key = 'ai_usage_limit.noDate';
    }
    return this.i18n.msg({ message: fallback, code: key, params: p }, 'run.reason.');
  }

  async start(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    this.needsLibreOffice.set(false);
    try {
      await this.api.post('/runs', { stages: [...this.chosen()], new: this.fresh() });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'needs_libreoffice') this.needsLibreOffice.set(true);
      else this.error.set(e instanceof ApiError && e.code === 'needs_tectonic' ? this.i18n.t('run.reason.needs_tectonic') : (e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  async cancel(): Promise<void> {
    await this.api.post('/runs/cancel');
  }

  private stageState(s: Stage): 'done' | 'failed' | 'paused' | 'running' | 'waiting' | 'notRun' | '' {
    const run = this.live.run();
    if (!run) return '';
    const last = [...this.live.events()].reverse().find((e) => e.type === 'stage' && e.stage === s);
    if (run.results[s]) return 'done';
    if (last?.status === 'failed') return 'failed';
    if (last?.status === 'paused') return 'paused';
    if (run.running && run.stage === s) return 'running';
    return run.running ? 'waiting' : 'notRun';
  }

  stageText(s: Stage): string {
    const st = this.stageState(s);
    return st ? this.i18n.t(STATE_KEY[st]) : '';
  }

  stageClass(s: Stage): string {
    const colours: Record<string, string> = { done: 'text-emerald-600', failed: 'text-rose-600', paused: 'text-amber-700 dark:text-amber-400', running: 'text-brand-600' };
    return colours[this.stageState(s)] ?? 'text-slate-400';
  }

  summary(s: Stage, r: Record<string, unknown>): string {
    const n = (k: string) => this.num(Number(r[k] ?? 0));
    const t = (key: string, p: Record<string, string>) => this.i18n.t(`live.sum.${key}`, p);
    switch (s) {
      case 'discover': {
        const errors = Object.keys((r['errors'] as object) ?? {}).length;
        const p = { new: n('new'), dup: n('duplicates') };
        return errors ? t('discoverErr', { ...p, err: this.num(errors) }) : t('discover', p);
      }
      case 'enrich':
        return t('enrich', { n: n('enriched') });
      case 'rank':
        return t('rank', { ranked: n('ranked'), out: n('filtered_out') });
      case 'score': {
        const p = { high: n('high'), mid: n('mid'), low: n('low') };
        return r['not_scored'] ? t('scoreNs', { ...p, ns: n('not_scored') }) : t('score', p);
      }
      case 'apply': {
        const parts = [
          r['dry_run'] && t('dry', { n: n('dry_run') }),
          t('applied', { n: n('applied') }),
          t('needs', { n: n('needs_user') }),
          t('failed', { n: n('failed') }),
          t('skipped', { n: n('skipped') }),
        ];
        return parts.filter(Boolean).join(this.i18n.t('live.sum.sep'));
      }
    }
  }

  describe(e: LiveEvent): string {
    if (e.type === 'log') return e.code ? this.i18n.msg({ message: e.message ?? '', code: e.code, params: e.params }, 'log.') : (e.message ?? '');
    const status = labelOr(this.i18n, 'live.status.', e.status ?? '');
    if (e.type === 'stage') {
      const error = e.error ? this.reasonText(e.code, e.params, e.error) : '';
      return this.i18n.t(e.error ? 'live.event.stageErr' : 'live.event.stage', { stage: this.label(e.stage!), status, error });
    }
    const error = e.error ? this.reasonText(e.reason_code, e.reason_params, e.error) : '';
    return this.i18n.t(e.error ? 'live.event.runErr' : 'live.event.run', { status, error });
  }

  eventClass(e: LiveEvent): string {
    if (e.level === 'WARNING' || e.status === 'failed') return 'text-amber-700 dark:text-amber-400';
    if (e.level === 'ERROR') return 'text-rose-700 dark:text-rose-400';
    if (e.type !== 'log') return 'font-semibold text-slate-900 dark:text-white';
    return 'text-slate-600 dark:text-slate-400';
  }
}
