import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { ApiKeyProvider } from '../types';

/**
 * One provider's API-key form (save / remove / "get a free key"). The vault must be unlocked: put it inside an
 * <app-vault-gate> or show it only when unlocked. `changed` emits the fresh provider list after a save or remove.
 * Secret boxes start empty (the server only sends a masked hint); a configured provider keeps blank secrets.
 */
@Component({
  selector: 'app-key-form',
  imports: [TPipe],
  host: { class: 'block' },
  template: `
    <form class="space-y-3" (submit)="save($event)">
      @for (f of provider().fields; track f.name) {
        <div>
          <label class="label" [for]="uid + f.name">{{ f.label }}</label>
          <input [id]="uid + f.name" dir="ltr" class="input" [name]="f.name" [type]="f.secret ? 'password' : 'text'" autocomplete="off"
                 [value]="v(f.name)" (input)="set(f.name, $event)"
                 [placeholder]="provider().configured && f.secret ? (provider().current[f.name] ?? '') : ''">
          @if (provider().configured && f.secret) { <p class="hint">{{ 'setup.keys.keepHint' | t }}</p> }
        </div>
      }
      @if (note(); as n) { <p class="text-sm" [class]="n.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'" [attr.role]="n.ok ? 'status' : 'alert'" dir="auto">{{ n.text }}</p> }
      <div class="flex flex-wrap items-center gap-3">
        <button type="submit" class="btn btn-primary" [disabled]="busy() || !ready()">{{ 'setup.keys.save' | t }}</button>
        @if (provider().configured) { <button type="button" class="btn" [disabled]="busy()" (click)="remove()">{{ 'setup.keys.remove' | t }}</button> }
        <a class="text-sm underline" [href]="provider().signup_url" target="_blank" rel="noopener">{{ 'setup.keys.signup' | t }}</a>
      </div>
    </form>
  `,
})
export class KeyForm {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  readonly provider = input.required<ApiKeyProvider>();
  readonly changed = output<ApiKeyProvider[]>();
  protected readonly uid = `kf-${Math.random().toString(36).slice(2, 8)}-`;
  protected readonly vals = signal<Record<string, string>>({});
  protected readonly busy = signal(false);
  protected readonly note = signal<{ ok: boolean; text: string } | null>(null);
  protected readonly ready = computed(() => {
    const p = this.provider();
    return p.fields.every((f) => !!this.v(f.name).trim() || (p.configured && f.secret));
  });

  constructor() {
    effect(() => {
      const p = this.provider();
      this.vals.set(Object.fromEntries(p.fields.map((f) => [f.name, f.secret ? '' : (p.current[f.name] ?? '')])));
    });
  }

  /** The typed text of one box; empty until the effect below has filled the boxes. */
  protected v(name: string): string {
    return this.vals()[name] ?? '';
  }

  protected set(name: string, e: Event): void {
    this.vals.update((v) => ({ ...v, [name]: (e.target as HTMLInputElement).value }));
  }

  protected async save(e: Event): Promise<void> {
    e.preventDefault();
    const p = this.provider();
    await this.run(async () => {
      this.changed.emit(await this.api.put<ApiKeyProvider[]>(`/keys/${p.name}`, this.vals()));
      return this.i18n.t('setup.keys.saved', { name: p.label });
    });
  }

  protected remove(): Promise<void> {
    const p = this.provider();
    return this.run(async () => {
      await this.api.delete(`/keys/${p.name}`);
      this.changed.emit(await this.api.get<ApiKeyProvider[]>('/keys'));
      return this.i18n.t('setup.keys.removed', { name: p.label });
    });
  }

  private async run(action: () => Promise<string>): Promise<void> {
    this.busy.set(true);
    this.note.set(null);
    try {
      this.note.set({ ok: true, text: await action() });
    } catch (err) {
      this.note.set({ ok: false, text: (err as Error).message });
    } finally {
      this.busy.set(false);
    }
  }
}
