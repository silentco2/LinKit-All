import { Component, computed, effect, ElementRef, inject, OnDestroy, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api, ApiError } from '../api';
import { AllClear } from '../components/all-clear';
import { Toast } from '../components/toast';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, localeOf } from '../locale';
import { Shell } from '../shell';
import { APPLY_STAGES, JobRow } from '../types';
import { JobDetailPanel } from './job-detail';

type Tab = 'awaiting_review' | 'below_threshold';
type Verb = 'approve' | 'reject';

/** Approvals and skips wait this long (so Undo can cancel them) before they are sent. */
const UNDO_MS = 10_000;

/** A group of jobs approved or skipped together, hidden from the list and not yet sent to the server. */
interface Pending {
  id: number;
  action: Verb;
  ids: number[];
  /** Taken from the "waiting for your OK" list (not the weak-match list), so it counts against the badge until it is sent. */
  review: boolean;
  timer: ReturnType<typeof setTimeout>;
}

/** Input types where a letter key is not typed text, so the list shortcuts still work. */
const NON_TEXT_INPUTS = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'file']);

const SHORTCUTS: [string, string][] = [
  ['J / K', 'review.keys.move'],
  ['A', 'review.keys.approve'],
  ['S', 'review.keys.skip'],
  ['Shift + A', 'review.keys.approveSel'],
  ['Z', 'review.keys.undo'],
  ['O', 'review.keys.open'],
  ['X', 'review.keys.select'],
  ['?', 'review.keys.help'],
];

