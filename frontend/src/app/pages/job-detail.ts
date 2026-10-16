import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { fmtNum, labelOr, localeOf } from '../locale';
import { JobDetail } from '../types';

interface Filled { value: unknown; source: string }
type Detail = Omit<JobDetail, 'events'> & {
  filled?: Record<string, Filled> | null;
  events: { id: number; at: string; to: string; message: string; screenshots: number }[];
};

const APPROVABLE = ['awaiting_review', 'below_threshold'];
const FINAL = ['applied', 'skipped', 'filtered_out'];

@Component({
  selector: 'app-job-detail',
  imports: [DatePipe, TPipe],
  template: `
    @if (error()) {
      <div class="alert alert-error" dir="auto">{{ error() }}</div>
    }
    @if (job(); as j) {
      <article class="space-y-5">
        <header>
          <h2 class="text-xl" dir="auto">{{ j.title }}</h2>
          <p class="text-sm text-slate-600 dark:text-slate-400">
            <bdi>{{ j.company }}</bdi> · @if (j.location) { <bdi>{{ j.location }}</bdi> } @else { {{ 'detail.noLocation' | t }} }
            @if (j.remote) { · <bdi>{{ j.remote }}</bdi> }
          </p>
          <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
            @if (j.tier) { <span class="badge tier-{{ j.tier }}">{{ 'detail.tier.' + j.tier | t }}</span> }
            <span class="badge tier-low">{{ 'common.state.' + j.state | t }}</span>
            <span class="badge tier-low"><bdi>{{ j.source }}</bdi></span>
            @if (j.rank !== null) { <span class="badge tier-low">{{ 'detail.match' | t: { pct: num(j.rank, { style: 'percent', maximumFractionDigits: 0 }) } }}</span> }
            @if (j.posted_at) { <span class="text-slate-500">{{ 'detail.posted' | t }} {{ j.posted_at | date: 'mediumDate' : undefined : loc() }}</span> }
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <a class="btn" [href]="j.url" target="_blank" rel="noopener noreferrer">{{ 'detail.open' | t }}</a>
            @if (approvable(j.state)) {
              <button class="btn btn-primary" (click)="act('approve')" [disabled]="busy()">{{ 'detail.approve' | t }}</button>
            }
            @if (!final(j.state)) {
              <button class="btn btn-danger" (click)="act('reject')" [disabled]="busy()">{{ 'detail.skip' | t }}</button>
            }
          </div>
        </header>

        @if (j.ai; as ai) {
          <section class="rounded-lg bg-slate-50 p-4 dark:bg-slate-950">
            <h3 class="font-semibold">{{ 'detail.ai.score' | t: { score: num(ai.score) } }}</h3>
            <ul class="mt-2 list-disc space-y-1 ps-5 text-sm">
              @for (r of ai.reasons; track r) { <li dir="auto">{{ r }}</li> }
            </ul>
            @if (ai.missing_skills.length) {
              <p class="mt-3 text-sm"><span class="font-medium">{{ 'detail.ai.missing' | t }}</span> <bdi>{{ ai.missing_skills.join(', ') }}</bdi></p>
            }
            @if (ai.red_flags.length) {
              <p class="mt-1 text-sm text-rose-700 dark:text-rose-300"><span class="font-medium">{{ 'detail.ai.redFlags' | t }}</span> <bdi>{{ ai.red_flags.join(', ') }}</bdi></p>
            }
          </section>
        }

        @if (j.salary.max || j.salary.min) {
          <p class="text-sm">
            <span class="font-medium">{{ 'detail.salary' | t }}</span>
            <bdi>{{ num(j.salary.min) }}@if (j.salary.max && j.salary.max !== j.salary.min) {–{{ num(j.salary.max) }}}
            {{ j.salary.currency }} @if (j.salary.interval) { / {{ j.salary.interval }} }</bdi>
          </p>
        }

        <section>
          <h3 class="font-semibold">{{ 'detail.description' | t }}</h3>
          <div class="mt-2 max-h-[50vh] overflow-auto text-sm leading-relaxed whitespace-pre-wrap" dir="auto">{{ j.description || ('detail.noDescription' | t) }}</div>
        </section>

        @if (filledRows(j); as rows) {
          <section>
            <h3 class="font-semibold">{{ 'detail.filled.title' | t }}</h3>
            <div class="overflow-x-auto">
              <table class="mt-2 w-full text-start text-sm">
                <thead class="text-xs text-slate-500"><tr><th class="py-1 pe-3 text-start">{{ 'detail.filled.question' | t }}</th><th class="py-1 pe-3 text-start">{{ 'detail.filled.value' | t }}</th><th class="py-1 text-start">{{ 'detail.filled.source' | t }}</th></tr></thead>
                <tbody>
                  @for (r of rows; track r.label) {
                    <tr class="border-t border-slate-200 align-top dark:border-slate-700">
                      <td class="py-1 pe-3" dir="auto">{{ r.label }}</td>
                      <td class="py-1 pe-3 break-words" dir="auto">{{ r.value }}</td>
                      <td class="py-1"><span class="badge" [class]="r.source === 'sensitive' ? 'tier-mid' : 'tier-low'">{{ sourceLabel(r.source) }}</span></td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </section>
        }

        <section>
          <h3 class="font-semibold">{{ 'detail.history' | t }}</h3>
          <ol class="mt-2 space-y-1 border-s border-slate-200 ps-4 text-xs dark:border-slate-700">
            @for (e of j.events; track $index) {
              <li><span class="text-slate-500">{{ e.at | date: 'short' : undefined : loc() }}</span> <span class="inline-block rtl:rotate-180">→</span> <span class="font-medium">{{ 'common.state.' + e.to | t }}</span> <span dir="auto">{{ e.message }}</span>
                @if (e.screenshots) {
                  <span class="ms-1">
                    @for (n of range(e.screenshots); track n) {
                      <a class="me-1 underline" [href]="shot(e.id, n)" target="_blank" rel="noopener noreferrer"><img class="inline-block h-12 rounded border border-slate-200 align-middle dark:border-slate-700" [src]="shot(e.id, n)" [alt]="'detail.screenshot' | t: { n: n + 1 }" loading="lazy"></a>
                    }
                  </span>
                }
              </li>
            }
          </ol>
        </section>
      </article>
    }
  `,
})
export class JobDetailPanel {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  readonly jobId = input.required<number>();
  readonly changed = output<void>();
  protected readonly job = signal<Detail | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  constructor() {
    effect(() => {
      const id = this.jobId();
      this.load(id);
    });
  }

