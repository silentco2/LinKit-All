import { Component, effect, inject, signal } from '@angular/core';
import { Api } from '../api';
import { Live } from '../live';
import { JobRow } from '../types';
import { JobDetailPanel } from './job-detail';

type Tab = 'awaiting_review' | 'below_threshold';

@Component({
  selector: 'app-review',
  host: { '(document:keydown.escape)': 'open.set(null)' },
  imports: [JobDetailPanel],
  template: `
    <h1>Review queue</h1>
    <p class="mt-1 text-sm text-slate-500">Mid-score jobs wait here for you. Approved jobs join the apply queue. High scores skip this step.</p>

    <div class="mt-5 flex gap-2" role="tablist">
      @for (t of tabs; track t.id) {
        <button type="button" role="tab" class="btn" [class.btn-primary]="tab() === t.id" [attr.aria-selected]="tab() === t.id"
                (click)="tab.set(t.id); load()">{{ t.label }}</button>
      }
    </div>

    @if (message()) { <div class="alert alert-ok mt-4" role="status">{{ message() }}</div> }

    @if (jobs().length) {
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" [checked]="picked().size === jobs().length" (change)="toggleAll()"> Select all ({{ jobs().length }})
        </label>
        <button class="btn btn-primary" [disabled]="!picked().size || busy()" (click)="act('approve')">Approve {{ picked().size || '' }}</button>
        <button class="btn btn-danger" [disabled]="!picked().size || busy()" (click)="act('reject')">Skip {{ picked().size || '' }}</button>
      </div>
    }

    <div class="mt-4 max-w-4xl">
      <ul class="space-y-3">
        @for (j of jobs(); track j.id) {
          <li class="card flex gap-4 p-4" [class.ring-2]="open() === j.id" [class.ring-brand-500]="open() === j.id">
            <input type="checkbox" class="mt-1.5" [checked]="picked().has(j.id)" (change)="toggle(j.id)"
                   [attr.aria-label]="'Select ' + j.title">
            <div class="min-w-0 flex-1">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="truncate font-medium" dir="auto">{{ j.title }}</div>
                  <div class="truncate text-sm text-slate-500" dir="auto">{{ j.company }} · {{ j.location }}</div>
                </div>
                @if (j.score) { <span class="badge tier-{{ j.tier }} shrink-0">{{ j.score }}/10</span> }
              </div>
              @if (j.ai; as ai) {
                <ul class="mt-2 list-disc pl-5 text-sm text-slate-700 dark:text-slate-300">
                  @for (r of ai.reasons.slice(0, 2); track r) { <li>{{ r }}</li> }
                </ul>
                @if (ai.missing_skills.length) { <p class="mt-1 text-xs text-slate-500">Missing: {{ ai.missing_skills.join(', ') }}</p> }
                @if (ai.red_flags.length) { <p class="mt-1 text-xs text-rose-600 dark:text-rose-400">Red flags: {{ ai.red_flags.join(', ') }}</p> }
              }
              <button type="button" class="mt-2 text-sm text-brand-600 hover:underline" (click)="open.set(j.id)">Details</button>
            </div>
          </li>
        } @empty {
          <li class="card text-center text-sm text-slate-500">
            {{ tab() === 'awaiting_review' ? 'Nothing waiting for review.' : 'No low-tier jobs.' }}
          </li>
        }
      </ul>
      @if (open(); as id) {
        <aside class="fixed inset-y-0 right-0 z-20 w-full max-w-xl overflow-auto border-l border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900" aria-label="Job details">
          <button type="button" class="btn float-right ml-3 px-2 py-1" aria-label="Close details" (click)="open.set(null)">✕</button>
          <app-job-detail [jobId]="id" (changed)="load()" />
        </aside>
      }
    </div>
  `,
})
export class ReviewPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  protected readonly tabs: { id: Tab; label: string }[] = [
    { id: 'awaiting_review', label: 'Needs review' },
    { id: 'below_threshold', label: 'Low scores (hidden)' },
  ];
  protected readonly tab = signal<Tab>('awaiting_review');
  protected readonly jobs = signal<JobRow[]>([]);
  protected readonly picked = signal(new Set<number>());
  protected readonly open = signal<number | null>(null);
  protected readonly busy = signal(false);
  protected readonly message = signal('');

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
  }

  async load(): Promise<void> {
    this.picked.set(new Set());
    this.jobs.set(await this.api.get<JobRow[]>(`/jobs?state=${this.tab()}`));
  }

  toggle(id: number): void {
    this.picked.update((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  toggleAll(): void {
    const all = this.picked().size === this.jobs().length;
    this.picked.set(new Set(all ? [] : this.jobs().map((j) => j.id)));
  }

  async act(action: 'approve' | 'reject'): Promise<void> {
    this.busy.set(true);
    try {
      const r = await this.api.post<{ done: number }>('/jobs/actions', { ids: [...this.picked()], action });
      this.message.set(`${r.done} job${r.done === 1 ? '' : 's'} ${action === 'approve' ? 'approved for applying' : 'skipped'}.`);
      this.open.set(null);
      await this.load();
    } finally {
      this.busy.set(false);
    }
  }
}
