import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { VaultEntry, VaultState } from '../types';

@Component({
  selector: 'app-vault',
  imports: [FormsModule, RouterLink],
  template: `
    <h1>Vault</h1>
    <p class="mt-1 max-w-3xl text-sm text-slate-500">
      Site passwords and your email app password, encrypted on this computer. The passphrase can't be recovered.
    </p>

    @if (error(); as err) { <div class="alert alert-error mt-4 max-w-4xl" role="alert">{{ err }}</div> }
    @if (notice(); as n) { <div class="alert alert-ok mt-4 max-w-4xl" role="status">{{ n }}</div> }

    @if (!state()) {
      <p class="mt-6 text-sm text-slate-500">Loading…</p>
    } @else if (!state()!.initialized) {
      <div class="card mt-5 max-w-3xl text-sm">
        No vault yet. Create one in the <a routerLink="/setup">setup wizard</a> (Vault step).
      </div>
    } @else if (!state()!.unlocked) {
      <form class="card mt-5 max-w-md space-y-4" (ngSubmit)="unlock()">
        <h2>Locked</h2>
        <div>
          <label class="label" for="unlock-pass">Passphrase</label>
          <input id="unlock-pass" type="password" class="input" name="pass" [(ngModel)]="pass" autocomplete="current-password">
        </div>
        <label class="flex items-start gap-3 text-sm">
          <input type="checkbox" class="mt-1" name="remember" [(ngModel)]="remember">
          <span><span class="font-medium">Remember on this computer</span>
            <span class="block text-xs text-slate-500">Opens by itself next time. Turn off on a shared computer.</span></span>
        </label>
        <button type="submit" class="btn btn-primary" [disabled]="busy() || !pass">Unlock</button>
      </form>
    } @else {
      <div class="mt-5 flex max-w-4xl flex-wrap items-center gap-3">
        <span class="badge tier-high">Unlocked</span>
        <span class="text-sm text-slate-500">{{ state()!.entries.length }} {{ state()!.entries.length === 1 ? 'entry' : 'entries' }}</span>
        <span class="ml-auto flex gap-2">
          <button type="button" class="btn" [disabled]="busy()" (click)="toggleExport()" [attr.aria-expanded]="exporting()">Export</button>
          <button type="button" class="btn" [disabled]="busy()" (click)="lock()">Lock</button>
        </span>
      </div>

      @if (exporting()) {
        <form class="card mt-4 max-w-4xl space-y-3" (ngSubmit)="exportAll()">
          <div class="alert alert-error" role="alert">
            <strong>The export is not encrypted.</strong> It lists every password in plain text. Keep it somewhere safe and delete it when you're done.
          </div>
          <label class="label" for="export-pass">Passphrase</label>
          <input id="export-pass" type="password" class="input max-w-sm" name="pass" [(ngModel)]="exportPass" autocomplete="current-password">
          <div class="flex gap-3">
            <button type="submit" class="btn btn-primary" [disabled]="busy() || !exportPass">Download export</button>
            <button type="button" class="btn" (click)="toggleExport()">Cancel</button>
          </div>
        </form>
      }

      <div class="card mt-4 max-w-4xl p-0">
        @for (e of state()!.entries; track e.id; let first = $first) {
          <div class="px-4 py-3" [class.border-t]="!first" [class.border-slate-100]="!first" [class.dark:border-slate-800]="!first">
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span class="badge alert-info">{{ e.kind }}</span>
              <span class="min-w-0 flex-1 break-words text-sm font-medium" dir="auto">{{ e.site }}</span>
              <span class="min-w-0 break-all text-sm text-slate-600 dark:text-slate-300" dir="auto">{{ e.username }}</span>
              <span class="text-xs text-slate-500">Updated {{ when(e.updated_at) }}</span>
              <span class="flex gap-2">
                @if (secret()?.id === e.id) {
                  <button type="button" class="btn" (click)="hide()">Hide</button>
                } @else {
                  <button type="button" class="btn" [disabled]="busy()" (click)="askReveal(e)" [attr.aria-expanded]="asking() === e.id">Reveal</button>
                }
                <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="remove(e)">Delete</button>
              </span>
            </div>
            @if (asking() === e.id) {
              <form class="mt-3 flex flex-wrap items-end gap-3" (ngSubmit)="reveal(e)">
                <div>
                  <label class="label" [attr.for]="'rp' + e.id">Passphrase</label>
                  <input [id]="'rp' + e.id" type="password" class="input w-64" name="pass" [(ngModel)]="revealPass" autocomplete="current-password">
                </div>
                <button type="submit" class="btn btn-primary" [disabled]="busy() || !revealPass">Show secret</button>
                <button type="button" class="btn" (click)="hide()">Cancel</button>
              </form>
            }
            @if (secret()?.id === e.id) {
              <p class="mt-3 select-all break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800" aria-live="polite">{{ secret()!.value }}</p>
            }
          </div>
        } @empty {
          <p class="p-8 text-center text-sm text-slate-500">
            Nothing saved yet. Passwords appear here when LinKit creates an account for you on a job site.
          </p>
        }
      </div>
    }
  `,
})
export class VaultPage implements OnInit {
  private readonly api = inject(Api);
  protected readonly state = signal<VaultState | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly notice = signal('');
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

  when = (iso: string): string => new Date(iso).toLocaleString();

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
    if (!confirm(`Delete the saved password for ${e.username} on ${e.site}? This can't be undone.`)) return;
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
      this.notice.set('Export downloaded. It is not encrypted: delete it when you are done.');
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