  protected num = (n: number | null, o?: Intl.NumberFormatOptions): string => fmtNum(this.loc(), n, o);
  protected sourceLabel = (s: string): string => labelOr(this.i18n, 'common.answerSource.', s || 'unknown');

  approvable(state: string): boolean {
    return APPROVABLE.includes(state);
  }

  filledRows(j: Detail): { label: string; value: string; source: string }[] | null {
    if (!j.filled) return null;
    return Object.entries(j.filled).map(([label, f]) => ({
      label,
      value: Array.isArray(f.value) ? f.value.join(', ') : String(f.value ?? ''),
      source: f.source,
    }));
  }

  range(n: number): number[] {
    return Array.from({ length: n }, (_, i) => i);
  }

  shot(eventId: number, n: number): string {
    return `/api/jobs/${this.jobId()}/events/${eventId}/screenshot/${n}`;
  }

  final(state: string): boolean {
    return FINAL.includes(state);
  }

  async load(id: number): Promise<void> {
    this.error.set('');
    try {
      this.job.set(await this.api.get<Detail>(`/jobs/${id}`));
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  async act(action: 'approve' | 'reject'): Promise<void> {
    this.busy.set(true);
    try {
      const r = await this.api.post<{ done: number; errors: Record<string, string> }>('/jobs/actions', { ids: [this.jobId()], action });
      if (!r.done) this.error.set(Object.values(r.errors)[0] ?? this.i18n.t('detail.notPossible'));
      await this.load(this.jobId());
      this.changed.emit();
    } finally {
      this.busy.set(false);
    }
  }
}
