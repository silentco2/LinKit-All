import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, ElementRef, inject, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, ApiError } from '../api';
import { LibreOfficeCard } from '../components/libreoffice-card';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { DtPipe, fmtNum, labelOr, localeOf, runReason } from '../locale';
import { LiveEvent, RunState, runKind, ScheduleSection, SEARCH_STAGES, SearchConfig, Stage, STAGES } from '../types';

const STAGE_KEY: Record<Exclude<Stage, 'apply'>, string> = {
  discover: 'live.stage.discover',
  enrich: 'live.stage.enrich',
  rank: 'live.stage.rank',
  score: 'live.stage.score',
};
/** What a step card shows. The first unfinished step of a run that is not running is `stopped`, `paused` or `failed`; `next` is the one after it. */
type StepState = 'done' | 'running' | 'stopping' | 'waiting' | 'stopped' | 'paused' | 'failed' | 'next' | 'notRun';
const STEP_TIP: Record<StepState, string> = {
  done: 'live.state.done',
  running: 'live.step.running',
  stopping: 'live.stopping',
  waiting: 'live.state.waiting',
  stopped: 'live.step.stopped',
  paused: 'live.step.paused',
  failed: 'live.step.failed',
  next: 'live.step.next',
  notRun: 'live.state.notRun',
};
const STEP_COLOUR: Partial<Record<StepState, string>> = {
  done: 'text-emerald-600 dark:text-emerald-400',
  running: 'text-brand-600 dark:text-brand-300',
  stopping: 'text-amber-700 dark:text-amber-400',
  stopped: 'text-amber-700 dark:text-amber-400',
  paused: 'text-amber-700 dark:text-amber-400',
  failed: 'text-rose-600 dark:text-rose-400',
  next: 'text-brand-600 dark:text-brand-300',
};
const STAGES_KEY = 'linkit.stages'; // the steps ticked under Advanced: a per-viewer convenience
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']; // Python weekday order, as the schedule stores it

interface RecentRun {
  id: number;
  status: string;
  started_at: string;
  kind: 'search' | 'apply' | 'mixed';
  stages: Stage[];
  stats: Record<string, Record<string, unknown>>;
  pause_reason: string | null;
  reason_code: string | null;
  reason_params: Record<string, unknown>;
}

