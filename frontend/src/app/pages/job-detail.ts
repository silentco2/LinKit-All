import { DatePipe, NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, MsgPipe, SourcePipe, TPipe } from '../i18n';
import { fmtNum, labelOr, localeOf } from '../locale';
import { JobDetail, SCAM_MEDIUM, TailorPatch, TrustVerdict } from '../types';

interface Filled { value: unknown; source: string }
type Detail = Omit<JobDetail, 'events'> & {
  filled?: Record<string, Filled> | null;
  events: { id: number; at: string; to: string; message: string; code?: string | null; params?: Record<string, unknown> | null; screenshots: number }[];
};

interface DiffOp { kind: 'same' | 'del' | 'ins'; word: string }

/** Word-level diff by longest common subsequence; CV segments are short, so O(n*m) is fine. */
function wordDiff(a: string, b: string): DiffOp[] {
  const x = a.split(/\s+/).filter(Boolean);
  const y = b.split(/\s+/).filter(Boolean);
  const lcs = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const ops: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) {
      ops.push({ kind: 'same', word: x[i++] });
      j++;
    } else if (i < x.length && (j === y.length || lcs[i + 1][j] >= lcs[i][j + 1])) ops.push({ kind: 'del', word: x[i++] });
    else ops.push({ kind: 'ins', word: y[j++] });  // deletions first, so a replaced word reads old-then-new
  }
  return ops;
}

const APPROVABLE = ['awaiting_review', 'below_threshold'];
const FINAL = ['applied', 'skipped', 'filtered_out'];

