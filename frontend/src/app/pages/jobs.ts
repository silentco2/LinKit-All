import { ScrollingModule } from '@angular/cdk/scrolling';
import { DecimalPipe } from '@angular/common';
import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { Live } from '../live';
import { JobRow } from '../types';
import { JobDetailPanel } from './job-detail';

const STATES = ['discovered', 'enriched', 'filtered_out', 'ranked', 'scored', 'below_threshold', 'awaiting_review',
  'queued_apply', 'tailored', 'applying', 'needs_user', 'applied', 'failed', 'skipped'];

@Component({
  selector: 'app-jobs',
  host: { '(document:keydown.escape)': 'selected.set(null)' },
  imports: [ScrollingModule, FormsModule, DecimalPipe, RouterLink, JobDetailPanel],
  template: `
    <div class="flex items-baseline justify-between">
      <h1>Jobs</h1>
      <span class="text-sm text-slate-500">{{ rows().length | number }} shown</span>
    </div>

    <div class="mt-4 flex flex-wrap gap-3" role="search">
      <input class="input max-w-xs" type="search" placeholder="Search title, company, location" aria-label="Search jobs"
             [ngModel]="q()" (ngModelChange)="search($event)">
      <select class="input w-44" aria-label="State" [ngModel]="state()" (ngModelChange)="state.set($event); load()">
        <option value="">All states</option>
        @for (s of states; track s) { <option [value]="s">{{ s.replace('_', ' ') }}</option> }
      </select>
      <select class="input w-36" aria-label="Tier" [ngModel]="tier()" (ngModelChange)="tier.set($event); load()">
        <option value="">All tiers</option><option value="high">High</option><option value="mid">Mid</option><option value="low">Low</option>
      </select>
      <select class="input w-40" aria-label="Source" [ngModel]="source()" (ngModelChange)="source.set($event); load()">
        <option value="">All sources</option>
        @for (s of sources(); track s) { <option [value]="s">{{ s }}</option> }
      </select>
    </div>

    @if (error()) { <div class="alert alert-error mt-4">{{ error() }}</div> }

    <div class="mt-4">
      <div class="card p-0">
        <div class="grid grid-cols-[3rem_minmax(0,1fr)_7rem_5rem] gap-3 border-b border-slate-200 px-4 py-2 text-xs font-medium tracking-wide text-slate-500 uppercase dark:border-slate-800">
          <span>Score</span><span>Job</span><span>State</span><span class="text-right">Match</span>
        </div>
        @if (rows().length) {
          <cdk-virtual-scroll-viewport itemSize="60" class="h-[calc(100vh-260px)]">
            <button *cdkVirtualFor="let j of rows(); trackBy: trackId" type="button" (click)="selected.set(j.id)"
                    class="grid h-[60px] w-full grid-cols-[3rem_minmax(0,1fr)_7rem_5rem] items-center gap-3 border-b border-slate-100 px-4 text-left hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                    [class.bg-brand-50]="selected() === j.id" [attr.aria-pressed]="selected() === j.id">
              <span>
                @if (j.score) { <span class="badge tier-{{ j.tier }}">{{ j.score }}</span> } @else { <span class="text-slate-400">–</span> }
              </span>
              <span class="min-w-0">
                <span class="block truncate text-sm font-medium" dir="auto">{{ j.title }}</span>
                <span class="block truncate text-xs text-slate-500" dir="auto">{{ j.company }} · {{ j.location }} · {{ j.source }}</span>
              </span>
              <span class="truncate text-xs text-slate-600 dark:text-slate-400">{{ j.state.replace('_', ' ') }}</span>
              <span class="text-right text-xs text-slate-500">{{ j.rank === null ? '' : (j.rank * 100 | number: '1.0-0') + '%' }}</span>
            </button>
          </cdk-virtual-scroll-viewport>
        } @else if (!loading()) {
          <p class="p-8 text-center text-sm text-slate-500">No jobs match. Start a run from <a routerLink="/live">Live run</a>, or clear the filters.</p>
        }
      </div>

      @if (selected(); as id) {
        <aside class="fixed inset-y-0 right-0 z-20 w-full max-w-xl overflow-auto border-l border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900" aria-label="Job details">
          <button type="button" class="btn float-right ml-3 px-2 py-1" aria-label="Close details" (click)="selected.set(null)">✕</button>
          <app-job-detail [jobId]="id" (changed)="load()" />
        </aside>
      }
    </div>
  `,
})
export class JobsPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
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
