import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { EmailState } from '../types';

type Note = { ok: boolean; text: string };

/** What a successful connect did: the saved email state and how many waiting applications were requeued. */
export type EmailConnected = { email: EmailState; count: number };

let nextId = 0;

/**
 * Connect Gmail (or Yahoo) with an app password, or Outlook/Hotmail/Live/MSN with "Sign in with Microsoft": how-to
 * steps, the form, the address (read-only until its edit button is pressed) and, once connected, the test/disconnect buttons. Used in Settings > Accounts and inline on Needs you.
 * `unlocked`: the password vault is open (the app password or Microsoft sign-in is stored there); when it is not, only a hint shows.
 * After a connect it requeues the applications parked for `needs_email` and emits `connected`.
 */
@Component({
  selector: 'app-email-connect',
  imports: [TPipe],
  host: { class: 'block' },
  template: `
    <div class="space-y-4">
      @if (note(); as n) {
        <div class="alert" [class.alert-ok]="n.ok" [class.alert-error]="!n.ok" [attr.role]="n.ok ? 'status' : 'alert'" dir="auto">{{ n.text }}</div>
      }
      @if (!unlocked()) {
        <div class="alert alert-info" role="status">{{ 'settings.acc.needVault' | t }}</div>
      } @else {
        @if (email()?.connected) {
          <div class="alert alert-ok" role="status">{{ 'setup.email.connectedAs' | t }} <bdi dir="ltr">{{ email()!.imap_user }}</bdi>.</div>
        }
        <div class="max-w-sm">
          <label class="label" [for]="id + '-user'">{{ 'setup.email.address' | t }}</label>
          <div class="flex items-center gap-2">
            <input #addr [id]="id + '-user'" type="email" dir="ltr" autocomplete="email"
              class="input read-only:bg-slate-100 read-only:text-slate-600 dark:read-only:bg-slate-800 dark:read-only:text-slate-300"
              [value]="eUser()" [readOnly]="!editable()" (change)="setUser(val($event))"
              (keydown.enter)="saveEdit(addr)" (keydown.escape)="cancelEdit(addr)">
            @if (eUser()) {
              <button type="button" class="btn shrink-0" [attr.aria-label]="(editing() ? 'setup.email.editDone' : 'setup.email.edit') | t"
                [title]="(editing() ? 'setup.email.editDone' : 'setup.email.edit') | t" (click)="editing() ? saveEdit(addr) : startEdit(addr)">
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  @if (editing()) { <path d="M20 6 9 17l-5-5" /> } @else { <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /> }
                </svg>
              </button>
            }
          </div>
        </div>
        @if (outlook()) {
          @if (!email()?.microsoft) {
            <div class="alert alert-info" role="status">{{ 'settings.acc.outlook' | t }}</div>
          } @else if (!linked()) {
            <ol class="list-decimal space-y-1 ps-5 text-sm text-slate-700 dark:text-slate-300">
              <li>{{ 'settings.acc.ms.step1' | t }}</li>
              <li>{{ 'settings.acc.ms.step2' | t }}</li>
              <li>{{ 'settings.acc.ms.step3' | t }}</li>
            </ol>
            <button type="button" class="btn btn-primary" (click)="signInMicrosoft()" [disabled]="busy()">{{ 'settings.acc.ms.signIn' | t }}</button>
            @if (busy()) { <p class="hint" role="status">{{ 'settings.acc.ms.waiting' | t }}</p> }
          }
        } @else {
          @if (!linked()) {
            <ol class="list-decimal space-y-1 ps-5 text-sm text-slate-700 dark:text-slate-300">
              <li>{{ 'settings.acc.step1' | t }} <a href="https://myaccount.google.com/security" target="_blank" rel="noopener">{{ 'settings.acc.open' | t }}</a></li>
              <li>{{ 'settings.acc.step2' | t }} <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">{{ 'settings.acc.open' | t }}</a></li>
              <li>{{ 'settings.acc.step3' | t }}</li>
            </ol>
            @if (yahoo()) { <p class="hint">{{ 'settings.acc.yahoo' | t }}</p> }
            <form class="space-y-3" (submit)="connect($event)">
              <div class="max-w-sm">
                <label class="label" [for]="id + '-pass'">{{ 'setup.email.appPass' | t }}</label>
                <input [id]="id + '-pass'" type="password" dir="ltr" class="input" name="app-password" autocomplete="off" placeholder="abcd efgh ijkl mnop" [value]="ePass()" (input)="ePass.set(val($event))">
              </div>
              <button type="submit" class="btn btn-primary" [disabled]="busy() || !ePass().trim() || !eUser()">{{ 'settings.acc.connect' | t }}</button>
            </form>
          }
        }
        @if (email()?.connected) {
          <div class="flex flex-wrap gap-3">
            <button type="button" class="btn" (click)="test()" [disabled]="busy()">{{ 'setup.email.testAgain' | t }}</button>
            <button type="button" class="btn" (click)="testSend()" [disabled]="busy()">{{ 'setup.email.testSend' | t }}</button>
            <button type="button" class="btn" (click)="disconnect()" [disabled]="busy()">{{ 'setup.email.disconnect' | t }}</button>
          </div>
          <p class="hint">{{ 'setup.email.testSendHint' | t }}</p>
        }
      }
    </div>
  `,
})
export class EmailConnect {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  readonly unlocked = input(true);
  readonly connected = output<EmailConnected>();
  protected readonly id = `ec${++nextId}`;
  protected readonly email = signal<EmailState | null>(null);
  protected readonly note = signal<Note | null>(null);
  protected readonly busy = signal(false);
  protected readonly eUser = signal('');
  protected readonly eHost = signal('imap.gmail.com');
  protected readonly ePass = signal('');
  protected readonly editing = signal(false);
  /** With no address yet there is nothing to protect, so the box starts open. */
  protected readonly editable = computed(() => this.editing() || !this.eUser());
  /** The address in the box is the connected one; a changed address needs connecting first. */
  protected readonly linked = computed(() => !!this.email()?.connected && this.eUser().toLowerCase() === this.email()!.imap_user.toLowerCase());
  private readonly domain = computed(() => (this.eUser().split('@')[1] ?? '').trim().toLowerCase());
  protected readonly outlook = computed(() => /^(outlook|hotmail|live|msn)\./.test(this.domain()));
  protected readonly yahoo = computed(() => /^(yahoo\.|ymail\.com$)/.test(this.domain()));

