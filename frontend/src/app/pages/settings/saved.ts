import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, inject, input } from '@angular/core';
import { TPipe } from '../../i18n';
import { FieldState, SettingsStore } from './store';

/** "Saving…", "✓ Saved" (fades after about 2 s) or "Not saved" for one store key. The live region is always in the page. */
@Component({
  selector: 'app-saved',
  imports: [TPipe],
  host: { class: 'text-xs' },
  template: `
    <span aria-live="polite" role="status">
      @switch (state()?.state) {
        @case ('saving') { <span class="text-slate-500 dark:text-slate-400">{{ 'settings.saving' | t }}</span> }
        @case ('saved') { <span class="text-emerald-700 dark:text-emerald-400"><span aria-hidden="true">✓ </span>{{ 'settings.saved' | t }}</span> }
        @case ('error') { <span class="text-rose-700 dark:text-rose-400">{{ 'settings.notSaved' | t }}</span> }
      }
    </span>
  `,
})
export class Saved {
  private readonly store = inject(SettingsStore);
  readonly field = input.required<string>();
  protected readonly state = computed((): FieldState | undefined => this.store.fields()[this.field()]);
}

/**
 * Label + control + the indicator + the inline error under the control + hint.
 * `<app-field key="filters.title_exclude" for="exc" [label]="..."><textarea id="exc" ...></textarea></app-field>`
 * Leave `for` out for a group of buttons (the label is then plain text); `check` puts a checkbox before its label.
 */
@Component({
  selector: 'app-field',
  imports: [NgTemplateOutlet, Saved],
  host: { class: 'block' },
  template: `
    <ng-template #control><ng-content /></ng-template>
    @if (check()) {
      <div class="flex items-start gap-2">
        <ng-container [ngTemplateOutlet]="control" />
        <label class="text-sm" [for]="forId()">{{ label() }}</label>
        <app-saved class="ms-auto" [field]="key()" />
      </div>
    } @else {
      <div class="flex items-baseline justify-between gap-2">
        @if (forId()) { <label class="label" [for]="forId()">{{ label() }}</label> } @else { <p class="label">{{ label() }}</p> }
        <app-saved class="mb-1" [field]="key()" />
      </div>
      <ng-container [ngTemplateOutlet]="control" />
    }
    @if (error(); as e) { <p class="mt-1 text-xs text-rose-700 dark:text-rose-400" role="alert" dir="auto">{{ e }}</p> }
    @if (hint()) { <p class="hint" dir="auto">{{ hint() }}</p> }
  `,
})
export class Field {
  private readonly store = inject(SettingsStore);
  readonly key = input.required<string>();
  readonly label = input.required<string>();
  readonly forId = input('', { alias: 'for' });
  readonly hint = input('');
  readonly check = input(false);
  protected readonly error = computed(() => this.store.fields()[this.key()]?.error ?? '');
}
