import { Component, input, output } from '@angular/core';

export interface ChipOption { value: string; label: string }

/**
 * A row of pressable chips (`aria-pressed`) for a short fixed list: Level, Work modes, Posted within.
 * Many can be on, or with `single` exactly one. `(changed)` emits the chosen values in the order of `options`.
 * `<app-chip-select [options]="opts" [selected]="cur" [label]="'...'" (changed)="save($event)" />`
 */
@Component({
  selector: 'app-chip-select',
  host: { class: 'block' },
  template: `
    <div class="flex flex-wrap items-center gap-2" role="group" [attr.aria-label]="label() || null">
      @for (o of options(); track o.value) {
        <button type="button" [attr.aria-pressed]="on(o.value)" (click)="toggle(o.value)"
                [class]="'rounded-full border px-3 py-1 text-sm max-sm:min-h-10 max-sm:px-4 ' + (on(o.value) ? 'border-brand-500 bg-brand-50 font-medium text-brand-700 dark:bg-slate-800 dark:text-white' : 'border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400')">{{ o.label }}</button>
      }
    </div>
  `,
})
export class ChipSelect {
  readonly options = input<ChipOption[]>([]);
  readonly selected = input<readonly string[]>([]);
  readonly single = input(false);
  /** Accessible name of the group (use it when the visible label is not a <label>). */
  readonly label = input('');
  readonly changed = output<string[]>();

  protected on(v: string): boolean {
    return this.selected().includes(v);
  }

  protected toggle(v: string): void {
    const cur = this.selected();
    this.changed.emit(this.options().map((o) => o.value).filter((x) => (x === v ? !cur.includes(x) || this.single() : !this.single() && cur.includes(x))));
  }
}
