import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Api } from '../api';
import { GoLiveCard } from '../components/golive';
import { Hint } from '../components/hint';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, localeOf } from '../locale';
import { Shell } from '../shell';
import { APPLY_STAGES, GoLive, Report, ScheduleSection, SEARCH_STAGES, SearchConfig, setupDone, Stage } from '../types';

/** The one thing Home asks the user to do next (ux-plan 8.1). `link` = go there; no link = start a run. */
interface Smart {
  kind: 'setup' | 'running' | 'finish' | 'review' | 'apply' | 'find';
  message: string;
  label: string;
  link?: string;
  query?: Record<string, string>;
  stages?: Stage[];
}

/** A line in the Tasks list. */
interface HomeTask {
  id: string;
  title: string;
  hint?: boolean;
  /** The go-live task: its title toggles the guided card. */
  golive?: boolean;
}

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];
const DEFAULT_TIME = '09:00';

@Component({
  selector: 'app-home',
  imports: [DatePipe, GoLiveCard, Hint, RouterLink, TPipe],
  template: `
    <h1>{{ 'home.title' | t }}</h1>
    <app-hint id="home">{{ 'hint.home' | t }}</app-hint>

    @if (shell.status(); as s) {
      @if (smart(); as sm) {
        <section class="card mt-6" aria-labelledby="home-next">
          <h2 id="home-next" class="text-sm font-medium tracking-wide text-slate-500 uppercase rtl:tracking-normal dark:text-slate-400">{{ 'home.next' | t }}</h2>
          <p class="mt-2 text-lg text-slate-900 dark:text-white" dir="auto">{{ sm.message }}</p>
          <div class="mt-4 flex flex-wrap items-center gap-3">
            @if (sm.link) {
              <a class="btn btn-primary no-underline hover:no-underline" [routerLink]="sm.link" [queryParams]="sm.query">{{ sm.label }}</a>
            } @else {
              <button type="button" class="btn btn-primary" (click)="go(sm)" [disabled]="busy()">{{ busy() ? ('home.working' | t) : sm.label }}</button>
            }
            @if (sm.kind === 'running') {
              <button type="button" class="btn btn-danger" (click)="stop()" [disabled]="busy() || stopping()">{{ (stopping() ? 'live.stopping' : 'live.stop') | t }}</button>
            }
          </div>
          @if (error()) { <div class="alert alert-error mt-3" role="alert" dir="auto">{{ error() }}</div> }
        </section>
      }

      <section class="card mt-6" aria-labelledby="home-funnel">
        <h2 id="home-funnel">{{ 'home.funnel.title' | t }}</h2>
        <ol class="mt-3 flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
          @for (f of funnel(); track f.id; let last = $last) {
            <li class="flex items-center gap-2">
              <a [routerLink]="f.link" [queryParams]="f.query" class="rounded-lg border border-slate-200 px-3 py-1.5 no-underline hover:bg-slate-50 hover:no-underline dark:border-slate-700 dark:hover:bg-slate-800">
                <strong class="text-base text-slate-900 dark:text-white">{{ num(f.n) }}</strong> {{ f.label | t }}
              </a>
              @if (!last) { <span aria-hidden="true" class="inline-block text-slate-400 rtl:rotate-180">{{ f.sep }}</span> }
            </li>
          }
        </ol>
        <p class="hint">{{ 'home.funnel.hint' | t }}</p>
      </section>

      <section class="card mt-6 space-y-3" aria-labelledby="home-sched">
        <h2 id="home-sched">{{ 'home.search.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">
          {{ 'home.last' | t }}
          @if (lastSearch(); as at) { <bdi>{{ at | date: 'EEE d MMM, HH:mm' : undefined : loc() }}</bdi> } @else { {{ 'home.never' | t }} }
          @if (s.next_run; as next) { · {{ 'home.next.run' | t }} <bdi>{{ next | date: 'EEE d MMM, HH:mm' : undefined : loc() }}</bdi> }
        </p>
        @if (schedule(); as sc) {
          <div class="flex flex-wrap items-center gap-3 text-sm">
            <label class="flex items-center gap-2 font-medium">
              <input type="checkbox" role="switch" [checked]="sc.enabled" [disabled]="saving()" (change)="setEnabled(!sc.enabled)">
              {{ (custom() ? 'home.sched.custom' : 'home.sched.every') | t }}
            </label>
            @if (!custom()) {
              <input type="time" class="input w-32" dir="ltr" [value]="time()" [attr.aria-label]="'home.sched.time' | t" [disabled]="saving()" (change)="setTime($event)">
            }
            <a routerLink="/activity" fragment="schedule">{{ 'home.sched.more' | t }}</a>
          </div>
          @if (scheduleError()) { <div class="alert alert-error" role="alert" dir="auto">{{ scheduleError() }}</div> }
        }
      </section>

      @if (tasks().length) {
        <section class="card mt-6" aria-labelledby="home-tasks">
          <h2 id="home-tasks">{{ 'home.tasks.title' | t }}</h2>
          <ul class="mt-3 space-y-3 text-sm">
            @for (task of tasks(); track task.id) {
              <li>
                @if (task.golive) {
                  <button type="button" class="font-medium text-brand-700 hover:underline dark:text-brand-300" [attr.aria-expanded]="goLiveOpen()" aria-controls="home-golive" (click)="goLiveOpen.set(!goLiveOpen())">{{ task.title }}</button>
                  @if (goLiveOpen()) {
                    <div id="home-golive" class="mt-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700">
                      <app-golive (enabled)="justOn.set(true)" (cancel)="goLiveOpen.set(false)" />
                    </div>
                  }
                } @else {
                  <div class="font-medium">{{ task.title }}</div>
                }
                @if (task.hint) { <p class="hint">{{ 'home.task.hintA' | t }} <code dir="ltr">linkit doctor</code> {{ 'home.task.hintB' | t }}</p> }
              </li>
            }
          </ul>
        </section>
      }
    } @else {
      <p class="mt-6 text-sm text-slate-500">{{ 'common.loading' | t }}</p>
    }
  `,
})
export class HomePage {
  protected readonly shell = inject(Shell);
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  protected readonly stopping = computed(() => !!this.live.run()?.stopping);
  private readonly router = inject(Router);
  private readonly i18n = inject(I18n);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  private readonly report = signal<Report | null>(null);
  protected readonly lastSearch = signal<string | null>(null);
  protected readonly schedule = signal<ScheduleSection | null>(null);
  protected readonly saving = signal(false);
  protected readonly scheduleError = signal('');
  private readonly golive = signal<GoLive | null>(null);
  protected readonly goLiveOpen = signal(false);
  /** Real applications were turned on from the card: the card stays, showing its "now on" message. */
  protected readonly justOn = signal(false);