/** "Search for jobs" / "Apply (practice)": a step's name in the UI language. */
function stageLabel(i18n: I18n, s: Stage, applyLive: boolean): string {
  return i18n.t(s === 'apply' ? (applyLive ? 'live.stage.applyLive' : 'live.stage.applyDry') : STAGE_KEY[s]);
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
  imports: [DtPipe, LibreOfficeCard, NgTemplateOutlet, RouterLink, TPipe],
  template: `
    @if (paused(); as p) {
      <div class="alert alert-warn mb-6 space-y-2" role="status">
        @let why = plainError(p.reason_code, p.reason_params, p.pause_reason ?? '', null);
        <p><strong>{{ runTitle(p.kind, p.id) }}</strong> {{ 'live.paused.is' | t }} <span dir="auto">{{ why.text }}</span></p>
        @if (why.detail) { <ng-container *ngTemplateOutlet="details; context: { $implicit: why.detail }" /> }
        @if (p.reason_code === 'ai_usage_limit') { <p><a [routerLink]="'/settings/ai'">{{ 'run.fix.ai' | t }}</a></p> }
        @if (p.reason_code === 'needs_libreoffice') { <app-libreoffice-card /> }
        <p class="text-xs">{{ 'live.paused.resume' | t }}</p>
      </div>
    }

    @let run = live.run();
    <div class="grid gap-x-10 gap-y-6" [class]="applyRunning() ? 'lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]' : ''">
      <div class="min-w-0">
        @if (runId(); as id) {
          <section>
            <h2>{{ runTitle(kind(), id) }} @if (run?.running) { <span class="text-sm font-normal" [class]="run?.stopping ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'">{{ (run?.stopping ? 'live.stopping' : 'live.running') | t }}</span> }</h2>
            @if (run?.running && run?.stopping) { <div class="alert alert-warn mt-3" role="status">{{ 'live.stoppingNote' | t }}</div> }
            @if (run && endKind(run); as end) {
              <div class="alert mt-3" [class]="end === 'stopped' ? 'alert-info' : 'alert-ok'" role="status">
                <p><strong>{{ (end === 'stopped' ? 'live.stopped.title' : 'live.done.title') | t }}</strong></p>
                <p class="mt-1" dir="auto">{{ endSummary(run, end) }}</p>
              </div>
            }
            @if (error()) { <div class="alert alert-error mt-3" role="alert" dir="auto">{{ error() }}</div> }
            @if (needsLibreOffice()) { <div class="mt-3"><app-libreoffice-card /></div> }
            <ol class="mt-2">
              @for (s of steps(); track s) {
                @let st = stepState(s);
                <li class="flex min-h-11 flex-wrap items-center gap-x-3 border-b border-slate-200 py-1.5 text-sm dark:border-slate-800" [class.font-medium]="st === 'running'">
                  @if (clickable(st)) {
                    <button type="button" class="shrink-0 rounded-md p-1 hover:bg-slate-100 disabled:opacity-50 max-sm:p-2 dark:hover:bg-slate-800"
                            [class]="colour(st)" [title]="tip(st)" [attr.aria-label]="label(s) + ': ' + tip(st)" [disabled]="busy() || st === 'stopping'" (click)="stepClick(s, st)">
                      <ng-container *ngTemplateOutlet="icon; context: { $implicit: st }" />
                    </button>
                  } @else {
                    <span class="shrink-0 p-1" role="img" [class]="colour(st)" [title]="tip(st)" [attr.aria-label]="label(s) + ': ' + tip(st)">
                      <ng-container *ngTemplateOutlet="icon; context: { $implicit: st }" />
                    </span>
                  }
                  <span>{{ label(s) }}</span>
                  @if (results()[s]; as r) { <span class="ms-auto text-end font-normal text-slate-600 dark:text-slate-400">{{ summary(s, r) }}</span> }
                </li>
              }
            </ol>
            @if (run?.error && paused()?.id !== run?.run_id) {
              @let why = plainError(run?.reason_code, run?.reason_params, run?.error ?? '', failedStage());
              <div class="alert alert-error mt-3" role="alert">
                <p dir="auto">{{ why.text }}</p>
                @if (why.detail) { <ng-container *ngTemplateOutlet="details; context: { $implicit: why.detail }" /> }
              </div>
            }
          </section>
        }

        @if (live.events().length || live.run()?.run_id) {
          <details class="mt-6" [open]="running()">
            <summary class="cursor-pointer font-medium text-slate-900 dark:text-white">{{ 'live.activity' | t }}</summary>
            <div #log class="mt-3 max-h-[32vh] overflow-auto text-xs" role="log" aria-live="polite">
              @for (e of live.events(); track $index) {
                <div class="flex gap-3 py-0.5" [class]="eventClass(e)">
                  <span class="shrink-0 text-slate-500" dir="ltr">{{ e.at | dt: 'time' }}</span>
                  <span class="min-w-0 break-words" dir="auto">{{ describe(e) }}</span>
                </div>
              }
            </div>
          </details>
        }
      </div>

      @if (applyRunning()) {
        <section class="min-w-0 space-y-3">
          <h2>{{ 'live.view.title' | t }}</h2>
          @if (live.shot(); as s) {
            <p class="text-sm font-medium" dir="auto">{{ 'live.view.job' | t: { title: s.title, company: s.company } }}</p>
            <img class="w-full rounded-md border border-slate-200 dark:border-slate-700" [src]="s.url" [alt]="'live.view.alt' | t">
          } @else {
            <p class="text-sm text-slate-500">{{ 'live.view.waiting' | t }}</p>
          }
          <p class="text-xs text-slate-500">{{ 'live.view.caption' | t }}</p>
        </section>
      }
    </div>

    <ng-template #icon let-st>
      @switch (st) {
        @case ('done') { <svg class="block size-5" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg> }
        @case ('running') { <svg class="block size-5" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg> }
        @case ('stopping') { <svg class="block size-5" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg> }
        @case ('waiting') { <svg class="block size-5" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" /></svg> }
        @case ('notRun') { <svg class="block size-5" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" /></svg> }
        @default { <svg class="block size-5" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z" /></svg> }
      }
    </ng-template>

    <ng-template #details let-raw>
      <details class="mt-2 text-xs">
        <summary class="cursor-pointer font-medium">{{ 'common.details' | t }}</summary>
        <p class="mt-1 break-words" dir="auto">{{ raw }}</p>
      </details>
    </ng-template>
  `,
})
export class LivePage {
  protected readonly live = inject(Live);
  private readonly api = inject(Api);
  protected readonly applyLive = signal(false);
  protected readonly paused = signal<RecentRun | null>(null);
  /** The newest run as saved: step results outlive a stop, a resume and a server restart. */
  private readonly latest = signal<RecentRun | null>(null);
  /** A step's play button was refused for want of LibreOffice (409 + code): the offer shows instead of an error. */
  protected readonly needsLibreOffice = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  private readonly i18n = inject(I18n);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly running = computed(() => !!this.live.run()?.running);
  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  protected readonly applyRunning = computed(() => !!this.live.run()?.running && this.live.run()?.stage === 'apply');
  protected readonly runId = computed(() => this.live.run()?.run_id ?? this.latest()?.id ?? null);
  /** The saved run, while it is the one on screen. */
  private readonly saved = computed(() => {
    const l = this.latest();
    return l?.id === this.runId() ? l : null;
  });
  /** Every step of this run: a resumed run's live state only lists the steps it still has to do. */
  protected readonly steps = computed(() => {
    const on = new Set<Stage>([...(this.live.run()?.stages ?? []), ...(this.saved()?.stages ?? [])]);
    return STAGES.filter((s) => on.has(s));
  });
  protected readonly results = computed(() => ({ ...this.saved()?.stats, ...this.live.run()?.results }));
  protected readonly kind = computed(() => runKind(this.steps()));

