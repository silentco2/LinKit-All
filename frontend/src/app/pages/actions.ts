import { Component, computed, effect, inject, signal } from '@angular/core';
import { Api } from '../api';
import { AllClear } from '../components/all-clear';
import { I18n, MsgPipe, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, labelOr, localeOf } from '../locale';
import { ActionDecision, ActionItem, ActionKind, ActionQuestion, AnswerValue, Status } from '../types';

/** Kinds where signing in / solving it by hand in a real Chrome window can unblock the job. */
const BROWSER_KINDS: ActionKind[] = ['captcha', 'login_issue', 'two_factor', 'validation_error', 'unknown_question'];

const SOURCES: Record<string, string> = {
  profile: 'tier-high',
  sensitive: 'tier-mid',
  bank: 'tier-low',
  ai: 'alert-info',
  file: 'tier-low',
};

@Component({
  selector: 'app-actions',
  imports: [AllClear, MsgPipe, TPipe],
  template: `
    <p class="text-sm text-slate-500">{{ 'actions.intro' | t }}</p>

    <div class="mt-5 max-w-4xl space-y-5">
      @for (a of items(); track a.id) {
        <section class="card" [attr.aria-label]="a.job.title">
          <header class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-lg font-semibold text-slate-900 dark:text-white" dir="auto">{{ a.job.title }}</div>
              <div class="truncate text-sm text-slate-500" dir="auto"><bdi>{{ a.job.company }}</bdi> · <bdi>{{ a.job.location }}</bdi></div>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-1">
              <span class="badge tier-mid">{{ 'actions.kind.' + a.kind | t }}</span>
              @if (a.job.score) { <span class="text-xs text-slate-500">{{ 'actions.score' | t: { n: num(a.job.score) } }}</span> }
              <span class="text-xs text-slate-400">{{ when(a.created_at) }}</span>
            </div>
          </header>

          @if (a.message) { <p class="mt-3 text-sm text-slate-700 dark:text-slate-300" dir="auto">{{ a | msg }}</p> }
          @if (hasHelp(a.kind)) { <div class="alert alert-info mt-3">{{ 'actions.help.' + a.kind | t }}</div> }

          @if (a.screenshots) {
            <div class="mt-4 flex flex-wrap gap-3">
              @for (n of range(a.screenshots); track n) {
                <a [href]="shot(a.id, n)" target="_blank" rel="noopener">
                  <img [src]="shot(a.id, n)" [alt]="'actions.screenshot' | t: { n: n + 1 }"
                       class="max-h-64 rounded-lg border border-slate-200 dark:border-slate-700">
                </a>
              }
            </div>
          }

          @if (a.kind === 'unknown_question') {
            <div class="alert alert-info mt-4">{{ 'actions.unknown.info' | t }}</div>
            <div class="mt-4 space-y-5">
              @for (q of a.questions; track q.label; let i = $index) {
                <div>
                  <label class="label" [attr.for]="'q' + a.id + '-' + i" dir="auto">
                    {{ q.label }} @if (q.required) { <span class="text-rose-600" [title]="'actions.required' | t">*</span> }
                  </label>
                  @switch (widget(q)) {
                    @case ('textarea') {
                      <textarea class="input" rows="4" [id]="'q' + a.id + '-' + i" [value]="text(a.id, q.label)"
                                (input)="set(a.id, q.label, val($event))"></textarea>
                    }
                    @case ('multi') {
                      <div class="space-y-1" role="group" [attr.aria-label]="q.label">
                        @for (o of q.options; track o) {
                          <label class="flex items-center gap-2 text-sm">
                            <input type="checkbox" [checked]="isOn(a.id, q.label, o)" (change)="toggle(a.id, q.label, o)"> <span dir="auto">{{ o }}</span>
                          </label>
                        }
                      </div>
                    }
                    @case ('radio') {
                      <div class="space-y-1" role="radiogroup" [attr.aria-label]="q.label">
                        @for (o of choices(q); track o) {
                          <label class="flex items-center gap-2 text-sm">
                            <input type="radio" [name]="'q' + a.id + '-' + i" [checked]="draft()[a.id]?.[q.label] === o"
                                   (change)="set(a.id, q.label, o)"> <span dir="auto">{{ optLabel(q, o) }}</span>
                          </label>
                        }
                      </div>
                    }
                    @case ('checkbox') {
                      <!-- never pre-ticked: the user picks Yes or No explicitly -->
                      <select class="input" [id]="'q' + a.id + '-' + i" (change)="setBool(a.id, q.label, val($event))">
                        <option value="" [selected]="draft()[a.id]?.[q.label] === undefined">{{ 'actions.choose' | t }}</option>
                        <option value="yes" [selected]="draft()[a.id]?.[q.label] === true">{{ 'common.yes' | t }}</option>
                        <option value="no" [selected]="draft()[a.id]?.[q.label] === false">{{ 'common.no' | t }}</option>
                      </select>
                    }
                    @case ('select') {
                      <select class="input" [id]="'q' + a.id + '-' + i" (change)="set(a.id, q.label, val($event))">
                        <option value="" [selected]="!text(a.id, q.label)">{{ 'actions.choose' | t }}</option>
                        @for (o of q.options; track o) { <option [value]="o" [selected]="text(a.id, q.label) === o">{{ o }}</option> }
                      </select>
                    }
                    @default {
                      <input class="input" [type]="inputType(q.kind)" [id]="'q' + a.id + '-' + i" [value]="text(a.id, q.label)"
                             (input)="set(a.id, q.label, val($event))">
                    }
                  }
                  @if (q.reason) { <p class="hint" dir="auto">{{ q.reason }}</p> }
                  @if (q.sensitive) {
                    <p class="hint !text-amber-700 dark:!text-amber-400">{{ 'actions.sensitive' | t }}</p>
                  }
                </div>
              }
            </div>
            <div class="mt-4">
              <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="send(a, 'answer')">{{ 'actions.saveRetry' | t }}</button>
            </div>
          }

          @if (a.kind === 'confirm_submit') {
            <h2 class="mt-5">{{ 'actions.filled.title' | t }}</h2>
            <div class="overflow-x-auto">
              <table class="mt-2 w-full text-sm">
                <tbody>
                  @for (row of entries(a); track row.label) {
                    <tr class="border-t border-slate-100 align-top dark:border-slate-800">
                      <th scope="row" class="w-2/5 py-2 pe-3 text-start font-medium text-slate-600 dark:text-slate-400" dir="auto">{{ row.label }}</th>
                      <td class="py-2 pe-3 break-words" dir="auto">{{ show(row.value) }}</td>
                      <td class="py-2 text-end"><span class="badge {{ sourceClass(row.source) }}">{{ sourceLabel(row.source) }}</span></td>
                    </tr>
                  } @empty {
                    <tr><td class="py-2 text-slate-500">{{ 'actions.filled.empty' | t }}</td></tr>
                  }
                </tbody>
              </table>
            </div>
            <div class="mt-4 flex flex-wrap gap-3">
              <button type="button" class="btn !border-emerald-700 !bg-emerald-600 !font-semibold !text-white hover:!bg-emerald-700"
                      [disabled]="busy()" (click)="send(a, 'confirm')">{{ 'actions.submit' | t }}</button>
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="send(a, 'skip')">{{ 'actions.skip' | t }}</button>
            </div>
          }

          @if (a.kind === 'confirm_email' && a.email_draft; as d) {
            <dl class="mt-4 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
              <dt class="font-medium text-slate-600 dark:text-slate-400">{{ 'actions.email.to' | t }}</dt>
              <dd class="break-words" dir="ltr"><bdi>{{ d.to }}</bdi></dd>
              <dt class="font-medium text-slate-600 dark:text-slate-400">{{ 'actions.email.attachment' | t }}</dt>
              <dd class="break-words"><bdi>{{ d.attachment }}</bdi></dd>
            </dl>
            <div class="mt-4 space-y-4">
              <div>
                <label class="label" [attr.for]="'es' + a.id">{{ 'actions.email.subject' | t }}</label>
                <input class="input" [id]="'es' + a.id" dir="auto" maxlength="200" [value]="subjectOf(a)" (input)="editEmail(a, 'subject', val($event))">
              </div>
              <div>
                <label class="label" [attr.for]="'eb' + a.id">{{ 'actions.email.body' | t }}</label>
                <textarea class="input" rows="10" dir="auto" maxlength="10000" [id]="'eb' + a.id" [value]="bodyOf(a)" (input)="editEmail(a, 'body', val($event))"></textarea>
              </div>
            </div>
            @if (emailSaved()[a.id]) { <div class="alert alert-ok mt-3" role="status">{{ 'actions.email.saved' | t }}</div> }
            <div class="mt-4 flex flex-wrap gap-3">
              <button type="button" class="btn" [disabled]="busy() || !emailDirty(a) || !emailValid(a)" (click)="saveDraft(a)">{{ 'actions.email.save' | t }}</button>
              <button type="button" class="btn !border-emerald-700 !bg-emerald-600 !font-semibold !text-white hover:!bg-emerald-700"
                      [disabled]="busy() || !emailValid(a)" (click)="confirmEmail(a)">{{ 'actions.email.send' | t }}</button>
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="send(a, 'skip')">{{ 'actions.skip' | t }}</button>
            </div>
          }

          @if (browserKind(a.kind)) {
            <div class="mt-4">
              @if (browser().open && browser().item_id === a.id) {
                <div class="flex flex-wrap items-center gap-3">
                  <span class="badge tier-high">{{ 'actions.browser.open' | t }}</span>
                  <button type="button" class="btn" [disabled]="browserBusy()" (click)="closeBrowser(a)">{{ 'actions.browser.close' | t }}</button>
                </div>
              } @else {
                <button type="button" class="btn" [disabled]="browserBusy() || browser().open" (click)="openBrowser(a)">{{ 'actions.browser.openBtn' | t }}</button>
                @if (browser().open) { <p class="hint mt-1">{{ 'actions.browser.other' | t }}</p> }
              }
              <p class="hint mt-1">{{ 'actions.browser.hint' | t }}</p>
            </div>
          }

          @if (errors()[a.id]; as err) { <div class="alert alert-error mt-4" role="alert" dir="auto">{{ err }}</div> }

          <footer class="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
            <button type="button" class="btn" [disabled]="busy()" (click)="send(a, 'retry')">{{ 'actions.retry' | t }}</button>
            @if (hasPage(a)) {
              <a class="btn no-underline hover:no-underline" [href]="a.job.apply_url" target="_blank" rel="noopener">{{ 'actions.openPage' | t }}</a>
            }
            <button type="button" class="btn" [disabled]="busy()" (click)="send(a, 'applied_by_hand')">{{ 'actions.byHand' | t }}</button>
            @if (a.kind !== 'confirm_submit' && a.kind !== 'confirm_email') {
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="send(a, 'skip')">{{ 'actions.skip' | t }}</button>
            }
          </footer>
        </section>
      } @empty {
        @if (loaded()) { <app-all-clear /> } @else { <div class="card text-center text-sm text-slate-500">{{ 'common.loading' | t }}</div> }
      }
    </div>
  `,
})
export class ActionsPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  private readonly i18n = inject(I18n);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly items = signal<ActionItem[]>([]);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly browserBusy = signal(false);
  protected readonly browser = signal<Status['app_browser']>({ open: false, item_id: null });
  /** Edited email subject / body per action id; absent until the user types. */
  protected readonly emailEdits = signal<Record<number, { subject?: string; body?: string }>>({});
  protected readonly emailSaved = signal<Record<number, boolean>>({});
  protected readonly errors = signal<Record<number, string>>({});
  /** Typed-in answers per action id, then question label. Survives reloads of the list. */
  protected readonly draft = signal<Record<number, Record<string, AnswerValue>>>({});

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
  }

  async load(): Promise<void> {
    try {
      const [items, status] = await Promise.all([
        this.api.get<ActionItem[]>('/actions?status=open'),
        this.api.get<Status>('/status'),
      ]);
      this.items.set(items);
      this.browser.set(status.app_browser);
    } catch (e) {
      // keep what we have; the live socket triggers another load on reconnect
      console.error(e);
    } finally {
      this.loaded.set(true);
    }
  }

  subjectOf = (a: ActionItem): string => this.emailEdits()[a.id]?.subject ?? a.email_draft?.subject ?? '';
  bodyOf = (a: ActionItem): string => this.emailEdits()[a.id]?.body ?? a.email_draft?.body ?? '';
  emailDirty = (a: ActionItem): boolean => this.subjectOf(a) !== (a.email_draft?.subject ?? '') || this.bodyOf(a) !== (a.email_draft?.body ?? '');
  emailValid = (a: ActionItem): boolean => !!this.subjectOf(a).trim() && !!this.bodyOf(a).trim();
  editEmail(a: ActionItem, field: 'subject' | 'body', value: string): void {
    this.emailEdits.update((m) => ({ ...m, [a.id]: { ...m[a.id], [field]: value } }));
    this.emailSaved.update(({ [a.id]: _drop, ...rest }) => rest);
  }

  /** PUT the edited subject and body; the server keeps them as the text that will be sent. */
  async saveDraft(a: ActionItem): Promise<boolean> {
    this.busy.set(true);
    this.errors.update(({ [a.id]: _drop, ...rest }) => rest);
    try {
      await this.api.put(`/actions/${a.id}/email-draft`, { subject: this.subjectOf(a).trim(), body: this.bodyOf(a) });
      this.emailEdits.update(({ [a.id]: _drop, ...rest }) => rest);
      this.emailSaved.update((m) => ({ ...m, [a.id]: true }));
      await this.load();
      return true;
    } catch (e) {
      this.errors.update((m) => ({ ...m, [a.id]: e instanceof Error ? e.message : String(e) }));
      return false;
    } finally {
      this.busy.set(false);
    }
  }

  /** Confirming sends the stored draft, so unsaved edits are saved first. */
  async confirmEmail(a: ActionItem): Promise<void> {
    if (this.emailDirty(a) && !(await this.saveDraft(a))) return;
    await this.send(a, 'confirm');
  }

  /** Email applications have no page to open: the job's apply_url is a mailto: link. */
  hasPage = (a: ActionItem): boolean => a.kind !== 'confirm_email' && !a.job.apply_url.toLowerCase().startsWith('mailto:');
  browserKind = (k: ActionKind): boolean => BROWSER_KINDS.includes(k);
  hasHelp = (k: ActionKind): boolean => k !== 'unknown_question' && k !== 'confirm_submit';
  num = (n: number | null): string => fmtNum(this.loc(), n);
  sourceLabel = (s: string): string => labelOr(this.i18n, 'common.answerSource.', s || 'unknown');
  range = (n: number): number[] => Array.from({ length: n }, (_, i) => i);
  shot = (id: number, n: number): string => `/api/actions/${id}/screenshot/${n}`;
  when = (iso: string): string => new Date(iso).toLocaleString(this.loc());
  sourceClass = (s: string): string => SOURCES[s] ?? 'tier-low';
  val = (e: Event): string => (e.target as HTMLInputElement).value;
  /** Which control to draw: radios and yes/no -> radio, dropdowns with options -> select, the rest as typed. */
  widget(q: ActionQuestion): string {
    if (q.kind === 'radio' || q.kind === 'yesno') return 'radio';
    if (q.kind === 'select' || q.kind === 'combobox') return q.options.length ? 'select' : 'text';
    return q.kind === 'textarea' || q.kind === 'multi' || q.kind === 'checkbox' ? q.kind : 'text';
  }
  inputType = (kind: string): string => (['email', 'tel', 'number', 'url', 'date'].includes(kind) ? kind : 'text');
  // 'Yes' / 'No' are the values sent to the server; only their labels are translated.
  choices = (q: ActionQuestion): string[] => (q.options.length ? q.options : q.kind === 'yesno' ? ['Yes', 'No'] : []);
  optLabel = (q: ActionQuestion, o: string): string =>
    q.options.length ? o : o === 'Yes' ? this.i18n.t('common.yes') : o === 'No' ? this.i18n.t('common.no') : o;
  entries = (a: ActionItem) => Object.entries(a.answers).map(([label, v]) => ({ label, ...v }));

  show(v: unknown): string {
    if (typeof v === 'boolean') return this.i18n.t(v ? 'common.yes' : 'common.no');
    if (Array.isArray(v)) return v.join(', ');
    return v == null ? '' : String(v);
  }

  text(id: number, label: string): string {
    const v = this.draft()[id]?.[label];
    return typeof v === 'string' ? v : '';
  }

  set(id: number, label: string, value: AnswerValue): void {
    this.draft.update((d) => ({ ...d, [id]: { ...d[id], [label]: value } }));
  }

  setBool(id: number, label: string, v: string): void {
    this.draft.update((d) => {
      const { [label]: _drop, ...rest } = d[id] ?? {};
      return { ...d, [id]: v ? { ...rest, [label]: v === 'yes' } : rest };
    });
  }

  isOn(id: number, label: string, option: string): boolean {
    const v = this.draft()[id]?.[label];
    return Array.isArray(v) && v.includes(option);
  }

  toggle(id: number, label: string, option: string): void {
    const v = this.draft()[id]?.[label];
    const cur = Array.isArray(v) ? v : [];
    this.set(id, label, cur.includes(option) ? cur.filter((x) => x !== option) : [...cur, option]);
  }

  /** Open or close the app's Chrome window for this item; server errors (409, 503) are shown as they come. */
  async toggleBrowser(a: ActionItem, open: boolean): Promise<void> {
    this.browserBusy.set(true);
    this.errors.update(({ [a.id]: _drop, ...rest }) => rest);
    try {
      if (open) await this.api.post(`/actions/${a.id}/browser`);
      else await this.api.delete(`/actions/${a.id}/browser`);
    } catch (e) {
      this.errors.update((m) => ({ ...m, [a.id]: e instanceof Error ? e.message : String(e) }));
    } finally {
      this.browserBusy.set(false);
      await this.load();
    }
  }
  openBrowser = (a: ActionItem): Promise<void> => this.toggleBrowser(a, true);
  closeBrowser = (a: ActionItem): Promise<void> => this.toggleBrowser(a, false);

  async send(a: ActionItem, decision: ActionDecision): Promise<void> {
    this.busy.set(true);
    this.errors.update(({ [a.id]: _drop, ...rest }) => rest);
    try {
      const answers = decision === 'answer' ? (this.draft()[a.id] ?? {}) : {};
      await this.api.post(`/actions/${a.id}`, { decision, answers });
      this.draft.update(({ [a.id]: _drop, ...rest }) => rest);
      // bumping `changed` reloads this list and the nav badge in the shell
      this.live.changed.update((n) => n + 1);
    } catch (e) {
      this.errors.update((m) => ({ ...m, [a.id]: e instanceof Error ? e.message : String(e) }));
    } finally {
      this.busy.set(false);
    }
  }
}
