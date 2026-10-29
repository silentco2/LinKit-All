import { Component, computed, inject, input, OnInit, output, signal } from '@angular/core';
import { Api } from '../api';
import { TPipe } from '../i18n';
import { VaultState } from '../types';

/** How many waiting applications were put back in the queue by creating or opening the vault. */
export type VaultReady = { needs_vault: number; vault_locked: number };
type Status = Pick<VaultState, 'initialized' | 'unlocked'>;

let nextId = 0;

/**
 * Wrap content that needs the vault: `<app-vault-gate reason="..." (ready)="...">content</app-vault-gate>`.
 * Not created: one passphrase box (show/hide, strength hint, "remember on this computer"), Create. Created but locked:
 * passphrase + Unlock. Unlocked: the projected content. After a create/unlock it requeues the applications parked for
 * `needs_vault` and `vault_locked` and emits `ready` with the counts. `reason` is an i18n key for one sentence above the
 * form. Call `refresh()` (via a template reference) after something else locks the vault.
 */
@Component({
  selector: 'app-vault-gate',
  imports: [TPipe],
  host: { class: 'block' },
  template: `
    @if (status(); as s) {
      @if (s.unlocked) {
        <ng-content />
      } @else {
        <form class="space-y-3" (submit)="submit($event)">
          @if (reason()) { <p class="text-sm text-slate-700 dark:text-slate-300">{{ reason() | t }}</p> }
          <p class="text-sm text-slate-600 dark:text-slate-400">{{ (s.initialized ? 'gate.locked' : 'gate.create.intro') | t }}</p>
          @if (!s.initialized) {
            <div class="alert alert-info"><strong>{{ 'setup.vault.warnTitle' | t }}</strong> {{ 'setup.vault.warnBody' | t }}</div>
          }
          <div class="max-w-sm">
            <label class="label" [for]="id">{{ 'vault.passphrase' | t }}</label>
            <div class="flex gap-2">
              <input [id]="id" name="passphrase" class="input" [type]="show() ? 'text' : 'password'" [value]="pass()" (input)="pass.set(val($event))"
                     [attr.autocomplete]="s.initialized ? 'current-password' : 'new-password'" [attr.aria-describedby]="s.initialized ? null : id + '-hint'">
              <button type="button" class="btn" [attr.aria-pressed]="show()" (click)="show.set(!show())">{{ (show() ? 'vault.hide' : 'gate.show') | t }}</button>
            </div>
            @if (!s.initialized) { <p class="hint" [id]="id + '-hint'" aria-live="polite">{{ 'gate.strength.' + strength() | t }}</p> }
          </div>
          <label class="flex items-start gap-3 text-sm">
            <input type="checkbox" class="mt-1" [checked]="remember()" (change)="remember.set(checked($event))">
            <span><span class="font-medium">{{ 'setup.vault.remember' | t }}</span>
              <span class="block text-xs text-slate-500">{{ 'setup.vault.rememberHint' | t }}</span></span>
          </label>
          @if (error(); as e) { <p class="text-sm text-rose-700 dark:text-rose-400" role="alert" dir="auto">{{ e }}</p> }
          <button type="submit" class="btn btn-primary" [disabled]="busy() || pass().length < (s.initialized ? 1 : 8)">
            {{ (s.initialized ? 'vault.unlock' : 'gate.create') | t }}
          </button>
        </form>
      }
    } @else if (loadError(); as e) {
      <div class="alert alert-error" role="alert" dir="auto">{{ e }}
        <button type="button" class="btn ms-2" (click)="refresh()">{{ 'welcome.retry' | t }}</button>
      </div>
    }
  `,
})
export class VaultGate implements OnInit {
  private readonly api = inject(Api);
  readonly reason = input('');
  readonly ready = output<VaultReady>();
  protected readonly id = `vg${++nextId}`;
  protected readonly status = signal<Status | null>(null);
  protected readonly loadError = signal('');
  protected readonly pass = signal('');
  protected readonly show = signal(false);
  protected readonly remember = signal(true);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly strength = computed(() => (this.pass().length >= 12 ? 'good' : this.pass().length >= 8 ? 'ok' : 'short'));

  ngOnInit(): void {
    void this.refresh();
  }

  async refresh(): Promise<void> {
    this.loadError.set('');
    try {
      const v = await this.api.get<VaultState>('/vault');
      this.status.set({ initialized: v.initialized, unlocked: v.unlocked });
    } catch (e) {
      this.loadError.set((e as Error).message);
    }
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  protected async submit(e: Event): Promise<void> {
    e.preventDefault();
    const s = this.status();
    if (!s || this.busy() || this.pass().length < (s.initialized ? 1 : 8)) return;
    this.busy.set(true);
    this.error.set('');
    try {
      if (!s.initialized) await this.api.post('/vault/create', { passphrase: this.pass() });
      await this.api.post('/vault/unlock', { passphrase: this.pass(), remember: this.remember() });
      this.pass.set('');
      const [needs_vault, vault_locked] = await Promise.all([this.resume('needs_vault'), this.resume('vault_locked')]);
      this.status.set({ initialized: true, unlocked: true });
      this.ready.emit({ needs_vault, vault_locked });
    } catch (err) {
      this.error.set((err as Error).message);
      void this.refresh(); // created but not unlocked: show the unlock form
    } finally {
      this.busy.set(false);
    }
  }

  /** Put the applications parked for this reason back in the queue; a failure here must not undo the unlock. */
  private async resume(code: string): Promise<number> {
    try {
      return (await this.api.post<{ count: number }>('/actions/retry-code', { code })).count;
    } catch {
      return 0;
    }
  }
}