  constructor() {
    this.api.get<{ apply_live: boolean }>('/status').then((st) => this.applyLive.set(st.apply_live)).catch(() => undefined);
    effect(() => {
      this.live.events(); // keep the log scrolled to the newest line
      const el = this.log()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
    effect(() => {
      this.live.changed();
      this.live.run()?.running; // a run starting is no `changed`, and its steps must show
      this.api.get<{ recent: RecentRun[] }>('/runs').then((r) => {
        this.paused.set(r.recent.find((x) => x.status === 'paused') ?? null);
        this.latest.set(r.recent[0] ?? null);
      }).catch(() => undefined);
    });
  }

  protected num = (n: number | null): string => fmtNum(this.loc(), n);

  label(s: Stage): string {
    return stageLabel(this.i18n, s, this.applyLive());
  }

  /** "Search 3" / "Applying 4" / "Search and apply 5". */
  protected runTitle(kind: 'search' | 'apply' | 'mixed', id: number | null): string {
    return this.i18n.t('live.runTitle.' + kind, { id: this.num(id) });
  }

  /** Why a run stopped or paused, in the UI language; the server's English text when it sent no code we know. */
  protected reasonText(code: string | null | undefined, params: Record<string, unknown> | undefined, fallback: string): string {
    return runReason(this.i18n, code, params, fallback);
  }

  protected stepState(s: Stage): StepState {
    const run = this.live.run();
    if (run?.running && run.stage === s) return run.stopping ? 'stopping' : 'running';
    const results = this.results();
    if (results[s]) return 'done';
    if (run?.running) return 'waiting';
    const open = this.steps().filter((x) => !results[x]);
    const saved = this.saved();
    if (saved?.status === 'done') return 'notRun';
    if (open[0] === s) return run?.status === 'paused' || saved?.status === 'paused' ? 'paused' : run?.error || saved?.reason_code ? 'failed' : 'stopped';
    return open[1] === s ? 'next' : 'notRun';
  }

  protected clickable(st: StepState): boolean {
    return ['running', 'stopping', 'stopped', 'paused', 'failed', 'next'].includes(st);
  }

  protected tip(st: StepState): string {
    return this.i18n.t(STEP_TIP[st]);
  }

  protected colour(st: StepState): string {
    return STEP_COLOUR[st] ?? 'text-slate-500';
  }

  /** Pause stops the run; play goes on from this step, and the steps before it count as done with what they stored. */
  protected async stepClick(s: Stage, st: StepState): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    this.needsLibreOffice.set(false);
    try {
      if (st === 'running') await this.api.post('/runs/cancel');
      else await this.api.post('/runs', { stages: this.steps().slice(this.steps().indexOf(s)), skip_earlier: true });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'needs_libreoffice') this.needsLibreOffice.set(true);
      else this.error.set(e instanceof ApiError && e.code === 'needs_tectonic' ? this.i18n.t('run.reason.needs_tectonic') : (e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  summary(s: Stage, r: Record<string, unknown>): string {
    if (r['stopped_early']) return this.i18n.t('live.sum.stoppedEarly');
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

  /** The error of a stage or run event in plain words; an unknown one is left out here (the banner has it under "Details"). */
  private eventError(code: string | null | undefined, params: Record<string, unknown> | undefined, raw: string | undefined): string {
    if (!raw) return '';
    const why = this.plainError(code, params, raw, null);
    return why.detail ? '' : why.text;
  }

  /**
   * "Filling Stripe — Backend Engineer…" / "Filled (practice) ✓ · Stripe — Backend Engineer": one line per job.
   * A newer server adds `questions` and `reason` to the result line ("Needs you: 3 questions", "Skipped: job closed");
   * without them, or with a reason we have no words for, the line is the plain one.
   */
  private jobLine(e: LiveEvent): string | null {
    const p = e.params ?? {};
    const j = this.live.jobs()[Number(p['job'])];
    const isolate = (s: string) => '⁨' + s + '⁩'; // names in any script keep their own direction
    const job = j ? (j.company ? `${isolate(j.company)} — ${isolate(j.title)}` : isolate(j.title)) : this.i18n.t('live.line.thisJob');
    if (e.code === 'apply_job_start') return this.i18n.t('live.line.filling', { job });
    if (e.code === 'apply_crashed') return this.i18n.t('live.line.crashed', { job });
    if (e.code === 'apply_filling') return this.i18n.t('live.line.filling', { job });
    const status = String(p['status']);
    const n = Number(p['questions']);
    if (status === 'needs_user' && n > 0) return this.i18n.plural('live.line.needsQuestions', n, { job });
    const reason = typeof p['reason'] === 'string' && this.i18n.has('live.reason.' + p['reason']) ? this.i18n.t('live.reason.' + p['reason']) : '';
    if (reason && ['needs_user', 'failed', 'skipped'].includes(status)) return this.i18n.t(`live.line.${status}.why`, { reason, job });
    const key = 'live.line.' + status;
    return this.i18n.has(key) ? this.i18n.t(key, { job }) : null;
  }

  describe(e: LiveEvent): string {
    if (e.type === 'log') {
      const line = ['apply_filling', 'apply_job_start', 'apply_job', 'apply_crashed'].includes(e.code ?? '') ? this.jobLine(e) : null;
      if (line) return line;
      return e.code ? this.i18n.msg({ message: e.message ?? '', code: e.code, params: e.params }, 'log.') : (e.message ?? '');
    }
    const status = labelOr(this.i18n, 'live.status.', e.status ?? '');
    if (e.type === 'stage') {
      const error = this.eventError(e.code, e.params, e.error);
      return this.i18n.t(error ? 'live.event.stageErr' : 'live.event.stage', { stage: this.label(e.stage!), status, error });
    }
    const error = this.eventError(e.reason_code, e.reason_params, e.error);
    return this.i18n.t(error ? 'live.event.runErr' : 'live.event.run', { status, error });
  }

  /** The stage that failed in this run, for "Something went wrong in ...". */
  protected failedStage(): Stage | null {
    const e = [...this.live.events()].reverse().find((x) => x.type === 'stage' && x.status === 'failed');
    return e?.stage ?? null;
  }

  /**
   * Why a run stopped, in plain words. A code we have words for is translated; anything else becomes "Something went
   * wrong in {stage}." with the raw text kept for a "Details" toggle.
   */
  protected plainError(code: string | null | undefined, params: Record<string, unknown> | undefined, raw: string, stage: Stage | null): { text: string; detail: string } {
    if (code && code !== 'pipeline_error' && this.i18n.has('run.reason.' + code)) return { text: this.reasonText(code, params, raw), detail: '' };
    return { text: stage ? this.i18n.t('live.err.in', { stage: this.label(stage) }) : this.i18n.t('live.err.generic'), detail: raw };
  }

  /** How the run ended, once it is not running: a clear end state for "Finished" and for "Stopped". */
  protected endKind(run: RunState): 'finished' | 'stopped' | null {
    if (run.running) return null;
    return run.status === 'finished' ? 'finished' : run.status === 'cancelled' ? 'stopped' : null;
  }

  protected endSummary(run: RunState, end: 'finished' | 'stopped'): string {
    if (end === 'finished') {
      const last = [...run.stages].reverse().find((s) => run.results[s]);
      return last ? this.summary(last, run.results[last]) : '';
    }
    const events = this.live.events();
    let from = events.length - 1;
    while (from >= 0 && !(events[from].type === 'run' && events[from].status === 'started')) from--;
    const jobs = events.slice(from + 1).filter((x) => x.type === 'log' && x.code === 'apply_job').length;
    const steps = run.stages.filter((s) => run.results[s]).length;
    return jobs > 0 || (steps === 0 && run.stages.includes('apply') && run.stages.length === 1)
      ? this.i18n.plural('live.stopped.jobs', jobs)
      : this.i18n.plural('live.stopped.steps', steps);
  }

  eventClass(e: LiveEvent): string {
    if (e.code === 'apply_crashed') return 'text-rose-700 dark:text-rose-400';
    if (e.code === 'apply_job') {
      const s = String(e.params?.['status']);
      if (s === 'failed') return 'text-rose-700 dark:text-rose-400';
      if (s === 'needs_user') return 'text-amber-700 dark:text-amber-400';
      if (s === 'applied' || s === 'dry_run') return 'text-emerald-700 dark:text-emerald-400';
    }
    if (e.level === 'WARNING' || e.status === 'failed') return 'text-amber-700 dark:text-amber-400';
    if (e.level === 'ERROR') return 'text-rose-700 dark:text-rose-400';
    if (e.type !== 'log') return 'font-semibold text-slate-900 dark:text-white';
    return 'text-slate-600 dark:text-slate-400';
  }
}

/**
 * Home's "Searches" card: when the last search ran, the automatic schedule, and (folded) a run of chosen steps only.
 * The main "Find new jobs" button is Home's next-step card; this card is for what that button does not offer.
 */
@Component({
  selector: 'app-searches',
  imports: [DtPipe, LibreOfficeCard, TPipe],
  template: `
    <section id="schedule" class="card space-y-4" aria-labelledby="home-sched">
      <h2 id="home-sched">{{ 'home.search.title' | t }}</h2>
      <p class="text-sm text-slate-600 dark:text-slate-400">
        {{ 'home.last' | t }}
        @if (lastSearch(); as at) { <bdi>{{ at | dt: 'when' }}</bdi> } @else { {{ 'home.never' | t }} }
      </p>
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
              <button type="button" class="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
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
      <details class="border-t border-slate-100 pt-4 dark:border-slate-800">
        <summary class="cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-300">{{ 'home.steps' | t }}</summary>
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
        <button type="button" class="btn mt-3" (click)="start()" [disabled]="running() || !chosen().size || busy()">{{ startLabel() | t }}</button>
        @if (error()) { <div class="alert alert-error mt-3" dir="auto">{{ error() }}</div> }
        @if (needsLibreOffice()) { <div class="mt-3"><app-libreoffice-card /></div> }
      </details>
    </section>
  `,
})
export class SearchesCard {
  private readonly live = inject(Live);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly stages = STAGES;
  protected readonly dayKeys = DAYS;
  protected readonly applyLive = signal(false);
  protected readonly chosen = signal(rememberedStages());
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
  protected readonly running = computed(() => !!this.live.run()?.running);
  protected readonly lastSearch = signal<string | null>(null);
  protected readonly schedule = signal<ScheduleSection | null>(null);
  protected readonly scheduleDirty = signal(false);
  protected readonly scheduleError = signal('');
  protected readonly nextRuns = signal<string[]>([]);

  constructor() {
    this.api.get<{ apply_live: boolean }>('/status').then((st) => this.applyLive.set(st.apply_live)).catch(() => undefined);
    void this.loadSchedule();
    effect(() => {
      this.live.changed();
      this.api.get<{ recent: { started_at: string; finished_at: string | null }[] }>('/runs').then((r) => {
        const last = r.recent[0];
        this.lastSearch.set(last ? (last.finished_at ?? last.started_at) + 'Z' : null); // the server sends UTC without a zone
      }).catch(() => undefined);
    });
  }

  label(s: Stage): string {
    return stageLabel(this.i18n, s, this.applyLive());
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
}