@Component({
  selector: 'app-review',
  host: {
    '(document:keydown.escape)': 'escape()',
    '(document:keydown)': 'onKey($event)',
    '(window:beforeunload)': 'flushAll(true)',
  },
  imports: [AllClear, JobDetailPanel, Toast, TPipe],
  template: `
    <p class="text-sm text-slate-500">{{ 'review.intro' | t }} <button type="button" class="text-brand-600 hover:underline max-sm:min-h-10" (click)="help.set(true)">{{ 'review.keys.link' | t }}</button></p>

    <div class="mt-5 flex flex-wrap gap-2" role="tablist">
      @for (t of tabs; track t.id) {
        <button type="button" role="tab" class="btn" [class.btn-primary]="tab() === t.id" [attr.aria-selected]="tab() === t.id"
                (click)="tab.set(t.id); load()">{{ t.label | t }}</button>
      }
    </div>

    <div class="sr-only" aria-live="polite" role="status">{{ announce() }}</div>
    @if (error(); as e) { <div class="alert alert-error mt-4" role="alert" dir="auto">{{ e }}</div> }

    @if (shown().length) {
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" [checked]="picked().size === shown().length" (change)="toggleAll()"> {{ 'review.selectAll' | t: { n: num(shown().length) } }}
        </label>
        <button class="btn btn-primary" [disabled]="!picked().size" (click)="queue('approve', [...picked()])">{{ 'review.approveBtn' | t }} {{ picked().size ? num(picked().size) : '' }}</button>
        <button class="btn btn-danger" [disabled]="!picked().size" (click)="queue('reject', [...picked()])">{{ 'review.skipBtn' | t }} {{ picked().size ? num(picked().size) : '' }}</button>
      </div>
    }

    <div class="mt-4 max-w-4xl">
      <ul class="space-y-3">
        @for (j of shown(); track j.id) {
          <li class="card flex gap-4 p-4 outline-offset-2" tabindex="-1" [attr.data-job]="j.id" [attr.aria-current]="focus() === j.id ? 'true' : null"
              [class.ring-2]="open() === j.id" [class.ring-brand-500]="open() === j.id"
              [class.outline-3]="focus() === j.id" [class.outline-brand-600]="focus() === j.id" [class.outline]="focus() === j.id"
              (click)="focus.set(j.id)">
            <label class="flex shrink-0 items-start pt-1.5 max-sm:-m-2 max-sm:size-10 max-sm:items-center max-sm:justify-center max-sm:pt-0">
              <input type="checkbox" [checked]="picked().has(j.id)" (change)="toggle(j.id)" [attr.aria-label]="'review.select' | t: { title: j.title }">
            </label>
            <div class="min-w-0 flex-1">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="truncate font-medium" dir="auto">{{ j.title }}</div>
                  <div class="truncate text-sm text-slate-500" dir="auto"><bdi>{{ j.company }}</bdi> · <bdi>{{ j.location }}</bdi></div>
                </div>
                <div class="flex shrink-0 flex-wrap items-center justify-end gap-2 max-sm:max-w-[45%]">
                  @if (j.reason) { <span class="badge tier-low text-start whitespace-normal" dir="auto">{{ why(j) }}</span> }
                  @if (j.score) { <span class="badge tier-{{ j.tier }}"><bdi>{{ 'review.score' | t: { n: j.score, out: 10 } }}</bdi></span> }
                </div>
              </div>
              @if (j.ai; as ai) {
                <ul class="mt-2 list-disc ps-5 text-sm text-slate-700 dark:text-slate-300">
                  @for (r of ai.reasons.slice(0, 2); track r) { <li dir="auto">{{ r }}</li> }
                </ul>
                @if (ai.missing_skills.length) { <p class="mt-1 text-xs text-slate-500">{{ 'review.missing' | t }} <bdi>{{ ai.missing_skills.join(', ') }}</bdi></p> }
                @if (ai.red_flags.length) { <p class="mt-1 text-xs text-rose-600 dark:text-rose-400">{{ 'review.redFlags' | t }} <bdi>{{ ai.red_flags.join(', ') }}</bdi></p> }
              }
              <div class="mt-2 flex flex-wrap items-center gap-3">
                <button type="button" class="btn px-3 py-1 max-sm:min-h-10" (click)="queue('approve', [j.id])">{{ 'review.approveBtn' | t }}</button>
                <button type="button" class="btn btn-danger px-3 py-1 max-sm:min-h-10" (click)="queue('reject', [j.id])">{{ 'review.skipBtn' | t }}</button>
                <button type="button" class="text-sm text-brand-600 hover:underline max-sm:min-h-10 max-sm:px-2" (click)="open.set(j.id)">{{ 'review.details' | t }}</button>
              </div>
            </div>
          </li>
        } @empty {
          <li>
            @if (tab() === 'awaiting_review') { <app-all-clear /> }
            @else { <div class="card text-center text-sm text-slate-500">{{ 'review.empty.low' | t }}</div> }
          </li>
        }
      </ul>
      @if (open(); as id) {
        <aside class="fixed inset-y-0 end-0 z-20 w-full max-w-xl overflow-auto border-s border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900" [attr.aria-label]="'common.drawer.label' | t">
          <button type="button" class="btn float-end ms-3 px-2 py-1" [attr.aria-label]="'common.drawer.close' | t" (click)="open.set(null)">✕</button>
          <app-job-detail [jobId]="id" (changed)="load()" />
        </aside>
      }
    </div>

    @if (help()) {
      <div class="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4" (click)="help.set(false)">
        <div class="card w-full max-w-sm" role="dialog" aria-modal="true" aria-labelledby="review-keys" (click)="$event.stopPropagation()">
          <div class="flex items-center justify-between gap-3">
            <h2 id="review-keys">{{ 'review.keys.title' | t }}</h2>
            <button type="button" class="btn px-2 py-1" [attr.aria-label]="'common.drawer.close' | t" (click)="help.set(false)">✕</button>
          </div>
          <dl class="mt-4 grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
            @for (s of shortcuts; track s[0]) {
              <dt><kbd class="rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-xs dark:border-slate-600 dark:bg-slate-800" dir="ltr">{{ s[0] }}</kbd></dt>
              <dd>{{ s[1] | t }}</dd>
            }
          </dl>
        </div>
      </div>
    }

    @if (toast(); as m) {
      <app-toast [text]="m" [action]="pending.length ? ('review.undo' | t) : ''" (act)="undo()" [action2]="offerApply() ? applyLabel() : ''" (act2)="applyNow()" />
    }
  `,
})
export class ReviewPage implements OnDestroy {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  private readonly shell = inject(Shell);
  private readonly i18n = inject(I18n);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly shortcuts = SHORTCUTS;
  protected readonly tabs: { id: Tab; label: string }[] = [
    { id: 'awaiting_review', label: 'review.tab.needs' },
    { id: 'below_threshold', label: 'review.tab.low' },
  ];
  protected readonly tab = signal<Tab>('awaiting_review');
  protected readonly jobs = signal<JobRow[]>([]);
  /** Jobs approved or skipped a moment ago: gone from the list, still waiting to be sent. */
  private readonly hidden = signal(new Set<number>());
  protected readonly shown = computed(() => this.jobs().filter((j) => !this.hidden().has(j.id)));
  protected readonly picked = signal(new Set<number>());
  protected readonly open = signal<number | null>(null);
  protected readonly focus = signal<number | null>(null);
  protected readonly help = signal(false);
  protected readonly toast = signal('');
  /** The toast follows an approval: it also offers to apply right away. */
  protected readonly offerApply = signal(false);
  protected readonly applyLabel = computed(() => this.i18n.t(this.shell.status()?.apply_live ? 'review.applyNow' : 'review.applyNowPractice'));
  private offerTimer: ReturnType<typeof setTimeout> | undefined;
  protected readonly announce = signal('');
  protected readonly error = signal('');
  protected pending: Pending[] = [];
  private seq = 0;

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
  }

  ngOnDestroy(): void {
    clearTimeout(this.offerTimer);
    this.flushAll(false);
  }

  protected num = (n: number): string => fmtNum(this.loc(), n);
  /** The plain-words reason, in the UI language when the server gave a code we have a sentence for. */
  protected why = (j: JobRow): string => this.i18n.msg({ message: j.reason ?? '', code: j.reason_code, params: j.reason_params });

  async load(): Promise<void> {
    this.picked.set(new Set());
    this.jobs.set(await this.api.get<JobRow[]>(`/jobs?state=${this.tab()}`));
    const f = this.focus();
    if (f !== null && !this.shown().some((j) => j.id === f)) this.focus.set(null);
  }

  toggle(id: number): void {
    this.picked.update((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  toggleAll(): void {
    const all = this.picked().size === this.shown().length;
    this.picked.set(new Set(all ? [] : this.shown().map((j) => j.id)));
  }

  // ---- approve / skip with Undo ---------------------------------------------------------------------------

  /** Hide the jobs now; send the request after 10 seconds unless the user presses Undo. */
  queue(action: Verb, ids: number[]): void {
    if (!ids.length) return;
    const batch: Pending = { id: ++this.seq, action, ids, review: this.tab() === 'awaiting_review', timer: setTimeout(() => void this.send(batch, false), UNDO_MS) };
    this.pending.push(batch);
    this.syncPending();
    this.hide(ids, true);
    const taken = new Set(ids);
    this.picked.update((s) => new Set([...s].filter((id) => !taken.has(id))));
    const o = this.open();
    if (o !== null && taken.has(o)) this.open.set(null);
    this.focusNear(ids);
    const text = this.i18n.plural(`review.${action === 'approve' ? 'approved' : 'skipped'}`, ids.length);
    clearTimeout(this.offerTimer);
    this.offerApply.set(action === 'approve');
    this.toast.set(text);
    this.announce.set(`${text}. ${this.i18n.t('review.undo')}`);
  }

  /** Put the latest batch back; nothing was sent. */
  protected undo(): void {
    const batch = this.pending.pop();
    if (!batch) return;
    clearTimeout(batch.timer);
    this.hide(batch.ids, false);
    this.syncPending();
    this.toast.set('');
    this.announce.set(this.i18n.plural('review.restored', batch.ids.length));
    this.focus.set(batch.ids[0]);
  }

  /** Tell the shell how many jobs sit in the Undo window, so the badge, the tab and Home count them as gone right away. */
  private syncPending(): void {
    this.shell.pendingReview.set(this.pending.filter((b) => b.review).reduce((n, b) => n + b.ids.length, 0));
  }

  private hide(ids: number[], on: boolean): void {
    this.hidden.update((s) => {
      const next = new Set(s);
      for (const id of ids) on ? next.add(id) : next.delete(id);
      return next;
    });
  }

  /** Send one batch now. On leaving the page the request must outlive it, hence `keepalive`. */
  private async send(batch: Pending, keepalive: boolean): Promise<void> {
    const at = this.pending.indexOf(batch);
    if (at < 0) return;
    this.pending.splice(at, 1);
    clearTimeout(batch.timer);
    if (!this.pending.length) this.toast.set('');
    const body = { ids: batch.ids, action: batch.action };
    try {
      if (keepalive) {
        await fetch('/api/jobs/actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), keepalive: true });
        return;
      }
      await this.api.post('/jobs/actions', body);
      this.error.set('');
      if (batch.action === 'approve' && !this.pending.length) this.keepOffer(batch.ids.length);
    } catch (e) {
      this.hide(batch.ids, false); // not saved: show them again
      this.syncPending();
      this.error.set(e instanceof Error ? e.message : String(e));
      return;
    }
    // the shell's status first, then the pending count: the other way round the badge would jump up for a moment
    await Promise.all([this.shell.refresh(), this.load()]);
    this.syncPending();
    this.hide(batch.ids, false); // only once the list no longer holds them, so they cannot flash back
  }

  /** Approved and sent: the confirmation stays a while longer with just "Apply now". */
  private keepOffer(n: number): void {
    this.offerApply.set(true);
    this.toast.set(this.i18n.plural('review.approved', n));
    clearTimeout(this.offerTimer);
    this.offerTimer = setTimeout(() => {
      if (!this.pending.length) this.toast.set('');
    }, 15_000);
  }

  /** Send what is still in the Undo window, then start the apply stage and show it on Activity. */
  protected async applyNow(): Promise<void> {
    this.error.set('');
    try {
      await Promise.all([...this.pending].map((b) => this.send(b, false)));
      this.toast.set('');
      await this.api.post('/runs', { stages: APPLY_STAGES, new: false });
      await this.router.navigate(['/activity']);
    } catch (e) {
      // a missing tool (409 + code): Home has the offer to install it or to use the CV as it is
      if (e instanceof ApiError && e.code) await this.router.navigate(['/']);
      else this.error.set((e as Error).message);
    }
  }

  /** Send everything still waiting for its Undo window: on leaving the page or closing the tab. */
  protected flushAll(keepalive: boolean): void {
    for (const batch of [...this.pending]) void this.send(batch, keepalive);
  }

  // ---- keyboard ---------------------------------------------------------------------------------------------

  protected escape(): void {
    if (this.help()) this.help.set(false);
    else this.open.set(null);
  }

  protected onKey(e: KeyboardEvent): void {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    const t = e.target as HTMLElement | null;
    // typing places ignore the shortcuts; a checkbox or button that kept the focus (after "Select all") does not
    if (t && (/^(select|textarea)$/i.test(t.tagName) || t.isContentEditable || (t instanceof HTMLInputElement && !NON_TEXT_INPUTS.has(t.type)))) return;
    const k = e.key.toLowerCase();
    if (k === '?') {
      this.help.update((v) => !v);
      e.preventDefault();
      return;
    }
    if (this.help() || this.open() !== null) return;
    if (k === 'z') {
      if (!this.pending.length) return;
      this.undo();
      e.preventDefault();
      return;
    }
    if (k === 'a' && e.shiftKey) {
      if (!this.picked().size) return;
      this.queue('approve', [...this.picked()]);
      e.preventDefault();
      return;
    }
    const list = this.shown();
    const cur = list.findIndex((j) => j.id === this.focus());
    const job = list[cur];
    if (k === 'j' || k === 'k') {
      if (!list.length) return;
      const next = list[Math.min(list.length - 1, Math.max(0, cur < 0 ? 0 : cur + (k === 'j' ? 1 : -1)))];
      this.focus.set(next.id);
      this.reveal(next.id);
    } else if (job && (k === 'a' || k === 's')) {
      this.queue(k === 'a' ? 'approve' : 'reject', [job.id]);
    } else if (job && k === 'o') {
      this.open.set(job.id);
    } else if (job && k === 'x') {
      this.toggle(job.id);
    } else return;
    e.preventDefault();
  }

  /** Scroll the card into view and move real focus to it, so screen readers follow. */
  private reveal(id: number): void {
    queueMicrotask(() => {
      const el = this.host.nativeElement.querySelector<HTMLElement>(`[data-job="${id}"]`);
      el?.focus({ preventScroll: true });
      el?.scrollIntoView({ block: 'nearest' });
    });
  }

  /** After hiding jobs, focus the card that took their place (the next one, else the one before). */
  private focusNear(ids: number[]): void {
    const taken = new Set(ids);
    const list = this.jobs().filter((j) => !this.hidden().has(j.id) || taken.has(j.id));
    const at = list.findIndex((j) => taken.has(j.id));
    const keep = list.filter((j) => !taken.has(j.id));
    if (at < 0 || this.focus() === null || !keep.length) return;
    const next = keep[Math.min(at, keep.length - 1)];
    this.focus.set(next.id);
    this.reveal(next.id);
  }
}
