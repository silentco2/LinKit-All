import { ScrollingModule } from '@angular/cdk/scrolling';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, localeOf } from '../locale';
import { JobRow } from '../types';
import { JobDetailPanel } from './job-detail';

const STATES = ['discovered', 'enriched', 'filtered_out', 'ranked', 'scored', 'below_threshold', 'awaiting_review',
  'queued_apply', 'tailored', 'applying', 'needs_user', 'applied', 'failed', 'skipped'];

@Component({
  selector: 'app-jobs',
  host: { '(document:keydown.escape)': 'selected.set(null)' },
  imports: [ScrollingModule, FormsModule, RouterLink, JobDetailPanel, TPipe],
  template: `
    <div class="flex items-baseline justify-between">
      <h1>{{ 'jobs.title' | t }}</h1>
      <span class="text-sm text-slate-500">{{ 'jobs.shown' | t: { n: num(rows().length) } }}</span>
    </div>

    <div class="mt-4 flex flex-wrap gap-3" role="search">
      <input class="input max-w-xs" type="search" [placeholder]="'jobs.searchPh' | t" [attr.aria-label]="'jobs.searchLabel' | t"
             [ngModel]="q()" (ngModelChange)="search($event)">
      <select class="input w-44" [attr.aria-label]="'jobs.filter.state' | t" [ngModel]="state()" (ngModelChange)="state.set($event); load()">
        <option value="">{{ 'jobs.filter.allStates' | t }}</option>
        @for (s of states; track s) { <option [value]="s">{{ 'common.state.' + s | t }}</option> }
      </select>
      <select class="input w-36" [attr.aria-label]="'jobs.filter.tier' | t" [ngModel]="tier()" (ngModelChange)="tier.set($event); load()">
        <option value="">{{ 'jobs.filter.allTiers' | t }}</option>
        <option value="high">{{ 'common.tier.high' | t }}</option>
        <option value="mid">{{ 'common.tier.mid' | t }}</option>
        <option value="low">{{ 'common.tier.low' | t }}</option>
      </select>
      <select class="input w-40" [attr.aria-label]="'jobs.filter.source' | t" [ngModel]="source()" (ngModelChange)="source.set($event); load()">
        <option value="">{{ 'jobs.filter.allSources' | t }}</option>
        @for (s of sources(); track s) { <option [value]="s">{{ s }}</option> }
      </select>
    </div>

    @if (error()) { <div class="alert alert-error mt-4" dir="auto">{{ error() }}</div> }

    <div class="mt-4">
      <div class="card p-0">
        <div class="grid grid-cols-[3rem_minmax(0,1fr)_7rem_5rem] gap-3 border-b border-slate-200 px-4 py-2 text-xs font-medium tracking-wide text-slate-500 uppercase rtl:tracking-normal dark:border-slate-800">
          <span>{{ 'jobs.col.score' | t }}</span><span>{{ 'jobs.col.job' | t }}</span><span>{{ 'jobs.col.state' | t }}</span><span class="text-end">{{ 'jobs.col.match' | t }}</span>
        </div>
        @if (rows().length) {
          <cdk-virtual-scroll-viewport itemSize="60" class="h-[calc(100vh-260px)]">
            <button *cdkVirtualFor="let j of rows(); trackBy: trackId" type="button" (click)="selected.set(j.id)"
                    class="grid h-[60px] w-full grid-cols-[3rem_minmax(0,1fr)_7rem_5rem] items-center gap-3 border-b border-slate-100 px-4 text-start hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                    [class.bg-brand-50]="selected() === j.id" [attr.aria-pressed]="selected() === j.id">
              <span>
                @if (j.score) { <span class="badge tier-{{ j.tier }}">{{ num(j.score) }}</span> } @else { <span class="text-slate-400">–</span> }
              </span>
              <span class="min-w-0">
                <span class="block truncate text-sm font-medium" dir="auto">{{ j.title }}</span>
                <span class="block truncate text-xs text-slate-500" dir="auto"><bdi>{{ j.company }}</bdi> · <bdi>{{ j.location }}</bdi> · <bdi>{{ j.source }}</bdi></span>
              </span>
              <span class="truncate text-xs text-slate-600 dark:text-slate-400">{{ 'common.state.' + j.state | t }}</span>
              <span class="text-end text-xs text-slate-500">{{ j.rank === null ? '' : num(j.rank, { style: 'percent', maximumFractionDigits: 0 }) }}</span>
            </button>
          </cdk-virtual-scroll-viewport>
        } @else if (!loading()) {
          <p class="p-8 text-center text-sm text-slate-500">{{ 'jobs.empty.a' | t }}<a routerLink="/live">{{ 'shell.nav.live' | t }}</a>{{ 'jobs.empty.b' | t }}</p>
        }
      </div>

      @if (selected(); as id) {
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
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly states = STATES;
  protected readonly rows = signal<JobRow[]>([]);
  protected readonly q = signal('');
  protected readonly state = signal('');
  protected readonly tier = signal('');
  protected readonly source = signal('');
  protected readonly selected = signal<number | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly sources = signal<string[]>([]);
  private timer?: ReturnType<typeof setTimeout>;

  constructor() {
    effect(() => {
      this.live.changed(); // new jobs or new scores after each stage
      this.load();
    });
    this.api.get<{ sources: Record<string, unknown> }>('/report').then((r) => this.sources.set(Object.keys(r.sources).sort()));
  }

  trackId = (_: number, j: JobRow) => j.id;
  protected num = (n: number | null, o?: Intl.NumberFormatOptions): string => fmtNum(this.loc(), n, o);

  search(value: string): void {
    this.q.set(value);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(), 250);
  }

  async load(): Promise<void> {
    const params = new URLSearchParams();
    for (const [k, v] of [['q', this.q()], ['state', this.state()], ['tier', this.tier()], ['source', this.source()]]) {
      if (v) params.set(k, v);
    }
    this.loading.set(true);
    try {
      this.rows.set(await this.api.get<JobRow[]>(`/jobs?${params}`));
      this.error.set('');
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.loading.set(false);
    }
  }
}
