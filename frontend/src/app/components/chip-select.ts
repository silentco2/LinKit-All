import { Component, input, output, signal } from '@angular/core';

export interface ChipOption { value: string; label: string; /** A short tip shown on hover, keyboard focus and touch. */ tip?: string }

let nextId = 0;

/**
 * A row of pressable chips (`aria-pressed`) for a short fixed list: Level, Work modes, Posted within.
 * Many can be on, or with `single` exactly one. `(changed)` emits the chosen values in the order of `options`.
 * An option with a `tip` shows it as a tooltip on hover and keyboard focus (`aria-describedby`); a tap shows it for a few seconds.
 * `<app-chip-select [options]="opts" [selected]="cur" [label]="'...'" (changed)="save($event)" />`
 */
@Component({
  selector: 'app-chip-select',
  host: { class: 'block' },
  template: `
    <div class="flex flex-wrap items-center gap-2" role="group" [attr.aria-label]="label() || null">
      @for (o of options(); track o.value) {
        <span class="group relative">
          <button type="button" [attr.aria-pressed]="on(o.value)" [attr.aria-describedby]="o.tip ? tipId(o.value) : null" (click)="toggle(o.value)" (pointerup)="tapped($event, o)"
                  [class]="'rounded-md border px-3 py-1 text-sm max-sm:min-h-10 max-sm:px-4 ' + (on(o.value) ? 'border-brand-500 bg-brand-50 font-medium text-brand-700 dark:bg-slate-800 dark:text-white' : 'border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400')">{{ o.label }}</button>
          @if (o.tip) {
            <span role="tooltip" [id]="tipId(o.value)" class="pointer-events-none absolute start-0 top-full z-30 mt-1 hidden w-56 max-w-[80vw] rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-normal text-white shadow-lg group-hover:block group-has-[:focus-visible]:block dark:bg-slate-700" [class.!block]="touched() === o.value">{{ o.tip }}</span>
          }
        </span>
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
  private readonly uid = ++nextId;
  /** Chip whose tip a touch showed: touch has no hover and no visible focus. */
  protected readonly touched = signal<string | null>(null);
  private hide?: ReturnType<typeof setTimeout>;

  protected tapped(e: PointerEvent, o: ChipOption): void {
    if (e.pointerType === 'mouse' || !o.tip) return;
    this.touched.set(o.value);
    clearTimeout(this.hide);
    this.hide = setTimeout(() => this.touched.set(null), 4000);
  }

  protected tipId(v: string): string {
    return `chip-tip-${this.uid}-${v}`;
  }

  protected on(v: string): boolean {
    return this.selected().includes(v);
  }

  protected toggle(v: string): void {
    const cur = this.selected();
    this.changed.emit(this.options().map((o) => o.value).filter((x) => (x === v ? !cur.includes(x) || this.single() : !this.single() && cur.includes(x))));
  }
}
