import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { fmtNum, labelOr, localeOf } from '../locale';
import { VaultEntry, VaultState } from '../types';

@Component({
  selector: 'app-vault',
  imports: [FormsModule, RouterLink, TPipe],
  template: `
    <h1>{{ 'vault.title' | t }}</h1>
    <p class="mt-1 max-w-3xl text-sm text-slate-500">{{ 'vault.intro' | t }}</p>

    @if (error(); as err) { <div class="alert alert-error mt-4 max-w-4xl" role="alert" dir="auto">{{ err }}</div> }
    @if (notice(); as n) { <div class="alert alert-ok mt-4 max-w-4xl" role="status">{{ n | t }}</div> }

    @if (!state()) {
      <p class="mt-6 text-sm text-slate-500">{{ 'common.loading' | t }}</p>
    } @else if (!state()!.initialized) {
      <div class="card mt-5 max-w-3xl text-sm">
        {{ 'vault.none.a' | t }}<a routerLink="/setup">{{ 'vault.none.link' | t }}</a>{{ 'vault.none.b' | t }}
      </div>
    } @else if (!state()!.unlocked) {
      <form class="card mt-5 max-w-md space-y-4" (ngSubmit)="unlock()">
        <h2>{{ 'vault.locked' | t }}</h2>
        <div>
          <label class="label" for="unlock-pass">{{ 'vault.passphrase' | t }}</label>
          <input id="unlock-pass" type="password" class="input" name="pass" [(ngModel)]="pass" autocomplete="current-password">
        </div>
        <label class="flex items-start gap-3 text-sm">
          <input type="checkbox" class="mt-1" name="remember" [(ngModel)]="remember">
          <span><span class="font-medium">{{ 'vault.remember' | t }}</span>
            <span class="block text-xs text-slate-500">{{ 'vault.rememberHint' | t }}</span></span>
        </label>
        <button type="submit" class="btn btn-primary" [disabled]="busy() || !pass">{{ 'vault.unlock' | t }}</button>
      </form>
    } @else {
      <div class="mt-5 flex max-w-4xl flex-wrap items-center gap-3">
        <span class="badge tier-high">{{ 'vault.unlocked' | t }}</span>
        <span class="text-sm text-slate-500">{{ (state()!.entries.length === 1 ? 'vault.entries.one' : 'vault.entries.other') | t: { n: num(state()!.entries.length) } }}</span>
        <span class="ms-auto flex gap-2">
          <button type="button" class="btn" [disabled]="busy()" (click)="toggleExport()" [attr.aria-expanded]="exporting()">{{ 'vault.export' | t }}</button>
          <button type="button" class="btn" [disabled]="busy()" (click)="lock()">{{ 'vault.lock' | t }}</button>
        </span>
      </div>

      @if (exporting()) {
        <form class="card mt-4 max-w-4xl space-y-3" (ngSubmit)="exportAll()">
          <div class="alert alert-error" role="alert">
            <strong>{{ 'vault.export.warnTitle' | t }}</strong> {{ 'vault.export.warnBody' | t }}
          </div>
          <label class="label" for="export-pass">{{ 'vault.passphrase' | t }}</label>
          <input id="export-pass" type="password" class="input max-w-sm" name="pass" [(ngModel)]="exportPass" autocomplete="current-password">
          <div class="flex gap-3">
            <button type="submit" class="btn btn-primary" [disabled]="busy() || !exportPass">{{ 'vault.export.download' | t }}</button>
            <button type="button" class="btn" (click)="toggleExport()">{{ 'vault.cancel' | t }}</button>
          </div>
        </form>
      }

      <div class="card mt-4 max-w-4xl p-0">
        @for (e of state()!.entries; track e.id; let first = $first) {
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
              <form class="mt-3 flex flex-wrap items-end gap-3" (ngSubmit)="reveal(e)">
                <div class="w-full sm:w-64">
                  <label class="label" [attr.for]="'rp' + e.id">{{ 'vault.passphrase' | t }}</label>
                  <input [id]="'rp' + e.id" type="password" class="input" name="pass" [(ngModel)]="revealPass" autocomplete="current-password">
                </div>
                <button type="submit" class="btn btn-primary" [disabled]="busy() || !revealPass">{{ 'vault.showSecret' | t }}</button>
                <button type="button" class="btn" (click)="hide()">{{ 'vault.cancel' | t }}</button>
              </form>
            }
            @if (secret()?.id === e.id) {
              <p class="mt-3 select-all break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800" dir="ltr" aria-live="polite">{{ secret()!.value }}</p>
            }
          </div>
        } @empty {
          <p class="p-8 text-center text-sm text-slate-500">{{ 'vault.empty' | t }}</p>
        }
      </div>
    }
  `,
})
export class VaultPage implements OnInit {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly state = signal<VaultState | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly notice = signal(''); // an i18n key, so it follows the language
  protected readonly asking = signal<number | null>(null);
  protected readonly secret = signal<{ id: number; value: string } | null>(null);
  protected readonly exporting = signal(false);
  protected pass = '';
  protected remember = true;
  protected revealPass = '';
  protected exportPass = '';

  ngOnInit(): Promise<void> {
    return this.run(async () => undefined);
  }

  num = (n: number): string => fmtNum(this.loc(), n);
  kindLabel = (kind: string): string => labelOr(this.i18n, 'vault.kind.', kind);
  when = (iso: string): string => new Date(iso).toLocaleString(this.loc());

  unlock(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/vault/unlock', { passphrase: this.pass, remember: this.remember });
      this.pass = '';
    });
  }

  lock(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/vault/lock');
      this.hide();
      this.exporting.set(false);
    });
  }

  askReveal(e: VaultEntry): void {
    this.hide();
    this.asking.set(e.id);
  }

  hide(): void {
    this.secret.set(null);
    this.asking.set(null);
    this.revealPass = '';
  }

  reveal(e: VaultEntry): Promise<void> {
    return this.run(async () => {
      const r = await this.api.post<{ secret: string }>(`/vault/entries/${e.id}/reveal`, { passphrase: this.revealPass });
      this.hide();
      this.secret.set({ id: e.id, value: r.secret });
    });
  }

  async remove(e: VaultEntry): Promise<void> {
    if (!confirm(this.i18n.t('vault.confirmDelete', { user: e.username, site: e.site }))) return;
    await this.run(async () => {
      await this.api.delete(`/vault/entries/${e.id}`);
      if (this.secret()?.id === e.id || this.asking() === e.id) this.hide();
    });
  }

  toggleExport(): void {
    this.exporting.update((v) => !v);
    this.exportPass = '';
  }

  exportAll(): Promise<void> {
    return this.run(async () => {
      const blob = await this.api.postForBlob('/vault/export', { passphrase: this.exportPass });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'linkit-vault-export.json';
      a.click();
      URL.revokeObjectURL(url);
      this.exportPass = '';
      this.exporting.set(false);
      this.notice.set('vault.exported');
    });
  }

  /** Run an action, then reload the vault state. Errors show in the banner. */
  private async run(fn: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    this.notice.set('');
    try {
      await fn();
      this.state.set(await this.api.get<VaultState>('/vault'));
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : String(err));
      if (!this.state()) this.state.set({ initialized: false, unlocked: false, entries: [] });
    } finally {
      this.busy.set(false);
    }
  }
}