  constructor() {
    // load on first show, and again when the vault opens (the saved address is only reported once it is)
    effect(() => {
      this.unlocked();
      void this.load();
    });
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  private async load(): Promise<void> {
    try {
      this.setEmail(await this.api.get<EmailState>('/email'));
    } catch (e) {
      this.note.set({ ok: false, text: (e as Error).message });
    }
  }

  /** Gmail, Yahoo and Outlook have fixed IMAP servers; any other address keeps what is there. */
  private hostFor(user: string, current: string): string {
    const d = (user.split('@')[1] ?? '').trim().toLowerCase();
    if (d === 'gmail.com' || d === 'googlemail.com') return 'imap.gmail.com';
    if (/^(outlook|hotmail|live|msn)\./.test(d)) return 'outlook.office365.com';
    return /^(yahoo\.|ymail\.com$)/.test(d) ? 'imap.mail.yahoo.com' : current;
  }

  private setEmail(e: EmailState): void {
    this.email.set(e);
    this.editing.set(false);
    this.eUser.set(e.imap_user);
    this.eHost.set(this.hostFor(e.imap_user, e.imap_host));
  }

  protected setUser(v: string): void {
    this.eUser.set(v.trim());
    this.eHost.set(this.hostFor(v, this.eHost()));
  }

  protected startEdit(box: HTMLInputElement): void {
    this.editing.set(true);
    box.focus();
    box.select();
  }

  protected saveEdit(box: HTMLInputElement): void {
    this.setUser(box.value);
    this.editing.set(false);
  }

  protected cancelEdit(box: HTMLInputElement): void {
    box.value = this.eUser();
    this.editing.set(false);
  }

  /** Run an action; it returns the (already translated) text to show. */
  private async run(action: () => Promise<string | void>): Promise<void> {
    this.busy.set(true);
    this.note.set(null);
    try {
      const text = await action();
      if (text) this.note.set({ ok: true, text });
    } catch (e) {
      this.note.set({ ok: false, text: (e as Error).message });
    } finally {
      this.busy.set(false);
    }
  }

  protected connect(ev: Event): Promise<void> {
    ev.preventDefault();
    return this.run(async () => {
      const e = await this.api.post<EmailState>('/email', { imap_host: this.eHost(), imap_user: this.eUser(), app_password: this.ePass() });
      this.ePass.set('');
      return this.afterConnect(e);
    });
  }

  /** The server opens Microsoft's sign-in page in the browser and answers once the user is done (or after 5 minutes). */
  protected signInMicrosoft(): Promise<void> {
    return this.run(async () => this.afterConnect(await this.api.post<EmailState>('/email/microsoft', { imap_user: this.eUser() })));
  }

  /** Requeue the applications that waited for an email, tell the parent, and return the message to show. */
  private async afterConnect(e: EmailState): Promise<string> {
    this.setEmail(e);
    const count = await this.api.post<{ count: number }>('/actions/retry-code', { code: 'needs_email' }).then((r) => r.count).catch(() => 0);
    this.connected.emit({ email: e, count });
    const text = this.i18n.t('setup.email.connectedMsg', { user: e.imap_user });
    if (count <= 0) return text;
    return `${text}. ${this.i18n.plural('settings.acc.waiting', count)}`;
  }

  protected test(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/email/test');
      return this.i18n.t('setup.email.works');
    });
  }

  /** Send one short test message to the user's own address through SMTP. */
  protected testSend(): Promise<void> {
    return this.run(async () => {
      const r = await this.api.post<{ ok: boolean; message_id?: string; error?: string }>('/email/test-send');
      if (!r.ok) throw new Error(this.i18n.t('setup.email.testFailed', { error: r.error ?? '' }));
      return this.i18n.t('setup.email.testSent');
    });
  }

  protected disconnect(): Promise<void> {
    return this.run(async () => {
      await this.api.delete('/email');
      this.setEmail(await this.api.get<EmailState>('/email'));
      return this.i18n.t('setup.email.disconnected');
    });
  }
}
