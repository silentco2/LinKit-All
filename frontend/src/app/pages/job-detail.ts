import { Component, computed, effect, inject, input, OnDestroy, output, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, MsgPipe, SourcePipe, TPipe } from '../i18n';
import { DtPipe, fmtNum, labelOr, localeOf } from '../locale';
import { PatchDiff } from '../components/patch-diff';
import { Toast } from '../components/toast';
import { Shell } from '../shell';
import { isLeftOut, JobDetail, reasonSetting, reasonText, SCAM_MEDIUM, TrustVerdict } from '../types';
import { SettingsStore } from './settings/store';

interface Filled { value: unknown; source: string }
type Detail = Omit<JobDetail, 'events'> & {
  filled?: Record<string, Filled> | null;
  events: { id: number; at: string; to: string; message: string; code?: string | null; params?: Record<string, unknown> | null; screenshots: number }[];
};

const APPROVABLE = ['awaiting_review', 'below_threshold'];
const FINAL = ['applied', 'skipped', 'filtered_out'];

@Component({
  selector: 'app-job-detail',
  imports: [DtPipe, MsgPipe, PatchDiff, RouterLink, SourcePipe, Toast, TPipe],
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
            @if (j.posted_at) { <span class="text-slate-500">{{ 'detail.posted' | t }} {{ j.posted_at | dt: 'date' }}</span> }
          </div>
          @if (why(j); as text) {
            <p class="mt-2 text-sm"><span class="font-medium">{{ (leftOut(j) ? 'detail.whyOut' : 'detail.why') | t }} </span><span dir="auto">{{ text }}</span></p>
            @if (target(j); as tg) {
              <p class="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                <a [routerLink]="['/settings', tg.section]" [fragment]="tg.focus" class="inline-flex min-h-10 items-center">{{ (j.reason_code === 'location' ? 'fix.addPlace' : 'fix.openSetting') | t }}</a>
                @if (quickFix(j); as q) {
                  <button type="button" class="btn" (click)="runFix(j)" [disabled]="busy()">{{ q.label }}</button>
                }
              </p>
            }
          }
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

        @if (j.source === 'linkedin_posts') {
          <section class="rounded-lg border border-slate-200 p-4 text-sm dark:border-slate-700" [attr.aria-label]="'source.linkedin_posts' | t">
            <p dir="auto">
              {{ 'detail.linkedin.from' | t: { author: post(j).author } }}@if (post(j).headline) { (<bdi>{{ post(j).headline }}</bdi>) }
            </p>
            <p class="mt-2 flex flex-wrap gap-x-4 gap-y-1">
              @if (post(j).postUrl; as u) { <a [href]="u" target="_blank" rel="noopener noreferrer">{{ 'detail.linkedin.post' | t }} ↗</a> }
            </p>
            <p class="mt-2"><span class="font-medium">{{ 'detail.linkedin.method' | t }}:</span>
              @if (post(j).method === 'email' && post(j).email) {
                {{ 'detail.linkedin.method.email' | t: { email: '\u2066' + post(j).email + '\u2069' } }}
              } @else {
                {{ 'detail.linkedin.method.' + (post(j).method === 'form' ? 'form' : 'link') | t }}
              }
            </p>
            @if (j.email_sent; as sent) {
              <p class="alert alert-ok mt-3" role="status">{{ 'detail.emailed' | t: { to: sent.to, date: sentOn(sent.sent_at) } }}</p>
            }
          </section>
        }

        @if (j.ai; as ai) {
          <section class="rounded-lg bg-slate-50 p-4 dark:bg-slate-950">
            <h3 class="font-semibold">{{ 'detail.ai.score' | t: { score: ai.score, out: 10 } }}</h3>
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
            <p class="mt-1 text-xs text-slate-500">{{ t.created_at | dt: 'medium' }}</p>
            @if (t.status === 'rolled_back') { <div class="alert alert-error mt-2">{{ 'detail.tailor.rolledBack' | t }}</div> }
            @if (t.status === 'unchanged') { <p class="mt-2 text-sm text-slate-600 dark:text-slate-400">{{ 'detail.tailor.unchanged' | t }}</p> }
            <ul class="mt-2 space-y-3">
              @for (p of t.patches; track $index) {
                <li><app-patch-diff [patch]="p" /></li>
              }
            </ul>
            @if (t.rejected.length) {
              <details class="mt-3">
                <summary class="cursor-pointer text-sm font-medium">{{ 'detail.tailor.rejected' | t: { n: num(t.rejected.length) } }}</summary>
                <ul class="mt-2 space-y-3">
                  @for (p of t.rejected; track $index) {
                    <li><app-patch-diff [patch]="p" /></li>
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
          <ol class="mt-2 space-y-2 border-s border-slate-200 ps-4 text-xs sm:space-y-1 dark:border-slate-700">
            @for (e of j.events; track $index) {
              <li class="max-sm:flex max-sm:flex-col max-sm:gap-0.5"><span class="text-slate-500">{{ e.at | dt: 'short' }}</span> <span><span class="inline-block rtl:rotate-180">→</span> <span class="font-medium">{{ 'common.state.' + e.to | t }}</span> <span dir="auto">{{ e | msg }}</span></span>
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

    @if (fixNote(); as note) { <app-toast [text]="note" [action]="'review.undo' | t" (act)="undoFix()" /> }
  `,
})
export class JobDetailPanel implements OnDestroy {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly store = inject(SettingsStore);
  private readonly shell = inject(Shell);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  readonly jobId = input.required<number>();
  readonly changed = output<void>();
  protected readonly job = signal<Detail | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly notice = signal('');
  /** The toast after a one-click fix ("sales" allowed) and how to take it back. */
  protected readonly fixNote = signal('');
  private undo?: () => void;
  private fixTimer?: ReturnType<typeof setTimeout>;
  protected readonly kinds = ['scam', 'ghost'] as const;
  protected readonly scamMedium = SCAM_MEDIUM;

  constructor() {
    effect(() => {
      const id = this.jobId();
      this.load(id);
    });
  }

  protected tailorClass = (s: string): string => ({ tailored: 'tier-high', rolled_back: 'tier-mid' })[s] ?? 'tier-low';

  protected verdict = (tr: NonNullable<Detail['trust']>, kind: 'scam' | 'ghost'): TrustVerdict => tr[kind] ?? { score: 0, band: 'low', signals: [] };
  protected bandClass = (b: string): string => ({ high: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300', medium: 'tier-mid' })[b] ?? 'tier-low';
  protected why = (j: Detail): string => reasonText(this.i18n, j);
  protected leftOut = isLeftOut;
  protected target = (j: Detail) => reasonSetting(j.reason_code);

  /** A safe one-click fix for the reason, if there is one: allow the word, or unblock the company. */
  protected quickFix(j: Detail): { label: string } | null {
    if (j.reason_code === 'title_excluded' && j.reason_params?.['word']) return { label: this.i18n.t('fix.allowWord', { word: String(j.reason_params['word']) }) };
    if (j.reason_code === 'blacklist' && j.company) return { label: this.i18n.t('fix.unblock') };
    return null;
  }

  /** Take the word (or company) off its list in the saved settings; Undo puts it back. Jobs already left out stay until the next search. */
  protected async runFix(j: Detail): Promise<void> {
    const word = j.reason_code === 'title_excluded' ? String(j.reason_params?.['word'] ?? '') : j.company;
    const key = j.reason_code === 'title_excluded' ? 'filters.title_exclude' : 'filters.company_blacklist';
    if (!word) return;
    this.busy.set(true);
    try {
      await this.store.load();
      if (!this.store.loaded()) throw new Error(this.store.loadError());
      const list: string[] = this.store.get(key);
      const same = (w: string) => w.trim().toLowerCase() === word.trim().toLowerCase();
      const entries = list.filter(same);
      if (!entries.length) throw new Error(this.i18n.t('fix.notFound'));
      this.store.update(key, list.filter((w) => !same(w)));
      this.undo = () => this.store.update(key, [...this.store.get(key), ...entries]);
      this.say(this.i18n.t(j.reason_code === 'title_excluded' ? 'fix.allowed' : 'fix.unblocked', { word }));
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  protected undoFix(): void {
    this.undo?.();
    this.say('');
  }

  private say(text: string): void {
    clearTimeout(this.fixTimer);
    this.fixNote.set(text);
    if (text) this.fixTimer = setTimeout(() => this.fixNote.set(''), 10_000);
  }

  ngOnDestroy(): void {
    clearTimeout(this.fixTimer);
  }
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

  /** The facts a linkedin_posts job carries in `extra`; the post link is the job URL without its `#n` suffix. */
  protected post(j: Detail): { author: string; headline: string; method: string; email: string; postUrl: string } {
    const x = j.extra ?? {};
    const str = (k: string): string => (typeof x[k] === 'string' ? (x[k] as string) : '');
    const url = j.url.split('#')[0];
    return {
      author: str('author') || j.company,
      headline: str('headline'),
      method: str('apply_method'),
      email: str('apply_email'),
      postUrl: /^https?:\/\//i.test(url) ? url : '',
    };
  }
  protected sentOn = (iso: string): string => new Date(iso).toLocaleDateString(this.loc(), { dateStyle: 'medium' });
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
      void this.shell.refresh(); // the nav badge and Home count it as decided
    } finally {
      this.busy.set(false);
    }
  }
}