  /** A schedule made on Activity (some days, or several times) is shown as such, not flattened to one daily time. */
  protected readonly custom = computed(() => {
    const sc = this.schedule();
    return !!sc && sc.enabled && (sc.days.length < ALL_DAYS.length || sc.times.length > 1);
  });
  protected readonly time = computed(() => this.schedule()?.times[0] ?? DEFAULT_TIME);

  private readonly count = (state: string): number => this.shell.status()?.states[state] ?? 0;

  protected readonly smart = computed<Smart | null>(() => {
    const s = this.shell.status();
    if (!s) return null;
    const t = (key: string, n?: number) => this.i18n.t(key, n === undefined ? undefined : { n: this.num(n) });
    const plural = (key: string, n: number) => t(`${key}.${n === 1 ? 'one' : 'other'}`, n);
    const run = this.live.run();
    if (!s.setup.required_done) {
      const step = setupDone(s.setup) + 1;
      return { kind: 'setup', message: t('smart.setup.msg'), label: this.i18n.t('smart.setup', { n: step, total: 4 }), link: '/welcome' };
    }
    if (run?.running) {
      const found = Number(run.results['discover']?.['new'] ?? NaN);
      const applying = run.stage === 'apply';
      const key = applying ? 'smart.applying' : 'smart.searching';
      const label = run.stopping ? t('live.stopping') : Number.isFinite(found) && !applying ? this.i18n.t('smart.searchingN', { n: this.num(found) }) : t(key);
      return { kind: 'running', message: t('smart.running.msg'), label, link: '/activity' };
    }
    if (s.actions_open > 0) {
      return { kind: 'finish', message: plural('smart.finish.msg', s.actions_open), label: plural('smart.finish', s.actions_open), link: '/needs-you', query: { tab: 'finish' } };
    }
    const review = this.count('awaiting_review');
    if (review > 0) {
      return { kind: 'review', message: plural('smart.review.msg', review), label: plural('smart.review', review), link: '/needs-you', query: { tab: 'approve' } };
    }
    const ready = s.ready_to_apply; // the server knows what the next apply stage would pick (practised jobs are left out)
    if (ready > 0) {
      const label = plural('smart.apply', ready) + (s.apply_live ? '' : ` (${t('smart.practice')})`);
      return { kind: 'apply', message: plural('smart.apply.msg', ready), label, stages: APPLY_STAGES };
    }
    const none = Object.values(s.states).reduce((a, b) => a + b, 0) === 0;
    return { kind: 'find', message: t(none ? 'smart.find.none' : 'smart.find.msg'), label: t(none ? 'smart.findFirst' : 'smart.find'), stages: SEARCH_STAGES };
  });