@Component({
  selector: 'app-job-detail',
  imports: [DatePipe, NgTemplateOutlet, MsgPipe, SourcePipe, TPipe],
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
            <span class="badge tier-low"><bdi>{{ j.source | src }}</bdi></span>
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

        @if (j.trust; as tr) {
          <section class="rounded-lg border border-slate-200 p-4 dark:border-slate-700" [attr.aria-label]="'trust.title' | t">
            <h3 class="font-semibold">{{ 'trust.title' | t }}</h3>
            <div class="mt-2 grid gap-3 sm:grid-cols-2">
              @for (kind of kinds; track kind) {
                @let v = verdict(tr, kind);
                <div>
                  <p class="flex flex-wrap items-center gap-2 text-sm">
                    <span class="font-medium">{{ 'trust.' + kind | t }}</span>
                    <span class="badge {{ bandClass(v.band) }}"><bdi dir="ltr">{{ num(v.score) }}/{{ num(100) }}</bdi> · {{ 'trust.band.' + v.band | t }}</span>
                  </p>
                  <ul class="mt-1 space-y-1 text-sm">
                    @for (sg of v.signals; track sg.code) {
                      <li>
                        <span class="font-medium">{{ signalLabel(sg.code) }}</span>
                        <span class="text-xs text-slate-500"> · {{ 'trust.weight' | t: { w: sgn(sg.weight) } }}</span>
                        @if (sg.evidence) { <span class="block text-xs break-words text-slate-500" dir="auto">{{ sg.evidence }}</span> }
                      </li>
                    } @empty {
                      <li class="text-xs text-slate-500">{{ 'trust.noSignals' | t }}</li>
                    }
                  </ul>
                </div>
              }
            </div>
            @if (tr.ghost_demoted) { <p class="alert alert-info mt-3" role="note">{{ 'trust.demoted' | t }}</p> }
            @if (aiNoticed(j); as note) { <p class="mt-3 text-sm text-rose-700 dark:text-rose-300" dir="auto">{{ 'trust.aiNoticed' | t: { text: note } }}</p> }
            @if (notice()) { <p class="alert alert-ok mt-3" role="status">{{ notice() }}</p> }
            <div class="mt-3 flex flex-wrap gap-2">
              @if (tr.scam.score >= scamMedium || j.state === 'filtered_out') {
                <button type="button" class="btn" (click)="trust('not_scam')" [disabled]="busy()">{{ 'trust.notScam' | t }}</button>
              }
              @if (j.state !== 'applied') {
                <button type="button" class="btn btn-danger" (click)="trust('report')" [disabled]="busy()">{{ 'trust.report' | t }}</button>
              }
            </div>
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

        @if (j.tailoring; as t) {
          <section>
            <h3 class="flex flex-wrap items-center gap-2 font-semibold">
              {{ 'detail.tailor.title' | t }}
              <span class="badge text-xs font-normal {{ tailorClass(t.status) }}">{{ 'detail.tailor.status.' + t.status | t }}</span>
            </h3>
            <p class="mt-1 text-xs text-slate-500">{{ t.created_at | date: 'medium' : undefined : loc() }}</p>
            @if (t.status === 'rolled_back') { <div class="alert alert-error mt-2">{{ 'detail.tailor.rolledBack' | t }}</div> }
            @if (t.status === 'unchanged') { <p class="mt-2 text-sm text-slate-600 dark:text-slate-400">{{ 'detail.tailor.unchanged' | t }}</p> }
            <ul class="mt-2 space-y-3">
              @for (p of t.patches; track $index) {
                <li><ng-container [ngTemplateOutlet]="patch" [ngTemplateOutletContext]="{ $implicit: p }" /></li>
              }
            </ul>
            @if (t.rejected.length) {
              <details class="mt-3">
                <summary class="cursor-pointer text-sm font-medium">{{ 'detail.tailor.rejected' | t: { n: num(t.rejected.length) } }}</summary>
                <ul class="mt-2 space-y-3">
                  @for (p of t.rejected; track $index) {
                    <li><ng-container [ngTemplateOutlet]="patch" [ngTemplateOutletContext]="{ $implicit: p }" /></li>
                  }
                </ul>
              </details>
            }
            @if (t.verify; as v) {
              <p class="mt-3 text-sm" [class.text-rose-700]="!v.ok" [class.dark:text-rose-300]="!v.ok">
                <span class="font-medium">{{ (v.ok ? 'detail.tailor.verify.ok' : 'detail.tailor.verify.bad') | t }}</span>
                {{ 'detail.tailor.verify.pages' | t: { from: num(v.pages[0]), to: num(v.pages[1]) } }} ·
                {{ 'detail.tailor.verify.similarity' | t: { pct: num(v.min_ssim, { style: 'percent', maximumFractionDigits: 1 }) } }}
                @if (v.reason) { · <span dir="auto">{{ v.reason }}</span> }
              </p>
            }
            @if (t.status === 'tailored') {
              <a class="btn mt-3 no-underline hover:no-underline" [href]="'/api/jobs/' + j.id + '/tailored.pdf'" target="_blank" rel="noopener noreferrer">{{ 'detail.tailor.download' | t }}</a>
            }
          </section>
        }

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
              <li><span class="text-slate-500">{{ e.at | date: 'short' : undefined : loc() }}</span> <span class="inline-block rtl:rotate-180">→</span> <span class="font-medium">{{ 'common.state.' + e.to | t }}</span> <span dir="auto">{{ e | msg }}</span>
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

    <ng-template #patch let-p>
      <div class="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700">
        <p class="leading-relaxed" dir="auto">
          @for (op of diff(p); track $index) {
            @switch (op.kind) {
              @case ('del') { <del class="rounded line-through bg-rose-50 px-0.5 text-rose-700 dark:bg-rose-950 dark:text-rose-300">{{ op.word }}</del>{{ ' ' }} }
              @case ('ins') { <ins class="rounded underline bg-emerald-50 px-0.5 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">{{ op.word }}</ins>{{ ' ' }} }
              @default { {{ op.word + ' ' }} }
            }
          }
        </p>
        @if (p.reason) { <p class="mt-1 text-xs text-slate-500" dir="auto">{{ p.reason }}</p> }
      </div>
    </ng-template>
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
  protected readonly notice = signal('');
  protected readonly kinds = ['scam', 'ghost'] as const;
  protected readonly scamMedium = SCAM_MEDIUM;

  constructor() {
    effect(() => {
      const id = this.jobId();
      this.load(id);
    });
  }

  private readonly diffs = new WeakMap<TailorPatch, DiffOp[]>();
  protected diff(p: TailorPatch): DiffOp[] {
    let ops = this.diffs.get(p);
    if (!ops) this.diffs.set(p, (ops = wordDiff(p.old_text ?? '', p.new_text ?? '')));
    return ops;
  }
  protected tailorClass = (s: string): string => ({ tailored: 'tier-high', rolled_back: 'tier-mid' })[s] ?? 'tier-low';

  protected verdict = (tr: NonNullable<Detail['trust']>, kind: 'scam' | 'ghost'): TrustVerdict => tr[kind] ?? { score: 0, band: 'low', signals: [] };
  protected bandClass = (b: string): string => ({ high: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300', medium: 'tier-mid' })[b] ?? 'tier-low';
  protected signalLabel = (code: string): string => labelOr(this.i18n, 'trust.', code);
  protected sgn = (w: number): string => '\u2066' + (w > 0 ? '+' : '') + fmtNum(this.loc(), w) + '\u2069';

  /** What the batched AI score said about legitimacy, shown beside the offline signals. */
  protected aiNoticed(j: Detail): string {
    const ai = j.ai;
    if (!ai) return '';
    const parts: string[] = [];
    if (ai.legit === 'scam' || ai.legit === 'suspicious') parts.push(this.i18n.t('trust.aiVerdict.' + ai.legit));
    parts.push(...(ai.trust_flags ?? []));
    return parts.join('; ');
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

  private loadSeq = 0;

  async load(id: number): Promise<void> {
    const seq = ++this.loadSeq; // a newer load supersedes this one, so a slow reply cannot overwrite it
    this.error.set('');
    this.notice.set('');
    if (this.job()?.id !== id) this.job.set(null); // never show the previous job under the new selection
    try {
      const d = await this.api.get<Detail>(`/jobs/${id}`);
      if (seq === this.loadSeq) this.job.set(d);
    } catch (e) {
      if (seq === this.loadSeq) this.error.set((e as Error).message);
    }
  }

  async trust(action: 'not_scam' | 'report'): Promise<void> {
    const j = this.job();
    if (!j) return;
    if (action === 'report' && !confirm(this.i18n.t('trust.reportConfirm', { company: j.company }))) return;
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.jobTrust(j.id, action);
      await this.load(j.id);
      this.notice.set(this.i18n.t('trust.done.' + action));
      this.changed.emit();
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
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
