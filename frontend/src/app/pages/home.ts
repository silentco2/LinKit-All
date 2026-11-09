import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, ApiError } from '../api';
import { GoLiveCard } from '../components/golive';
import { LibreOfficeCard } from '../components/libreoffice-card';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, localeOf } from '../locale';
import { Shell } from '../shell';
import { ActionItem, APPLY_STAGES, GoLive, JobRow, Report, SEARCH_STAGES, setupDone, Stage } from '../types';
import { LivePage, SearchesCard } from './live';
import { ReportPage } from './report';

/** The one thing Home asks the user to do next (ux-plan 8.1). `link` = go there; no link = start a run. */
interface Smart {
  kind: 'setup' | 'running' | 'finish' | 'review' | 'apply' | 'find';
  message: string;
  label: string;
  link?: string;
  query?: Record<string, string>;
  stages?: Stage[];
}

/** The sheet on top of the pile next to the lead sentence: the real next item. */
interface TopSheet {
  title: string;
  sub: string;
  label: string;
  detail: string;
  stamp: string;
  tone: string;
  pile: number;
}

@Component({
  selector: 'app-home',
  imports: [GoLiveCard, LibreOfficeCard, LivePage, ReportPage, RouterLink, SearchesCard, TPipe],
  template: `
    @if (shell.status(); as s) {
      @if (smart(); as sm) {
        <section class="mt-2 grid items-center gap-x-14 gap-y-10" [class]="top() || setupRows().length ? 'md:grid-cols-2' : ''">
          <div class="min-w-0">
            <h1>{{ sm.message }}</h1>
            @if (sm.kind === 'finish' || sm.kind === 'review') { <p class="mt-3 max-w-[34em] text-[15px] text-slate-600 dark:text-slate-400">{{ 'home.lead.' + sm.kind | t }}</p> }
            <div class="mt-5 flex flex-wrap items-center gap-2">
              @if (sm.kind === 'running') {
                <span class="text-base font-medium text-brand-700 dark:text-brand-300" role="status">{{ sm.label }}</span>
                <button type="button" class="btn btn-danger" (click)="stop()" [disabled]="busy() || stopping()">{{ (stopping() ? 'live.stopping' : 'live.stop') | t }}</button>
              } @else if (sm.link) {
                <a class="btn btn-primary no-underline hover:no-underline" [routerLink]="sm.link" [queryParams]="sm.query">{{ sm.label }}</a>
              } @else {
                <button type="button" class="btn btn-primary" (click)="go(sm)" [disabled]="busy()">{{ busy() ? ('home.working' | t) : sm.label }}</button>
              }
              @for (r of extras(); track r.id) {
                @if (r.smart; as x) {
                  @if (x.link) {
                    <a class="btn no-underline hover:no-underline" [routerLink]="x.link" [queryParams]="x.query" [title]="x.message">{{ x.label }}</a>
                  } @else {
                    <button type="button" class="btn" (click)="go(x)" [disabled]="busy()" [title]="x.message">{{ busy() ? ('home.working' | t) : x.label }}</button>
                  }
                } @else {
                  <button type="button" class="btn" [attr.aria-expanded]="goLiveOpen()" aria-controls="home-golive" (click)="toggleGoLive()">{{ 'golive.offer' | t }}</button>
                }
              }
            </div>
            @if (applyHint(); as hint) { <p class="hint mt-2">{{ hint }}</p> }
            @if (error()) { <div class="alert alert-error mt-3" role="alert" dir="auto">{{ error() }}</div> }
            @if (needsLibreOffice()) { <div class="mt-3"><app-libreoffice-card /></div> }
          </div>

          @if (top(); as t) {
            <div class="sheets">
              @if (t.pile > 2) { <div class="under"></div> }
              @if (t.pile > 1) { <div class="under"></div> }
              <article class="card">
                <h2 class="!text-xl" dir="auto">{{ t.title }}</h2>
                <div class="text-sm text-slate-600 dark:text-slate-400" dir="auto">{{ t.sub }}</div>
                <div class="mt-4 border-t border-slate-200 pt-3 pe-24 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-400">
                  {{ t.label }}
                  @if (t.detail) { <div class="mt-1 line-clamp-2 text-base text-slate-900 dark:text-white" dir="auto">{{ t.detail }}</div> }
                </div>
                <span [class]="'stamp ' + t.tone">{{ t.stamp }}</span>
              </article>
            </div>
          } @else if (setupRows().length) {
            <div class="sheets">
              <article class="card">
                <h2 class="!text-xl">{{ 'shell.setupChip' | t: { n: setupCount(), total: 4 } }}</h2>
                <ol class="mt-3 text-sm">
                  @for (row of setupRows(); track row.label) {
                    <li class="flex min-h-10 items-center gap-2.5 border-b border-slate-200 dark:border-slate-800" [class]="row.done ? 'text-slate-500' : 'font-medium'">
                      <svg class="icon" [class.invisible]="!row.done" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 13l4 4L19 7" /></svg>
                      {{ row.label | t }}
                    </li>
                  }
                </ol>
              </article>
            </div>
          }
        </section>

        @if (goLiveOpen()) {
          <div id="home-golive" class="card mt-8"><app-golive (enabled)="justOn.set(true)" (cancel)="goLiveOpen.set(false)" /></div>
        }
      }

      @if (!s.libreoffice) { <div class="mt-8 max-w-2xl"><app-libreoffice-card /></div> }

      <section class="mt-12" aria-labelledby="home-funnel">
        <h2 id="home-funnel" class="sr-only">{{ 'home.funnel.title' | t }}</h2>
        <nav class="folder-tabs" [attr.aria-labelledby]="'home-funnel'">
          @for (f of funnel(); track f.id) {
            @if (f.link) {
              <a class="folder-tab" [routerLink]="f.link" [queryParams]="f.query"><strong>{{ num(f.n) }}</strong>{{ f.label | t }}</a>
            } @else {
              <div class="folder-tab"><strong>{{ num(f.n) }}</strong>{{ f.label | t }}</div>
            }
          }
        </nav>
        <div class="card !rounded-t-none">
          <app-live />
          <p class="hint">{{ 'home.funnel.hint' | t }}</p>
        </div>
      </section>

      <div class="mt-10"><app-report /></div>
      <div class="mt-6"><app-searches /></div>

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
  private readonly i18n = inject(I18n);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  /** A run refused for a missing tool (409 + code): the LibreOffice offer shows instead of an error. */
  protected readonly needsLibreOffice = signal(false);
  /** How many of the ready jobs are strong matches (the rest were approved by the user); null until known. */
  private readonly readyMix = signal<number | null>(null);
  private readonly report = signal<Report | null>(null);
  private readonly golive = signal<GoLive | null>(null);
  protected readonly goLiveOpen = signal(false);
  /** Real applications were turned on from the card: the card stays, showing its "now on" message. */
  protected readonly justOn = signal(false);
  private readonly firstAction = signal<ActionItem | null>(null);
  private readonly firstReview = signal<JobRow | null>(null);
  private readonly firstReady = signal<JobRow | null>(null);
  private readonly openCount = computed(() => this.shell.status()?.actions_open ?? 0);

  private readonly count = (state: string): number => this.shell.status()?.states[state] ?? 0;

  protected readonly smart = computed<Smart | null>(() => {
    const s = this.shell.status();
    if (!s) return null;
    const t = (key: string, n?: number) => this.i18n.t(key, n === undefined ? undefined : { n: this.num(n) });
    const plural = (key: string, n: number) => this.i18n.plural(key, n);
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
      return { kind: 'running', message: t('smart.running.msg'), label };
    }
    if (s.actions_open > 0) {
      return { kind: 'finish', message: plural('smart.finish.msg', s.actions_open), label: plural('smart.finish', s.actions_open), link: '/needs-you', query: { tab: 'finish' } };
    }
    const review = this.shell.reviewCount();
    if (review > 0) {
      return { kind: 'review', message: plural('smart.review.msg', review), label: plural('smart.review', review), link: '/needs-you', query: { tab: 'approve' } };
    }
    const apply = this.applyAction();
    if (apply) return apply;
    const none = Object.values(s.states).reduce((a, b) => a + b, 0) === 0;
    return { kind: 'find', message: t(none ? 'smart.find.none' : 'smart.find.msg'), label: t(none ? 'smart.findFirst' : 'smart.find'), stages: SEARCH_STAGES };
  });

  /** Start the apply stage: "Apply to 3 jobs (practice)", with where the 3 come from. Null when nothing is ready. */
  private readonly applyAction = computed<Smart | null>(() => {
    const s = this.shell.status();
    const ready = s?.ready_to_apply ?? 0;
    if (!s || ready <= 0) return null;
    const plural = (key: string, n: number) => this.i18n.plural(key, n);
    const label = plural('smart.apply', ready) + (s.apply_live ? '' : ` (${this.i18n.t('smart.practice')})`);
    const strong = Math.min(this.readyMix() ?? -1, ready);
    const approved = ready - strong;
    const parts = [strong > 0 && plural('home.apply.strong', strong), approved > 0 && plural('home.apply.approved', approved)].filter(Boolean);
    const message = strong < 0 ? plural('smart.apply.msg', ready) : parts.join(this.i18n.t('home.apply.and'));
    return { kind: 'apply', message, label, stages: APPLY_STAGES };
  });

  /** The second button on Home: applying is always one click away once there is something to apply to. */
  protected readonly applyToo = computed<Smart | null>(() => {
    const sm = this.smart();
    return sm && (sm.kind === 'finish' || sm.kind === 'review') ? this.applyAction() : null;
  });

  /** Jobs wait for a yes or no behind another main action (a parked application, a running search): keep the queue in sight. */
  private readonly reviewToo = computed<Smart | null>(() => {
    const sm = this.smart();
    const n = this.shell.reviewCount(); // what the nav badge shows: jobs just approved or skipped (Undo window) are not counted
    if (!sm || sm.kind === 'review' || n <= 0) return null;
    return { kind: 'review', message: this.i18n.plural('smart.review.msg', n), label: this.i18n.plural('smart.review', n), link: '/needs-you', query: { tab: 'approve' } };
  });

  /** Buttons next to the main one, most important first, at most two. */
  protected readonly extras = computed<{ id: 'review' | 'apply' | 'golive'; smart?: Smart }[]>(() => {
    const rows: { id: 'review' | 'apply' | 'golive'; smart?: Smart }[] = [];
    const review = this.reviewToo();
    const apply = this.applyToo();
    if (review) rows.push({ id: 'review', smart: review });
    if (apply) rows.push({ id: 'apply', smart: apply });
    if (this.goLiveOffer()) rows.push({ id: 'golive' });
    const keep = rows.slice(0, 2);
    // the guided card stays while it is open or just switched real applications on
    if (rows.length > 2 && (this.goLiveOpen() || this.justOn())) keep[1] = rows[rows.length - 1];
    return keep;
  });

  /** Where the jobs behind the secondary "Apply to N jobs" button come from. */
  protected readonly applyHint = computed(() => this.extras().find((r) => r.id === 'apply')?.smart?.message ?? '');

  /** What sits on top of the pile: the next item the main button leads to. */
  protected readonly top = computed<TopSheet | null>(() => {
    const kind = this.smart()?.kind;
    const place = (j: { company: string; location: string }) => [j.company, j.location].filter(Boolean).join(this.i18n.t('home.sheet.sep'));
    const a = this.firstAction();
    if (kind === 'finish' && a) {
      const sensitive = a.questions.find((q) => q.label)?.label ?? '';
      return { title: a.job.title, sub: place(a.job), label: this.i18n.t('actions.kind.' + a.kind), detail: sensitive, stamp: this.i18n.t('shell.nav.needsYou'), tone: 'stamp-stop', pile: this.openCount() };
    }
    const r = this.firstReview();
    if (kind === 'review' && r) {
      const label = r.score ? this.i18n.t('actions.score', { n: this.num(r.score), out: this.num(10) }) : '';
      return { title: r.title, sub: place(r), label, detail: r.ai?.reasons[0] ?? '', stamp: this.i18n.t('common.tier.mid'), tone: '', pile: this.shell.reviewCount() };
    }
    const q = this.firstReady();
    if (kind === 'apply' && q) {
      const label = q.score ? this.i18n.t('actions.score', { n: this.num(q.score), out: this.num(10) }) : '';
      return { title: q.title, sub: place(q), label, detail: q.ai?.reasons[0] ?? '', stamp: this.i18n.t('common.tier.' + (q.tier ?? 'high')), tone: q.tier === 'high' ? 'stamp-go' : '', pile: this.shell.status()?.ready_to_apply ?? 1 };
    }
    return null;
  });

  /** First-run checklist on the sheet, while setup is unfinished. */
  protected readonly setupRows = computed(() => {
    const s = this.shell.status();
    if (!s || s.setup.required_done) return [];
    return [
      { label: 'welcome.cv.title', done: s.setup.cv },
      { label: 'welcome.ai.title', done: s.setup.ai },
      { label: 'welcome.found.title', done: s.setup.profile },
      { label: 'welcome.jobs.title', done: s.setup.roles && s.setup.where },
    ];
  });
  protected readonly setupCount = computed(() => this.setupRows().filter((r) => r.done).length);

  protected readonly funnel = computed(() => {
    const s = this.shell.status();
    if (!s) return [];
    const tiers = this.report()?.tiers ?? {};
    const found = Object.values(s.states).reduce((a, b) => a + b, 0);
    // "passed filters" = ranked or later; the Jobs page knows it as the state group `passed`
    const passed = found - ['discovered', 'enriched', 'filtered_out'].reduce((a, k) => a + this.count(k), 0);
    return [
      { id: 'found', n: found, label: 'home.funnel.found', link: '/jobs', query: {} },
      { id: 'passed', n: passed, label: 'home.funnel.passed', link: '/jobs', query: { state: 'passed' } },
      { id: 'strong', n: tiers['high'] ?? 0, label: 'home.funnel.strong', link: '/jobs', query: { tier: 'high' } },
      { id: 'possible', n: tiers['mid'] ?? 0, label: 'home.funnel.possible', link: '/jobs', query: { tier: 'mid' } },
      // practice mode sends nothing, so "applied" would read 0: show how many forms were practised (the report below has them)
      s.apply_live
        ? { id: 'applied', n: this.count('applied'), label: 'home.funnel.applied', link: '', query: {} }
        : { id: 'applied', n: s.practiced, label: 'home.funnel.practiced', link: '', query: {} },
    ];
  });

  constructor() {
    effect(() => {
      this.live.changed(); // numbers move whenever a stage ends
      void this.loadNumbers();
    });
    effect(() => {
      const ready = this.shell.status()?.ready_to_apply ?? 0;
      this.live.changed(); // a stage ending can change who is ready
      untracked(() => void this.loadMix(ready));
    });
    effect(() => {
      const open = this.openCount();
      const review = this.shell.reviewCount();
      this.live.changed();
      untracked(() => void this.loadFront(open, review));
    });
  }

  protected num = (n: number): string => fmtNum(this.loc(), n);

  /** "Ready to apply for real?" next to the main button once a practice run filled a form (ux-plan 8.2); the card opens under it. */
  protected readonly goLiveOffer = computed(() => {
    const s = this.shell.status();
    return !!s && (this.justOn() || (!s.apply_live && (s.practiced > 0 || !!this.golive()?.eligible)));
  });

  /** How many of the jobs ready to apply to are strong matches; the rest were approved by the user. */
  private async loadMix(ready: number): Promise<void> {
    if (ready <= 0) {
      this.firstReady.set(null);
      return this.readyMix.set(null);
    }
    try {
      const lists = await Promise.all(['queued_apply', 'tailored'].map((state) => this.api.get<JobRow[]>(`/jobs?state=${state}`)));
      const rows = lists.flat();
      this.readyMix.set(rows.filter((j) => j.tier === 'high').length);
      this.firstReady.set(rows[0] ?? null);
    } catch {
      this.readyMix.set(null); // the plain "N jobs are ready" shows instead
    }
  }

  /** The items behind the top sheet; on failure the lead sentence simply stands alone. */
  private async loadFront(open: number, review: number): Promise<void> {
    try {
      const [actions, jobs] = await Promise.all([
        open > 0 ? this.api.get<ActionItem[]>('/actions?status=open') : Promise.resolve([]),
        review > 0 ? this.api.get<JobRow[]>('/jobs?state=awaiting_review') : Promise.resolve([]),
      ]);
      this.firstAction.set(actions[0] ?? null);
      this.firstReview.set(jobs[0] ?? null);
    } catch {
      this.firstAction.set(null);
      this.firstReview.set(null);
    }
  }

  /** Opening the guided card scrolls it into view: it can be taller than the screen. */
  protected toggleGoLive(): void {
    this.goLiveOpen.set(!this.goLiveOpen());
    if (this.goLiveOpen()) setTimeout(() => document.getElementById('home-golive')?.scrollIntoView({ block: 'start' }));
  }

  private async loadNumbers(): Promise<void> {
    try {
      const [report, golive] = await Promise.all([this.api.get<Report>('/report'), this.api.get<GoLive>('/golive')]);
      this.report.set(report);
      this.golive.set(golive);
    } catch {
      // the numbers stay as they were; the live socket triggers another load
    }
  }

  /** Start the apply stages (an unfinished run goes on) or a new search, which discards an unfinished one: its steps' play buttons resume it. */
  protected async go(sm: Smart): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    this.needsLibreOffice.set(false);
    try {
      await this.api.post('/runs', { stages: sm.stages, new: sm.kind === 'find' }); // its progress shows further down this page
    } catch (e) {
      if (e instanceof ApiError && e.code === 'needs_libreoffice') this.needsLibreOffice.set(true);
      else this.error.set(e instanceof ApiError && e.code === 'needs_tectonic' ? this.i18n.t('run.reason.needs_tectonic') : (e as Error).message);
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
}
