import { Component, computed, inject, input, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';

let nextId = 0;

/**
 * "Your data stays on this computer, except:" and the link that opens the list of what leaves it, and to whom.
 * `[lead]="false"` shows the link alone (where the sentence is already on the page).
 */
@Component({
  selector: 'app-privacy',
  imports: [TPipe],
  template: `
    <p class="text-sm text-slate-600 dark:text-slate-400">
      @if (lead()) { {{ 'privacy.lead' | t }} }
      <button type="button" class="linkish" [attr.aria-expanded]="open()" [attr.aria-controls]="panel" (click)="toggle()">{{ 'privacy.link' | t }}</button>
    </p>
    @if (open()) {
      <div [id]="panel" class="alert alert-info mt-2" role="region" [attr.aria-label]="'privacy.link' | t">
        <ul class="list-disc space-y-1.5 ps-5 text-sm">
          <li>{{ (provider() ? 'privacy.ai' : 'privacy.aiNone') | t: { provider: name() } }}</li>
          <li>{{ 'privacy.sites' | t }}</li>
          <li>{{ 'privacy.employers' | t }}</li>
          <li>{{ 'privacy.fx' | t }}</li>
          <li>{{ 'privacy.nothing' | t }}</li>
        </ul>
      </div>
    }
  `,
})
export class Privacy {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  readonly lead = input(true);
  protected readonly panel = `privacy-panel-${nextId++}`;
  protected readonly open = signal(false);
  protected readonly provider = signal<string | null>(null);
  protected readonly name = computed(() => this.i18n.provider(this.provider()));

  protected toggle(): void {
    this.open.update((o) => !o);
    if (this.open()) {
      this.api.get<{ provider: string | null }>('/ai').then((r) => this.provider.set(r.provider)).catch(() => undefined);
    }
  }
}
