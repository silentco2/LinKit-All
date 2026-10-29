import { ScrollingModule } from '@angular/cdk/scrolling';
import { Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, SourcePipe, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, localeOf } from '../locale';
import { Hint } from '../components/hint';
import { GHOST_HIGH, GHOST_MEDIUM, JobRow, reasonText, SCAM_HIGH, SCAM_MEDIUM } from '../types';

interface Risk { key: string; cls: string }
const RISK_RED = 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300';
const RISK_AMBER = 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300';
const RISK_GREY = 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300';

/** The one trust badge a row shows: scam outranks ghost, high outranks medium. */
function riskOf(j: JobRow): Risk | null {
  const scam = j.scam_score ?? 0;
  const ghost = j.ghost_score ?? 0;
  if (scam >= SCAM_HIGH) return { key: 'scam.high', cls: RISK_RED };
  if (scam >= SCAM_MEDIUM) return { key: 'scam.medium', cls: RISK_AMBER };
  if (ghost >= GHOST_HIGH) return { key: 'ghost.high', cls: RISK_AMBER };
  if (ghost >= GHOST_MEDIUM) return { key: 'ghost.medium', cls: RISK_GREY };
  return null;
}
import { JobDetailPanel } from './job-detail';

/** A pseudo-state in the URL for several states at once (the server filters one state at a time). */
const GROUPS: Record<string, Set<string>> = {
  // ranked or later: what Home calls "passed filters"
  passed: new Set(['ranked', 'scored', 'below_threshold', 'awaiting_review', 'queued_apply', 'tailored', 'applying', 'needs_user', 'applied', 'failed', 'skipped']),
};
const STATES = ['discovered', 'enriched', 'filtered_out', 'ranked', 'scored', 'below_threshold', 'awaiting_review',
  'queued_apply', 'tailored', 'applying', 'needs_user', 'applied', 'failed', 'skipped'];