  protected readonly funnel = computed(() => {
    const s = this.shell.status();
    if (!s) return [];
    const tiers = this.report()?.tiers ?? {};
    const found = Object.values(s.states).reduce((a, b) => a + b, 0);
    // "passed filters" = ranked or later; the Jobs page knows it as the state group `passed`
    const passed = found - ['discovered', 'enriched', 'filtered_out'].reduce((a, k) => a + this.count(k), 0);
    return [
      { id: 'found', n: found, label: 'home.funnel.found', link: '/jobs', query: {}, sep: '→' },
      { id: 'passed', n: passed, label: 'home.funnel.passed', link: '/jobs', query: { state: 'passed' }, sep: '→' },
      { id: 'strong', n: tiers['high'] ?? 0, label: 'home.funnel.strong', link: '/jobs', query: { tier: 'high' }, sep: '·' },
      { id: 'possible', n: tiers['mid'] ?? 0, label: 'home.funnel.possible', link: '/jobs', query: { tier: 'mid' }, sep: '→' },
      // practice mode sends nothing, so "applied" would read 0: show how many forms were practised, linking to the history
      s.apply_live
        ? { id: 'applied', n: this.count('applied'), label: 'home.funnel.applied', link: '/jobs', query: { state: 'applied' }, sep: '' }
        : { id: 'applied', n: s.practiced, label: 'home.funnel.practiced', link: '/activity', query: { tab: 'history' }, sep: '' },
    ];
  });

  /** Things to do outside the main flow. */
  protected readonly tasks = computed<HomeTask[]>(() => {
    const s = this.shell.status();
    if (!s) return [];
    const list: HomeTask[] = [];
    if (!s.libreoffice) list.push({ id: 'libreoffice', title: this.i18n.t('home.task.libreoffice'), hint: true });
    const goLive = this.goLiveTask();
    if (goLive) list.push(goLive);
    return list;
  });

  constructor() {
    effect(() => {
      this.live.changed(); // numbers move whenever a stage ends
      void this.loadNumbers();
    });
    void this.loadSchedule();
  }

  protected num = (n: number): string => fmtNum(this.loc(), n);

  /** "Ready to apply for real?" once a practice run filled a form (ux-plan 8.2); the card opens under it. */
  protected goLiveTask(): HomeTask | null {
    const live = this.shell.status()?.apply_live;
    if (!this.justOn() && (live || !this.golive()?.eligible)) return null;
    return { id: 'golive', title: this.i18n.t('golive.title'), golive: true };
  }

  private async loadNumbers(): Promise<void> {
    try {
      const [report, runs, golive] = await Promise.all([
        this.api.get<Report>('/report'),
        this.api.get<{ recent: { started_at: string; finished_at: string | null }[] }>('/runs'),
        this.api.get<GoLive>('/golive'),
      ]);
      this.report.set(report);
      this.golive.set(golive);
      const last = runs.recent[0];
      this.lastSearch.set(last ? (last.finished_at ?? last.started_at) + 'Z' : null); // the server sends UTC without a zone
    } catch {
      // the numbers stay as they were; the live socket triggers another load
    }
  }

  private async loadSchedule(): Promise<void> {
    try {
      this.schedule.set((await this.api.get<SearchConfig>('/search')).schedule);
    } catch (e) {
      this.scheduleError.set((e as Error).message);
    }
  }

  /** Start the search or the apply stages; a paused or unfinished run resumes on its own (`new` stays false). */
  protected async go(sm: Smart): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.post('/runs', { stages: sm.stages, new: false });
      await this.router.navigate(['/activity']);
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  protected async stop(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.post('/runs/cancel');
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  protected setEnabled(enabled: boolean): void {
    // turning it on from Home means "every day at one time"; a custom schedule from Activity is kept as it is
    const sc = this.schedule();
    if (!sc) return;
    void this.saveSchedule(enabled && !this.custom() ? { ...sc, enabled, days: ALL_DAYS, times: [sc.times[0] ?? DEFAULT_TIME] } : { ...sc, enabled });
  }

  protected setTime(e: Event): void {
    const value = (e.target as HTMLInputElement).value;
    const sc = this.schedule();
    if (value && sc) void this.saveSchedule({ ...sc, times: [value] });
  }

  private async saveSchedule(schedule: ScheduleSection): Promise<void> {
    this.saving.set(true);
    this.scheduleError.set('');
    try {
      // the whole config is one document: read it fresh so other pages' edits are not overwritten
      const cfg = await this.api.get<SearchConfig>('/search');
      this.schedule.set((await this.api.put<SearchConfig>('/search', { ...cfg, schedule })).schedule);
      await this.shell.refresh(); // the "next search" time
    } catch (e) {
      this.scheduleError.set((e as Error).message);
      await this.loadSchedule(); // show what is really saved
    } finally {
      this.saving.set(false);
    }
  }
}
