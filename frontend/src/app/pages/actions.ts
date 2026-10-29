import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, inject, signal, viewChildren } from '@angular/core';
import { Api } from '../api';
import { AllClear } from '../components/all-clear';
import { GmailConnect, GmailConnected } from '../components/gmail-connect';
import { Toast } from '../components/toast';
import { VaultGate, VaultReady } from '../components/vault-gate';
import { I18n, MsgPipe, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, labelOr, localeOf } from '../locale';
import { ActionDecision, ActionGroup, ActionItem, ActionKind, ActionQuestion, AnswerValue, Remember, Status } from '../types';

/** Kinds where signing in / solving it by hand in a real Chrome window can unblock the job. */
const BROWSER_KINDS: ActionKind[] = ['captcha', 'login_issue', 'two_factor', 'validation_error', 'unknown_question'];

/** Park codes that mean "set something up once": they get one card at the top instead of one card per job. */
const VAULT_CODES = ['needs_vault', 'vault_locked'];
const EMAIL_CODES = ['needs_email', 'email_not_connected'];
const EEO_KEYS = ['eeo_gender', 'eeo_race', 'eeo_hispanic', 'eeo_veteran', 'eeo_disability'];
const EEO_DECLINE: Remember = Object.fromEntries(EEO_KEYS.map((k) => [k, 'decline']));
const ACK_CATEGORIES = ['acknowledge_privacy', 'acknowledge_legal'];
const DECLINE = /decline|prefer not|do(?:n'?t| not) wish|not to (?:say|answer|disclose|identify|specify)|choose not|rather not/i;
const AGREE = /^\s*(?:yes|i\s*(?:agree|accept|acknowledge|consent|understand|certify|confirm)|agree|accept|acknowledge|consent)/i;

/** A question asked by several waiting applications, ready to draw like a single question. */
interface GroupCard {
  g: ActionGroup;
  q: ActionQuestion;
  /** Key of its typed answer in `draft`; stable while the group's first item stays open. */
  key: string;
}

const SOURCES: Record<string, string> = {
  profile: 'tier-high',
  sensitive: 'tier-mid',
  bank: 'tier-low',
  ai: 'alert-info',
  file: 'tier-low',
};

@Component({
  selector: 'app-actions',
  imports: [AllClear, GmailConnect, MsgPipe, NgTemplateOutlet, Toast, TPipe, VaultGate],
  template: `
    <p class="text-sm text-slate-500">{{ 'actions.intro' | t }}</p>

    <!-- One answer control, drawn for a single item or for a group; k is the key of its typed answer in the draft. -->
    <ng-template #ctl let-k="k" let-q="q" let-i="i">
      <label class="label" [attr.for]="'q' + k + '-' + i" dir="auto">
        {{ q.label }} @if (q.required) { <span class="text-rose-600" [title]="'actions.required' | t">*</span> }
      </label>
      @switch (widget(q)) {
        @case ('textarea') {
          <textarea class="input" rows="4" [id]="'q' + k + '-' + i" [value]="text(k, q.label)"
                    (input)="set(k, q.label, val($event))"></textarea>
        }
        @case ('multi') {
          <div class="space-y-1" role="group" [attr.aria-label]="q.label">
            @for (o of q.options; track o) {
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" [checked]="isOn(k, q.label, o)" (change)="toggle(k, q.label, o)"> <span dir="auto">{{ o }}</span>
              </label>
            }
          </div>
        }
        @case ('radio') {
          <div class="space-y-1" role="radiogroup" [attr.aria-label]="q.label">
            @for (o of choices(q); track o) {
              <label class="flex items-center gap-2 text-sm">
                <input type="radio" [name]="'q' + k + '-' + i" [checked]="draft()[k]?.[q.label] === o"
                       (change)="set(k, q.label, o)"> <span dir="auto">{{ optLabel(q, o) }}</span>
              </label>
            }
          </div>
        }
        @case ('checkbox') {
          <!-- never pre-ticked: the user picks Yes or No explicitly -->
          <select class="input" [id]="'q' + k + '-' + i" (change)="setBool(k, q.label, val($event))">
            <option value="" [selected]="draft()[k]?.[q.label] === undefined">{{ 'actions.choose' | t }}</option>
            <option value="yes" [selected]="draft()[k]?.[q.label] === true">{{ 'common.yes' | t }}</option>
            <option value="no" [selected]="draft()[k]?.[q.label] === false">{{ 'common.no' | t }}</option>
          </select>
        }
        @case ('select') {
          <select class="input" [id]="'q' + k + '-' + i" (change)="set(k, q.label, val($event))">
            <option value="" [selected]="!text(k, q.label)">{{ 'actions.choose' | t }}</option>
            @for (o of q.options; track o) { <option [value]="o" [selected]="text(k, q.label) === o">{{ o }}</option> }
          </select>
        }
        @default {
          <input class="input" [type]="inputType(q.kind)" [id]="'q' + k + '-' + i" [value]="text(k, q.label)"
                 (input)="set(k, q.label, val($event))">
        }
      }
      @if (q.reason) { <p class="hint" dir="auto">{{ q.reason }}</p> }
      @if (q.sensitive || q.category) {
        <p class="hint !text-amber-700 dark:!text-amber-400">{{ 'actions.sensitive' | t }}</p>
      }
    </ng-template>

    <!-- One-time "always" choices that depend on the question: kept in the profile, never guessed. -->
    <ng-template #extras let-k="k" let-q="q" let-a="a" let-c="c">
      @if (isNotice(q)) {
        <label class="mt-2 flex items-center gap-2 text-sm">
          <input type="checkbox" [checked]="kept(k, q)" (change)="keep(k, q, checked($event))"> {{ 'fin.keep' | t }}
        </label>
      }
      @if (isRelocate(q)) {
        <label class="mt-2 flex items-center gap-2 text-sm">
          <input type="checkbox" [checked]="kept(k, q)" (change)="keep(k, q, checked($event))"> {{ 'fin.keepRelocate' | t }}
        </label>
      }
      @if (isEeo(q) && declineOf(q); as d) {
        <button type="button" class="btn mt-2" [disabled]="busy()" (click)="declineAll(q, d, a, c)">{{ 'fin.eeo.decline' | t }}</button>
      }
    </ng-template>

    <div class="mt-5 max-w-4xl space-y-5">
      @if (vaultItems().length) {
        <section class="card" aria-labelledby="fin-vault">
          <h2 id="fin-vault">{{ plural('fin.vault', vaultItems().length) }}</h2>
          @if (sites(vaultItems()); as s) { <p class="mt-1 text-sm text-slate-600 dark:text-slate-400">{{ 'fin.sites' | t }} <bdi dir="ltr">{{ s }}</bdi></p> }
          <div class="mt-4">
            <app-vault-gate reason="fin.vault.why" (ready)="onVault($event)">
              <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="retryCodes(VAULT_CODES)">{{ 'actions.retry' | t }}</button>
            </app-vault-gate>
          </div>
          <button type="button" class="btn mt-4" [attr.aria-expanded]="shown().vault" (click)="toggleShown('vault')">{{ (shown().vault ? 'fin.hide' : 'fin.show') | t }}</button>
        </section>
      }

      @if (emailItems().length) {
        <section class="card" aria-labelledby="fin-email">
          <h2 id="fin-email">{{ plural('fin.email', emailItems().length) }}</h2>
          @if (sites(emailItems()); as s) { <p class="mt-1 text-sm text-slate-600 dark:text-slate-400">{{ 'fin.sites' | t }} <bdi dir="ltr">{{ s }}</bdi></p> }
          <div class="mt-4">
            <app-vault-gate reason="fin.email.vaultFirst" (ready)="onVault($event)">
              <p class="mb-3 text-sm text-slate-700 dark:text-slate-300">{{ 'fin.email.why' | t }}</p>
              <app-gmail-connect (connected)="onGmail($event)" />
            </app-vault-gate>
          </div>
          <button type="button" class="btn mt-4" [attr.aria-expanded]="shown().email" (click)="toggleShown('email')">{{ (shown().email ? 'fin.hide' : 'fin.show') | t }}</button>
        </section>
      }

      @for (c of groupCards(); track c.key) {
        <section class="card" [attr.aria-label]="c.g.label">
          <h2><span>{{ 'fin.group.asks' | t: { n: num(c.g.count) } }}</span>&ngsp;<bdi dir="auto" class="font-semibold">{{ c.g.label }}</bdi></h2>
          @if (companies(c.g); as co) { <p class="mt-1 text-sm text-slate-500" dir="auto">{{ co }}</p> }
          <div class="mt-4">
            <ng-container *ngTemplateOutlet="ctl; context: { k: c.key, q: c.q, i: 0 }" />
            <ng-container *ngTemplateOutlet="extras; context: { k: c.key, q: c.q, a: null, c: c }" />
          </div>
          @if (errors()[c.key]; as err) { <div class="alert alert-error mt-4" role="alert" dir="auto">{{ err }}</div> }
          <div class="mt-4">
            @if (ackOf(c.q); as ack) {
              <p class="mb-2 text-sm font-medium">{{ 'fin.ack.' + ack | t }}</p>
              <div class="flex flex-wrap gap-3">
                <button type="button" class="btn btn-primary" [disabled]="busy() || !hasValue(c.key, c.g.label)" (click)="answerGroup(c)">{{ 'fin.ack.once' | t }}</button>
                @if (acceptValue(c.q) !== null) {
                  <button type="button" class="btn" [disabled]="busy()" (click)="acceptAlways(c.q, ack, null, c)">{{ 'fin.ack.always' | t }}</button>
                }
                <button type="button" class="btn" [disabled]="busy() || !hasValue(c.key, c.g.label)" (click)="answerGroup(c)">{{ 'fin.ack.ask' | t }}</button>
              </div>
            } @else {
              <button type="button" class="btn btn-primary" [disabled]="busy() || !hasValue(c.key, c.g.label)" (click)="answerGroup(c)">{{ 'fin.group.answerAll' | t: { n: num(c.g.count) } }}</button>
            }
          </div>
        </section>
      }

      @for (a of visible(); track a.id) {
        <section class="card" [attr.aria-label]="a.job.title">
          <header class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-lg font-semibold text-slate-900 dark:text-white" dir="auto">{{ a.job.title }}</div>
              <div class="truncate text-sm text-slate-500" dir="auto"><bdi>{{ a.job.company }}</bdi> · <bdi>{{ a.job.location }}</bdi></div>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-1">
              @if (a.job.score) { <span class="text-xs text-slate-500">{{ 'actions.score' | t: { n: num(a.job.score) } }}</span> }
              <span class="text-xs text-slate-400">{{ when(a.created_at) }}</span>
            </div>
          </header>

          <!-- what happened, then why, then one main button -->
          <h3 class="mt-4 text-base font-semibold text-slate-900 dark:text-white">{{ 'actions.kind.' + a.kind | t }}</h3>
          @if (a.message) { <p class="mt-1 text-sm text-slate-700 dark:text-slate-300" dir="auto">{{ a | msg }}</p> }
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
                  <ng-container *ngTemplateOutlet="ctl; context: { k: a.id, q: q, i: i }" />
                  <ng-container *ngTemplateOutlet="extras; context: { k: a.id, q: q, a: a, c: null }" />
                </div>
              }
            </div>
            <div class="mt-4">
              @if (ackQuestion(a); as ack) {
                <p class="mb-2 text-sm font-medium">{{ 'fin.ack.' + ack.category | t }}</p>
                <div class="flex flex-wrap gap-3">
                  <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="send(a, 'answer')">{{ 'fin.ack.once' | t }}</button>
                  @if (acceptValue(ack) !== null) {
                    <button type="button" class="btn" [disabled]="busy()" (click)="acceptAlways(ack, ack.category!, a, null)">{{ 'fin.ack.always' | t }}</button>
                  }
                  <button type="button" class="btn" [disabled]="busy()" (click)="send(a, 'answer')">{{ 'fin.ack.ask' | t }}</button>
                </div>
              } @else {
                <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="send(a, 'answer')">{{ 'actions.saveRetry' | t }}</button>
              }
            </div>
          }

          @if (a.kind === 'confirm_submit') {
            <h4 class="mt-5 font-semibold">{{ 'actions.filled.title' | t }}</h4>
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
            <div class="mt-4">
              <button type="button" class="btn !border-emerald-700 !bg-emerald-600 !font-semibold !text-white hover:!bg-emerald-700"
                      [disabled]="busy()" (click)="send(a, 'confirm')">{{ 'actions.submit' | t }}</button>
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
              <button type="button" class="btn !border-emerald-700 !bg-emerald-600 !font-semibold !text-white hover:!bg-emerald-700"
                      [disabled]="busy() || !emailValid(a)" (click)="confirmEmail(a)">{{ 'actions.email.send' | t }}</button>
              <button type="button" class="btn" [disabled]="busy() || !emailDirty(a) || !emailValid(a)" (click)="saveDraft(a)">{{ 'actions.email.save' | t }}</button>
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
                <button type="button" class="btn" [class.btn-primary]="a.kind !== 'unknown_question' && !isSetup(a)"
                        [disabled]="browserBusy() || browser().open" (click)="openBrowser(a)">{{ 'actions.browser.openBtn' | t }}</button>
                @if (browser().open) { <p class="hint mt-1">{{ 'actions.browser.other' | t }}</p> }
              }
              <p class="hint mt-1">{{ 'actions.browser.hint' | t }}</p>
            </div>
          }

          @if (errors()[a.id]; as err) { <div class="alert alert-error mt-4" role="alert" dir="auto">{{ err }}</div> }

          <footer class="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
            <button type="button" class="btn" [class.btn-primary]="retryIsMain(a)" [disabled]="busy()" (click)="send(a, 'retry')">{{ 'actions.retry' | t }}</button>
            @if (hasPage(a)) {
              <a class="btn no-underline hover:no-underline" [href]="a.job.apply_url" target="_blank" rel="noopener">{{ 'actions.openPage' | t }}</a>
            }
            <button type="button" class="btn" [disabled]="busy()" (click)="send(a, 'applied_by_hand')">{{ 'actions.byHand' | t }}</button>
            <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="send(a, 'skip')">{{ 'actions.skip' | t }}</button>
          </footer>
        </section>
      }

      @if (loaded() && !items().length) {
        <app-all-clear />
      } @else if (!loaded()) {
        <div class="card text-center text-sm text-slate-500">{{ 'common.loading' | t }}</div>
      }
    </div>

    @if (toast()) { <app-toast [text]="toast()" /> }
  `,
})
export class ActionsPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  private readonly i18n = inject(I18n);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly VAULT_CODES = VAULT_CODES;
  private readonly gates = viewChildren(VaultGate);
  protected readonly items = signal<ActionItem[]>([]);
  protected readonly groups = signal<ActionGroup[]>([]);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly browserBusy = signal(false);
  protected readonly browser = signal<Status['app_browser']>({ open: false, item_id: null });
  /** Edited email subject / body per action id; absent until the user types. */
  protected readonly emailEdits = signal<Record<number, { subject?: string; body?: string }>>({});
  protected readonly emailSaved = signal<Record<number, boolean>>({});
  protected readonly errors = signal<Record<string, string>>({});
  /** Typed-in answers per card key (an action id, or a group's key), then question label. Survives reloads of the list. */
  protected readonly draft = signal<Record<string, Record<string, AnswerValue>>>({});
  /** "Use this for every application" boxes that are ticked, by card key and label. */
  private readonly keepOn = signal<Record<string, boolean>>({});
  /** Whether the individual cards behind each setup card are listed too. */
  protected readonly shown = signal({ vault: false, email: false });
  protected readonly toast = signal('');
  private toastTimer: ReturnType<typeof setTimeout> | undefined;

  protected readonly vaultItems = computed(() => this.items().filter((a) => VAULT_CODES.includes(a.code ?? '')));
  protected readonly emailItems = computed(() => this.items().filter((a) => EMAIL_CODES.includes(a.code ?? '')));
  /** The cards listed one by one: setup items only when asked for. */
  protected readonly visible = computed(() =>
    this.items().filter((a) => !(VAULT_CODES.includes(a.code ?? '') && !this.shown().vault) && !(EMAIL_CODES.includes(a.code ?? '') && !this.shown().email)),
  );
  /** Questions that two or more waiting applications ask: answer them once. */
  protected readonly groupCards = computed<GroupCard[]>(() =>
    this.groups()
      .filter((g) => g.count >= 2)
      .map((g) => {
        const first = this.items().find((a) => a.id === g.item_ids[0])?.questions.find((q) => q.label.trim() === g.label);
        const q: ActionQuestion = {
          label: g.label,
          kind: g.kind ?? 'text',
          options: g.options,
          required: true,
          reason: '',
          sensitive: g.sensitive,
          category: first?.category ?? null,
        };
        return { g, q, key: `g${g.item_ids[0]}` };
      }),
  );

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
  }

  async load(): Promise<void> {
    try {
      const [items, status, groups] = await Promise.all([
        this.api.get<ActionItem[]>('/actions?status=open'),
        this.api.get<Status>('/status'),
        this.api.get<ActionGroup[]>('/actions/groups').catch(() => [] as ActionGroup[]),
      ]);
      this.items.set(items);
      this.groups.set(groups);
      this.browser.set(status.app_browser);
    } catch (e) {
      // keep what we have; the live socket triggers another load on reconnect
      console.error(e);
    } finally {
      this.loaded.set(true);
    }
  }

  // ---- setup cards ---------------------------------------------------------------------------------------

  protected plural = (base: string, n: number): string => this.i18n.t(`${base}.${n === 1 ? 'one' : 'other'}`, { n: this.num(n) });
  protected isSetup = (a: ActionItem): boolean => VAULT_CODES.includes(a.code ?? '') || EMAIL_CODES.includes(a.code ?? '');
  /** The first three sites the waiting applications are for, then "+N". */
  protected sites(list: ActionItem[]): string {
    const names = [...new Set(list.map((a) => String(a.params?.['site'] ?? '')).filter(Boolean))];
    return names.slice(0, 3).join(', ') + (names.length > 3 ? ` +${this.num(names.length - 3)}` : '');
  }
  protected toggleShown(which: 'vault' | 'email'): void {
    this.shown.update((s) => ({ ...s, [which]: !s[which] }));
  }

  protected showToast(text: string): void {
    clearTimeout(this.toastTimer);
    this.toast.set(text);
    this.toastTimer = setTimeout(() => this.toast.set(''), 6000);
  }

  private continued(n: number): void {
    if (n > 0) this.showToast(this.plural('fin.continue', n));
    this.live.changed.update((c) => c + 1); // reloads this list and the badge in the shell
  }

  protected onVault(r: VaultReady): void {
    for (const g of this.gates()) void g.refresh(); // the other card's gate must notice the vault is open now
    this.continued(r.needs_vault + r.vault_locked);
  }

  protected onGmail(r: GmailConnected): void {
    this.continued(r.count);
  }

  /** The vault is open already but applications still wait for it: put them back in the queue. */
  protected async retryCodes(codes: string[]): Promise<void> {
    this.busy.set(true);
    try {
      let n = 0;
      for (const code of codes) n += (await this.api.post<{ count: number }>('/actions/retry-code', { code })).count;
      this.continued(n);
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    } finally {
      this.busy.set(false);
    }
  }

  // ---- answers: one control, one-time choices ------------------------------------------------------------------

  protected isNotice = (q: ActionQuestion): boolean => !q.sensitive && !q.category && /notice/i.test(q.label);
  protected isRelocate = (q: ActionQuestion): boolean => !q.sensitive && !q.category && /relocat/i.test(q.label);
  protected isEeo = (q: ActionQuestion): boolean => !!q.category && EEO_KEYS.includes(q.category);
  /** The "I'd rather not say" option of an option list, if the form has one. */
  protected declineOf = (q: ActionQuestion): string | null => q.options.find((o) => DECLINE.test(o)) ?? null;
  /** The first privacy or legal agreement this item asks. */
  protected ackQuestion = (a: ActionItem): ActionQuestion | undefined => a.questions.find((q) => ACK_CATEGORIES.includes(q.category ?? ''));
  protected ackOf = (q: ActionQuestion): string | null => (ACK_CATEGORIES.includes(q.category ?? '') ? q.category! : null);

  /** What "yes, I accept" means for this control, or null when we cannot tell (then there is no "Always accept"). */
  protected acceptValue(q: ActionQuestion): AnswerValue | null {
    if (q.kind === 'checkbox') return true;
    if (q.kind === 'yesno') return 'Yes';
    if (q.kind === 'multi') return q.options.length ? [...q.options] : null;
    if (q.kind === 'radio' || q.kind === 'select' || q.kind === 'combobox') return q.options.find((o) => AGREE.test(o)) ?? null;
    return null;
  }

  private keepKey = (k: string | number, q: ActionQuestion): string => `${k}|${q.label}`;
  protected kept = (k: string | number, q: ActionQuestion): boolean => !!this.keepOn()[this.keepKey(k, q)];
  protected keep(k: string | number, q: ActionQuestion, on: boolean): void {
    this.keepOn.update((m) => ({ ...m, [this.keepKey(k, q)]: on }));
  }

  /** What to keep in the profile for later applications: only what the user ticked, from what they typed. */
  private keepRemember(k: string | number, qs: ActionQuestion[]): Remember {
    const r: Remember = {};
    for (const q of qs) {
      if (!this.kept(k, q)) continue;
      const v = this.draft()[k]?.[q.label];
      if (this.isNotice(q) && typeof v === 'string' && v.trim()) r['notice_period'] = v.trim();
      if (this.isRelocate(q)) {
        const b = typeof v === 'boolean' ? v : typeof v === 'string' ? (/^(yes|true)/i.test(v) ? true : /^(no|false)/i.test(v) ? false : null) : null;
        if (b !== null) r['willing_to_relocate'] = b;
      }
    }
    return r;
  }

  protected hasValue(k: string | number, label: string): boolean {
    const v = this.draft()[k]?.[label];
    return typeof v === 'string' ? !!v.trim() : Array.isArray(v) ? v.length > 0 : typeof v === 'boolean';
  }

  /** "Always accept": answer this agreement with its accept value and keep the choice in the profile. */
  protected acceptAlways(q: ActionQuestion, category: string, a: ActionItem | null, c: GroupCard | null): Promise<void> {
    this.set(a ? a.id : c!.key, q.label, this.acceptValue(q)!);
    return a ? this.send(a, 'answer', { [category]: true }) : this.answerGroup(c!, { [category]: true });
  }

  /** "Prefer not to say for all demographic questions": decline this one and keep that for all five. */
  protected declineAll(q: ActionQuestion, option: string, a: ActionItem | null, c: GroupCard | null): Promise<void> {
    this.set(a ? a.id : c!.key, q.label, option);
    return a ? this.send(a, 'answer', EEO_DECLINE) : this.answerGroup(c!, EEO_DECLINE);
  }

  /** One answer for every application in the group; the server says how many continued and how many still need you. */
  async answerGroup(c: GroupCard, extra: Remember = {}): Promise<void> {
    if (!this.hasValue(c.key, c.g.label)) return;
    this.busy.set(true);
    this.errors.update(({ [c.key]: _drop, ...rest }) => rest);
    try {
      const remember = { ...this.keepRemember(c.key, [c.q]), ...extra };
      const r = await this.api.post<{ resolved: number; still_open: number }>('/actions/answer-group', {
        item_ids: c.g.item_ids,
        label: c.g.label,
        value: this.draft()[c.key][c.g.label],
        ...(Object.keys(remember).length ? { remember } : {}),
      });
      this.draft.update(({ [c.key]: _drop, ...rest }) => rest);
      this.showToast(this.i18n.t('fin.group.done', { resolved: this.num(r.resolved), still: this.num(r.still_open) }));
      this.live.changed.update((n) => n + 1);
    } catch (e) {
      this.errors.update((m) => ({ ...m, [c.key]: e instanceof Error ? e.message : String(e) }));
    } finally {
      this.busy.set(false);
    }
  }

  protected companies(g: ActionGroup): string {
    const names = g.item_ids.map((id) => this.items().find((a) => a.id === id)?.job.company).filter((n): n is string => !!n);
    return names.slice(0, 3).join(', ') + (names.length > 3 ? ` +${this.num(names.length - 3)}` : '');
  }

  // ---- email drafts ----------------------------------------------------------------------------------------

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

  // ---- helpers for the template ----------------------------------------------------------------------------

  /** Email applications have no page to open: the job's apply_url is a mailto: link. */
  hasPage = (a: ActionItem): boolean => a.kind !== 'confirm_email' && !a.job.apply_url.toLowerCase().startsWith('mailto:');
  browserKind = (k: ActionKind): boolean => BROWSER_KINDS.includes(k);
  hasHelp = (k: ActionKind): boolean => k !== 'unknown_question' && k !== 'confirm_submit';
  /** Retry is the main button when nothing else on the card is: setup cards, and kinds Chrome cannot fix. */
  retryIsMain = (a: ActionItem): boolean => a.kind !== 'confirm_submit' && a.kind !== 'confirm_email' && (this.isSetup(a) || !this.browserKind(a.kind));
  num = (n: number | null): string => fmtNum(this.loc(), n);
  sourceLabel = (s: string): string => labelOr(this.i18n, 'common.answerSource.', s || 'unknown');
  range = (n: number): number[] => Array.from({ length: n }, (_, i) => i);
  shot = (id: number, n: number): string => `/api/actions/${id}/screenshot/${n}`;
  when = (iso: string): string => new Date(iso).toLocaleString(this.loc());
  sourceClass = (s: string): string => SOURCES[s] ?? 'tier-low';
  val = (e: Event): string => (e.target as HTMLInputElement).value;
  checked = (e: Event): boolean => (e.target as HTMLInputElement).checked;
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

  text(k: string | number, label: string): string {
    const v = this.draft()[k]?.[label];
    return typeof v === 'string' ? v : '';
  }

  set(k: string | number, label: string, value: AnswerValue): void {
    this.draft.update((d) => ({ ...d, [k]: { ...d[k], [label]: value } }));
  }

  setBool(k: string | number, label: string, v: string): void {
    this.draft.update((d) => {
      const { [label]: _drop, ...rest } = d[k] ?? {};
      return { ...d, [k]: v ? { ...rest, [label]: v === 'yes' } : rest };
    });
  }

  isOn(k: string | number, label: string, option: string): boolean {
    const v = this.draft()[k]?.[label];
    return Array.isArray(v) && v.includes(option);
  }

  toggle(k: string | number, label: string, option: string): void {
    const v = this.draft()[k]?.[label];
    const cur = Array.isArray(v) ? v : [];
    this.set(k, label, cur.includes(option) ? cur.filter((x) => x !== option) : [...cur, option]);
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

  /** `extra`: profile answers to keep for good ("Always"), added to what the user ticked on the card. */
  async send(a: ActionItem, decision: ActionDecision, extra: Remember = {}): Promise<void> {
    this.busy.set(true);
    this.errors.update(({ [a.id]: _drop, ...rest }) => rest);
    try {
      const answers = decision === 'answer' ? (this.draft()[a.id] ?? {}) : {};
      const remember = decision === 'answer' ? { ...this.keepRemember(a.id, a.questions), ...extra } : {};
      await this.api.post(`/actions/${a.id}`, { decision, answers, ...(Object.keys(remember).length ? { remember } : {}) });
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
