import { Component, computed, input, model, output, signal } from '@angular/core';

export interface ComboOption { key: string; label: string }

/**
 * A text box with a dropdown of options (ARIA combobox + listbox). It only shows what the parent gives it:
 * `[(value)]` is the text, `[options]` the list. Keys: arrows move, Enter picks the marked option (or submits the text),
 * Esc closes, Backspace in an empty box tells the parent. Used by the tag, place and phone-code boxes.
 */
@Component({
  selector: 'app-combo',
  host: { class: 'relative block' },
  template: `
    <input #box [id]="inputId()" class="input" type="text" role="combobox" autocomplete="off" aria-autocomplete="list"
           [attr.aria-expanded]="isOpen()" [attr.aria-controls]="isOpen() ? listId() : null" [attr.aria-activedescendant]="activeId()"
           [attr.aria-label]="label() || null" [attr.dir]="dir()" [attr.inputmode]="inputMode() || null" [placeholder]="placeholder()" [value]="value()"
           (input)="typed($event)" (keydown)="key($event)" (focus)="onFocus(box)" (blur)="onBlur()">
    @if (isOpen()) {
      <ul [id]="listId()" role="listbox" [class]="'absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-slate-300 bg-white py-1 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900 ' + panelClass()">
        @for (o of options(); track o.key; let i = $index) {
          <li role="option" [id]="listId() + '-' + i" [attr.aria-selected]="i === active()" dir="auto"
              class="cursor-pointer px-3 py-1.5 text-slate-800 hover:bg-slate-100 aria-selected:bg-brand-100 dark:text-slate-200 dark:hover:bg-slate-800 dark:aria-selected:bg-slate-700"
              (mousedown)="$event.preventDefault(); choose(o)">{{ o.label }}</li>
        }
      </ul>
    }
  `,
})
export class Combo {
  readonly inputId = input('');
  readonly value = model('');
  readonly options = input<ComboOption[]>([]);
  readonly placeholder = input('');
  /** The accessible name when no <label> points at the box. */
  readonly label = input('');
  readonly dir = input<'auto' | 'ltr'>('auto');
  readonly inputMode = input('');
  readonly panelClass = input('');

  readonly picked = output<ComboOption>();
  /** Enter with no option marked. */
  readonly submitted = output<string>();
  readonly blurred = output<string>();
  readonly focused = output<void>();
  readonly backspaceEmpty = output<void>();

  private static n = 0;
  private readonly uid = ++Combo.n;
  protected readonly listId = computed(() => `${this.inputId() || 'combo'}-list-${this.uid}`);
  protected readonly active = signal(-1);
  private readonly focus = signal(false);
  private readonly dismissed = signal(false);
  protected readonly isOpen = computed(() => this.focus() && !this.dismissed() && this.options().length > 0);
  protected readonly activeId = computed(() => (this.isOpen() && this.active() >= 0 ? `${this.listId()}-${this.active()}` : null));

  protected typed(e: Event): void {
    this.value.set((e.target as HTMLInputElement).value);
    this.active.set(-1);
    this.dismissed.set(false);
  }

  protected onFocus(box: HTMLInputElement): void {
    this.focus.set(true);
    this.dismissed.set(false);
    box.select();
    this.focused.emit();
  }

  protected onBlur(): void {
    this.focus.set(false);
    this.active.set(-1);
    this.blurred.emit(this.value());
  }

  protected choose(o: ComboOption): void {
    this.active.set(-1);
    this.picked.emit(o);
  }

  protected key(e: KeyboardEvent): void {
    const n = this.options().length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!n) return;
      e.preventDefault();
      this.dismissed.set(false);
      this.active.update((a) => (e.key === 'ArrowDown' ? (a + 1) % n : (a <= 0 ? n : a) - 1));
      document.getElementById(`${this.listId()}-${this.active()}`)?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const o = this.isOpen() ? this.options()[this.active()] : undefined;
      if (o) this.choose(o);
      else this.submitted.emit(this.value());
    } else if (e.key === 'Escape' && this.isOpen()) {
      e.preventDefault();
      this.dismissed.set(true);
    } else if (e.key === 'Backspace' && !this.value()) {
      this.backspaceEmpty.emit();
    }
  }
}
