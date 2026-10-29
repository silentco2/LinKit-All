import { Component, computed, inject, OnInit, signal, viewChild } from '@angular/core';
import { Api } from '../../api';
import { GmailConnect, GmailConnected } from '../../components/gmail-connect';
import { KeyForm } from '../../components/key-form';
import { VaultGate, VaultReady } from '../../components/vault-gate';
import { I18n, TPipe } from '../../i18n';
import { labelOr, localeOf } from '../../locale';
import { ApiKeyProvider, VaultEntry, VaultState } from '../../types';
import { Field } from './saved';
import { SettingsStore } from './store';

type Note = { ok: boolean; text: string };

/** Settings > Accounts & email: saved passwords (the vault), Gmail for sign-up codes and email applications, API keys. */
@Component({
  selector: 'app-settings-accounts',
  imports: [Field, GmailConnect, KeyForm, VaultGate, TPipe],
  template: `
    <div class="space-y-6">
      @if (note(); as n) {
        <div class="alert" [class.alert-ok]="n.ok" [class.alert-error]="!n.ok" [attr.role]="n.ok ? 'status' : 'alert'" dir="auto">{{ n.text }}</div>
      }

      <section class="card space-y-4">
        <h2>{{ 'settings.acc.vault' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'vault.intro' | t }}</p>
        <app-vault-gate reason="settings.acc.vaultWhy" (ready)="onReady($event)">
          <div class="space-y-4">
            <div class="flex flex-wrap items-center gap-3">
              <span class="badge tier-high">{{ 'vault.unlocked' | t }}</span>
              <span class="text-sm text-slate-500">{{ plural('vault.entries', entries().length) }}</span>
              <span class="ms-auto flex gap-2">
                <button type="button" class="btn" [disabled]="busy()" (click)="toggleExport()" [attr.aria-expanded]="exporting()">{{ 'vault.export' | t }}</button>
                <button type="button" class="btn" [disabled]="busy()" (click)="lock()">{{ 'vault.lock' | t }}</button>
              </span>
            </div>

            @if (exporting()) {
              <form class="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700" (submit)="exportAll($event)">
                <div class="alert alert-error" role="alert"><strong>{{ 'vault.export.warnTitle' | t }}</strong> {{ 'vault.export.warnBody' | t }}</div>
                <label class="label" for="export-pass">{{ 'vault.passphrase' | t }}</label>
                <input id="export-pass" type="password" class="input max-w-sm" name="passphrase" autocomplete="current-password" [value]="exportPass()" (input)="exportPass.set(val($event))">
                <div class="flex gap-3">
                  <button type="submit" class="btn btn-primary" [disabled]="busy() || !exportPass()">{{ 'vault.export.download' | t }}</button>
                  <button type="button" class="btn" (click)="toggleExport()">{{ 'vault.cancel' | t }}</button>
                </div>
              </form>
            }

            <div class="rounded-lg border border-slate-200 dark:border-slate-700">
              @for (e of entries(); track e.id; let first = $first) {
                <div class="px-4 py-3" [class.border-t]="!first" [class.border-slate-100]="!first" [class.dark:border-slate-800]="!first">
                  <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
                    <span class="badge alert-info">{{ kindLabel(e.kind) }}</span>
                    <span class="min-w-0 flex-1 break-words text-sm font-medium" dir="auto">{{ e.site }}</span>
                    <span class="min-w-0 break-all text-sm text-slate-600 dark:text-slate-300" dir="auto">{{ e.username }}</span>
                    <span class="text-xs text-slate-500">{{ 'vault.updated' | t: { date: when(e.updated_at) } }}</span>
                    <span class="flex gap-2">
                      @if (secret()?.id === e.id) {
                        <button type="button" class="btn" (click)="hide()">{{ 'vault.hide' | t }}</button>
                      } @else {
                        <button type="button" class="btn" [disabled]="busy()" (click)="askReveal(e)" [attr.aria-expanded]="asking() === e.id">{{ 'vault.reveal' | t }}</button>
                      }
                      <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="remove(e)">{{ 'vault.delete' | t }}</button>
                    </span>
                  </div>
                  @if (asking() === e.id) {
                    <form class="mt-3 flex flex-wrap items-end gap-3" (submit)="reveal($event, e)">
                      <div class="w-full sm:w-64">
                        <label class="label" [attr.for]="'rp' + e.id">{{ 'vault.passphrase' | t }}</label>
                        <input [id]="'rp' + e.id" type="password" class="input" name="passphrase" autocomplete="current-password" [value]="revealPass()" (input)="revealPass.set(val($event))">
                      </div>
                      <button type="submit" class="btn btn-primary" [disabled]="busy() || !revealPass()">{{ 'vault.showSecret' | t }}</button>
                      <button type="button" class="btn" (click)="hide()">{{ 'vault.cancel' | t }}</button>
                    </form>
                  }
                  @if (secret()?.id === e.id) {
                    <p class="mt-3 select-all break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800" dir="ltr" aria-live="polite">{{ secret()!.value }}</p>
                  }
                </div>
              } @empty {
                <p class="p-6 text-center text-sm text-slate-500">{{ 'vault.empty' | t }}</p>
              }
            </div>
          </div>
        </app-vault-gate>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.acc.gmail' | t }} <span class="text-sm font-normal text-slate-500">({{ 'common.optional' | t }})</span></h2>
        <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.email.intro' | t }}</p>
        <app-gmail-connect [unlocked]="unlocked()" (connected)="onGmail($event)" />
        @if (unlocked()) {
          <div class="max-w-xs border-t border-slate-100 pt-4 dark:border-slate-800">
            <app-field key="apply.email_daily_cap" for="e-cap" [label]="'setup.email.cap' | t" [hint]="'setup.email.capHint' | t">
              <input id="e-cap" type="number" min="1" max="100" class="input" [value]="store.cfg.apply.email_daily_cap" (change)="store.update('apply.email_daily_cap', num2($event))">
            </app-field>
          </div>
        }
      </section>

      <section class="card space-y-4">
        <h2>{{ 'setup.keys.title' | t }} <span class="text-sm font-normal text-slate-500">({{ 'common.optional' | t }})</span></h2>
        <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.keys.intro' | t }}</p>
        @if (!unlocked()) {
          <div class="alert alert-info" role="status">{{ 'settings.acc.needVaultKeys' | t }}</div>
        } @else {
          <div class="grid gap-4 lg:grid-cols-2">
            @for (p of keys(); track p.name) {
              <div class="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="font-semibold">{{ p.label }}</h3>
                  @if (p.configured) { <span class="badge tier-high">{{ 'setup.keys.configured' | t }}</span> }
                </div>
                <p class="hint" dir="auto">{{ p.note }}</p>
                <app-key-form [provider]="p" (changed)="keys.set($event)" />
              </div>
            }
          </div>
        }
      </section>
    </div>
  `,
})
export class AccountsSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly gate = viewChild(VaultGate);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly vault = signal<VaultState | null>(null);
  protected readonly keys = signal<ApiKeyProvider[]>([]);
  protected readonly note = signal<Note | null>(null);
  protected readonly busy = signal(false);
  protected readonly unlocked = computed(() => !!this.vault()?.unlocked);
  protected readonly entries = computed(() => this.vault()?.entries ?? []);

  protected readonly asking = signal<number | null>(null);
  protected readonly secret = signal<{ id: number; value: string } | null>(null);
  protected readonly exporting = signal(false);
  protected readonly revealPass = signal('');
  protected readonly exportPass = signal('');

  ngOnInit(): void {
    void this.loadAll();
  }

  protected plural = (base: string, n: number): string => this.i18n.plural(base, n);
  protected kindLabel = (kind: string): string => labelOr(this.i18n, 'vault.kind.', kind);
  protected when = (iso: string): string => new Date(iso).toLocaleString(this.loc());

  protected val(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  /** An empty box is NaN, which the server rejects with a message for this field. */
  protected num2(e: Event): number {
    const box = e.target as HTMLInputElement;
    return box.value.trim() === '' ? NaN : box.valueAsNumber;
  }

  private async loadAll(): Promise<void> {
    await Promise.all([
      this.api.get<VaultState>('/vault').then((v) => this.vault.set(v)),
      this.api.get<ApiKeyProvider[]>('/keys').then((k) => this.keys.set(k)),
    ]).catch((e) => this.note.set({ ok: false, text: (e as Error).message }));
  }

  /** The vault was just created or opened: show what it unlocks, and say how many parked applications were requeued. */
  protected onReady(r: VaultReady): void {
    const n = r.needs_vault + r.vault_locked;
    this.note.set(n > 0 ? { ok: true, text: this.waiting(n) } : null);
    void this.loadAll();
  }

  private waiting(n: number): string {
    return this.i18n.plural('settings.acc.waiting', n);
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

  // ---- saved passwords ----------------------------------------------------------------------

  protected lock(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/vault/lock');
      this.hide();
      this.exporting.set(false);
      await this.loadAll();
      await this.gate()?.refresh();
    });
  }

  protected askReveal(e: VaultEntry): void {
    this.hide();
    this.asking.set(e.id);
  }

  protected hide(): void {
    this.secret.set(null);
    this.asking.set(null);
    this.revealPass.set('');
  }

  protected reveal(ev: Event, e: VaultEntry): Promise<void> {
    ev.preventDefault();
    return this.run(async () => {
      const r = await this.api.post<{ secret: string }>(`/vault/entries/${e.id}/reveal`, { passphrase: this.revealPass() });
      this.hide();
      this.secret.set({ id: e.id, value: r.secret });
    });
  }

  protected async remove(e: VaultEntry): Promise<void> {
    if (!confirm(this.i18n.t('vault.confirmDelete', { user: e.username, site: e.site }))) return;
    await this.run(async () => {
      await this.api.delete(`/vault/entries/${e.id}`);
      if (this.secret()?.id === e.id || this.asking() === e.id) this.hide();
      this.vault.set(await this.api.get<VaultState>('/vault'));
    });
  }

  protected toggleExport(): void {
    this.exporting.update((v) => !v);
    this.exportPass.set('');
  }

  protected exportAll(ev: Event): Promise<void> {
    ev.preventDefault();
    return this.run(async () => {
      const blob = await this.api.postForBlob('/vault/export', { passphrase: this.exportPass() });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'linkit-vault-export.json';
      a.click();
      URL.revokeObjectURL(url);
      this.exportPass.set('');
      this.exporting.set(false);
      return this.i18n.t('vault.exported');
    });
  }

  // ---- Gmail ----------------------------------------------------------------------------------

  /** The component saved the address and host in the search config: keep our copy the same so a later autosave does not undo it. */
  protected onGmail(r: GmailConnected): void {
    this.store.cfg.email.imap_host = r.email.imap_host;
    this.store.cfg.email.imap_user = r.email.imap_user;
  }
}
