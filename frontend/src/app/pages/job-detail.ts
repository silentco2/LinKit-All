import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { Api } from '../api';
import { JobDetail } from '../types';

const APPROVABLE = ['awaiting_review', 'below_threshold'];
const FINAL = ['applied', 'skipped', 'filtered_out'];

@Component({
  selector: 'app-job-detail',
  imports: [DatePipe, DecimalPipe],
  template: `
    @if (error()) {
      <div class="alert alert-error">{{ error() }}</div>
    }
    @if (job(); as j) {
      <article class="space-y-5">
        <header>
          <h2 class="text-xl">{{ j.title }}</h2>
          <p class="text-sm text-slate-600 dark:text-slate-400">
            {{ j.company }} · {{ j.location || 'Location not stated' }}
            @if (j.remote) { · {{ j.remote }} }
          </p>
          <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
            @if (j.tier) { <span class="badge tier-{{ j.tier }}">{{ j.tier }} tier</span> }
            <span class="badge tier-low">{{ j.state.replace('_', ' ') }}</span>
            <span class="badge tier-low">{{ j.source }}</span>
            @if (j.rank !== null) { <span class="badge tier-low">match {{ j.rank * 100 | number: '1.0-0' }}%</span> }
            @if (j.posted_at) { <span class="text-slate-500">posted {{ j.posted_at | date: 'mediumDate' }}</span> }
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <a class="btn" [href]="j.url" target="_blank" rel="noopener noreferrer">Open posting ↗</a>
            @if (approvable(j.state)) {
              <button class="btn btn-primary" (click)="act('approve')" [disabled]="busy()">Approve for applying</button>
            }
            @if (!final(j.state)) {
              <button class="btn btn-danger" (click)="act('reject')" [disabled]="busy()">Skip this job</button>
            }
          </div>
        </header>

        @if (j.ai; as ai) {
          <section class="rounded-lg bg-slate-50 p-4 dark:bg-slate-950">
            <h3 class="font-semibold">AI score: {{ ai.score }}/10</h3>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm">
              @for (r of ai.reasons; track r) { <li>{{ r }}</li> }
            </ul>
            @if (ai.missing_skills.length) {
              <p class="mt-3 text-sm"><span class="font-medium">Missing skills:</span> {{ ai.missing_skills.join(', ') }}</p>
            }
            @if (ai.red_flags.length) {
              <p class="mt-1 text-sm text-rose-700 dark:text-rose-300"><span class="font-medium">Red flags:</span> {{ ai.red_flags.join(', ') }}</p>
            }
          </section>
        }

        @if (j.salary.max || j.salary.min) {
          <p class="text-sm">
            <span class="font-medium">Salary:</span>
            {{ j.salary.min | number: '1.0-0' }}@if (j.salary.max && j.salary.max !== j.salary.min) {–{{ j.salary.max | number: '1.0-0' }}}
            {{ j.salary.currency }} @if (j.salary.interval) { / {{ j.salary.interval }} }
          </p>
        }

        <section>
          <h3 class="font-semibold">Description</h3>
          <div class="mt-2 max-h-[50vh] overflow-auto text-sm leading-relaxed whitespace-pre-wrap" dir="auto">{{ j.description || 'No description yet.' }}</div>
        </section>

        <section>
          <h3 class="font-semibold">History</h3>
          <ol class="mt-2 space-y-1 border-l border-slate-200 pl-4 text-xs dark:border-slate-700">
            @for (e of j.events; track $index) {
              <li><span class="text-slate-500">{{ e.at | date: 'short' }}</span> → <span class="font-medium">{{ e.to.replace('_', ' ') }}</span> {{ e.message }}</li>
            }
          </ol>
        </section>
      </article>
    }
  `,
})
export class JobDetailPanel {
  private readonly api = inject(Api);
  readonly jobId = input.required<number>();
  readonly changed = output<void>();
  protected readonly job = signal<JobDetail | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  constructor() {
    effect(() => {
      const id = this.jobId();
      this.load(id);
    });
  }

  approvable(state: string): boolean {
    return APPROVABLE.includes(state);
  }

  final(state: string): boolean {
    return FINAL.includes(state);
  }

  async load(id: number): Promise<void> {
    this.error.set('');
    try {
      this.job.set(await this.api.get<JobDetail>(`/jobs/${id}`));
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  async act(action: 'approve' | 'reject'): Promise<void> {
    this.busy.set(true);
    try {
      const r = await this.api.post<{ done: number; errors: Record<string, string> }>('/jobs/actions', { ids: [this.jobId()], action });
      if (!r.done) this.error.set(Object.values(r.errors)[0] ?? 'Not possible in this state');
      await this.load(this.jobId());
      this.changed.emit();
    } finally {
      this.busy.set(false);
    }
  }
}