@Component({
  selector: 'app-jobs',
  host: { '(document:keydown.escape)': 'selected.set(null)' },
  imports: [ScrollingModule, FormsModule, Hint, RouterLink, JobDetailPanel, SourcePipe, TPipe],
  template: `
    <div class="flex items-baseline justify-between">
      <h1>{{ 'jobs.title' | t }}</h1>
      <span class="text-sm text-slate-500">{{ 'jobs.shown' | t: { n: num(rows().length) } }}</span>
    </div>

    <app-hint id="jobs">{{ 'hint.jobs' | t }}</app-hint>

    <div class="mt-4 flex flex-wrap gap-3" role="search">
      <input class="input max-w-xs" type="search" [placeholder]="'jobs.searchPh' | t" [attr.aria-label]="'jobs.searchLabel' | t"
             [ngModel]="qText()" (ngModelChange)="search($event)">
      <select class="input w-44" [attr.aria-label]="'jobs.filter.state' | t" [ngModel]="state()" (ngModelChange)="setFilter('state', $event)">
        <option value="">{{ 'jobs.filter.allStates' | t }}</option>
        <option value="passed">{{ 'jobs.filter.passed' | t }}</option>
        @for (s of states; track s) { <option [value]="s">{{ 'common.state.' + s | t }}</option> }
      </select>
      <select class="input w-36" [attr.aria-label]="'jobs.filter.tier' | t" [ngModel]="tier()" (ngModelChange)="setFilter('tier', $event)">
        <option value="">{{ 'jobs.filter.allTiers' | t }}</option>
        <option value="high">{{ 'common.tier.high' | t }}</option>
        <option value="mid">{{ 'common.tier.mid' | t }}</option>
        <option value="low">{{ 'common.tier.low' | t }}</option>
      </select>
      <select class="input w-40" [attr.aria-label]="'jobs.filter.source' | t" [ngModel]="source()" (ngModelChange)="setFilter('source', $event)">
        <option value="">{{ 'jobs.filter.allSources' | t }}</option>
        @for (s of sources(); track s) { <option [value]="s">{{ s | src }}</option> }
      </select>
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" [ngModel]="hideRisky()" (ngModelChange)="hideRisky.set($event)">{{ 'jobs.filter.hideRisky' | t }}</label>
    </div>

    @if (error()) { <div class="alert alert-error mt-4" dir="auto">{{ error() }}</div> }

    <div class="mt-4" [class]="selected() !== null ? 'xl:pe-[36rem]' : ''">
      <div class="card p-0">
        <div [class]="compact() ? 'grid-cols-[2.5rem_minmax(0,1fr)]' : 'grid-cols-[3rem_minmax(0,1fr)_7rem_5rem]'" class="grid gap-3 border-b border-slate-200 px-4 py-2 text-xs font-medium tracking-wide text-slate-500 uppercase rtl:tracking-normal dark:border-slate-800">
          <span>{{ 'jobs.col.score' | t }}</span><span>{{ 'jobs.col.job' | t }}</span>@if (!compact()) { <span>{{ 'jobs.col.state' | t }}</span><span class="text-end">{{ 'jobs.col.match' | t }}</span> }
        </div>
        @if (rows().length) {
          <cdk-virtual-scroll-viewport [itemSize]="rowHeight()" class="h-[calc(100vh-260px)]">
            <button *cdkVirtualFor="let j of rows(); trackBy: trackId" type="button" (click)="selected.set(j.id)"
                    [style.height.px]="rowHeight()"
                    [class]="compact() ? 'grid-cols-[2.5rem_minmax(0,1fr)]' : 'grid-cols-[3rem_minmax(0,1fr)_7rem_5rem]'"
                    class="grid w-full items-center gap-3 border-b border-slate-100 px-4 text-start hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                    [class.bg-brand-50]="selected() === j.id" [attr.aria-pressed]="selected() === j.id">
              <span>
                @if (j.score) { <span class="badge tier-{{ j.tier }}">{{ num(j.score) }}</span> } @else { <span class="text-slate-400">–</span> }
              </span>
              <span class="min-w-0">
                <span [class]="compact() ? 'line-clamp-2' : 'block truncate'" class="text-sm font-medium break-words" dir="auto">{{ j.title }}</span>
                <span class="block truncate text-xs text-slate-500" dir="auto">@if (reasonOf(j); as why) { <span class="badge tier-low me-1.5 inline-block max-w-[55%] truncate px-1.5 py-0 align-middle text-[11px] leading-4" [attr.title]="why" dir="auto">{{ why }}</span> }@if (risk(j); as r) { <span class="badge me-1.5 px-1.5 py-0 text-[11px] leading-4 {{ r.cls }}">{{ 'trust.badge.' + r.key | t }}</span> }@if (compact()) { <span>{{ 'common.state.' + j.state | t }} · </span> }<bdi>{{ j.company }}</bdi> · <bdi>{{ j.location }}</bdi> · <bdi>{{ j.source | src }}</bdi></span>
              </span>
              @if (!compact()) {
                <span class="truncate text-xs text-slate-600 dark:text-slate-400">{{ 'common.state.' + j.state | t }}</span>
                <span class="text-end text-xs text-slate-500">{{ j.rank === null ? '' : num(j.rank, { style: 'percent', maximumFractionDigits: 0 }) }}</span>
              }
            </button>
          </cdk-virtual-scroll-viewport>
        } @else if (!loading()) {
          <p class="p-8 text-center text-sm text-slate-500">{{ 'jobs.empty.a' | t }}<a routerLink="/home">{{ 'shell.nav.home' | t }}</a>{{ 'jobs.empty.b' | t }}</p>
        }
      </div>

      @if (selected(); as id) {
        <button type="button" tabindex="-1" aria-hidden="true" class="fixed inset-0 z-10 cursor-default bg-slate-900/30 xl:hidden" (click)="selected.set(null)"></button>
        <aside class="fixed inset-y-0 end-0 z-20 w-full max-w-xl overflow-auto border-s border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900" [attr.aria-label]="'common.drawer.label' | t">
          <button type="button" class="btn float-end ms-3 px-2 py-1" [attr.aria-label]="'common.drawer.close' | t" (click)="selected.set(null)">✕</button>
          <app-job-detail [jobId]="id" (changed)="load()" />
        </aside>
      }
    </div>
  `,
})
export class JobsPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  private readonly i18n = inject(I18n);
  private readonly router = inject(Router);
  /** The filters live in the URL (`?state=&tier=&source=&q=`), so Home's numbers and a reload both land on the same list. */
  private readonly params = toSignal(inject(ActivatedRoute).queryParamMap);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly states = STATES;
  private readonly all = signal<JobRow[]>([]);
  protected readonly hideRisky = signal(false);
  /** "Hide likely ghost/scam" drops the high bands only (a medium band is a hint, not a verdict). */
  protected readonly rows = computed(() =>
    this.hideRisky() ? this.all().filter((j) => (j.scam_score ?? 0) < SCAM_HIGH && (j.ghost_score ?? 0) < GHOST_HIGH) : this.all());
  protected readonly risk = riskOf;
  protected readonly reasonOf = (j: JobRow): string => reasonText(this.i18n, j);
  protected readonly q = computed(() => this.params()?.get('q') ?? '');
  protected readonly state = computed(() => this.params()?.get('state') ?? '');
  protected readonly tier = computed(() => this.params()?.get('tier') ?? '');
  protected readonly source = computed(() => this.params()?.get('source') ?? '');
  /** What the search box shows: ahead of `q` while the user types. */
  protected readonly qText = signal('');
  protected readonly selected = signal<number | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly sources = signal<string[]>([]);
  /** Phones, and the list narrowed beside the open drawer (xl+), show title + score only on two-line rows. */
  private readonly wide = signal(true);
  private readonly xl = signal(true);
  protected readonly compact = computed(() => !this.wide() || (this.xl() && this.selected() !== null));
  protected readonly rowHeight = computed(() => (this.compact() ? 76 : 60));
  private timer?: ReturnType<typeof setTimeout>;

  constructor() {
    if (typeof matchMedia === 'function') {
      for (const [query, sig] of [['(min-width: 640px)', this.wide], ['(min-width: 1280px)', this.xl]] as const) {
        const mq = matchMedia(query);
        sig.set(mq.matches);
        const onChange = (e: MediaQueryListEvent) => sig.set(e.matches);
        mq.addEventListener('change', onChange);
        inject(DestroyRef).onDestroy(() => mq.removeEventListener('change', onChange));
      }
    }
    effect(() => {
      this.live.changed(); // new jobs or new scores after each stage
      this.load(); // also runs when a filter in the URL changes
    });
    effect(() => {
      const q = this.q(); // a link or a back step changed the URL: follow it, unless the user is mid-word
      if (this.timer === undefined) this.qText.set(q);
    });
    this.api.get<{ sources: Record<string, unknown> }>('/report').then((r) => this.sources.set(Object.keys(r.sources).sort()));
  }

  trackId = (_: number, j: JobRow) => j.id;
  protected num = (n: number | null, o?: Intl.NumberFormatOptions): string => fmtNum(this.loc(), n, o);

  search(value: string): void {
    this.qText.set(value);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = undefined;
      this.setFilter('q', value);
    }, 250);
  }

  protected setFilter(key: 'q' | 'state' | 'tier' | 'source', value: string): void {
    void this.router.navigate([], { queryParams: { [key]: value || null }, queryParamsHandling: 'merge', replaceUrl: true });
  }

  async load(): Promise<void> {
    const params = new URLSearchParams();
    const group = GROUPS[this.state()];
    for (const [k, v] of [['q', this.q()], ['state', group ? '' : this.state()], ['tier', this.tier()], ['source', this.source()]]) {
      if (v) params.set(k, v);
    }
    this.loading.set(true);
    try {
      const rows = await this.api.get<JobRow[]>(`/jobs?${params}`);
      this.all.set(group ? rows.filter((j) => group.has(j.state)) : rows);
      this.error.set('');
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.loading.set(false);
    }
  }
}
