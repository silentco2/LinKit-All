import { Component, ElementRef, inject, input, output, signal } from '@angular/core';
import { TPipe } from '../i18n';

export interface MenuItem {
  id: string;
  label: string;
  /** A link item (opens in a new tab); without it the item emits `(picked)` with its id. */
  href?: string;
  danger?: boolean;
  disabled?: boolean;
}

let nextId = 0;

/**
 * A "More" menu button for the quiet actions of a card. Keyboard: Enter, Space, Arrow Down or Arrow Up opens it,
 * the arrow keys (and Home / End) move between items, Esc closes it and returns to the button, Tab closes it.
 * `<app-more-menu [items]="items" context="Backend Engineer" (picked)="run($event)" />`
 */
@Component({
  selector: 'app-more-menu',
  imports: [TPipe],
  host: { class: 'relative inline-block', '(document:click)': 'outside($event)', '(focusout)': 'leave($event)' },
  template: `
    <button type="button" class="btn" aria-haspopup="menu" [attr.aria-expanded]="open()" [attr.aria-controls]="open() ? menuId : null"
            [attr.aria-label]="context() ? (('actions.more' | t) + ': ' + context()) : null" (click)="toggle()" (keydown)="buttonKey($event)">
      {{ 'actions.more' | t }} <span aria-hidden="true">▾</span>
    </button>
    @if (open()) {
      <div [id]="menuId" role="menu" [attr.aria-label]="'actions.more' | t"
           class="absolute end-0 bottom-full z-30 mb-1 min-w-56 max-w-[calc(100vw-2rem)] rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900"
           (keydown)="menuKey($event)">
        @for (it of items(); track it.id) {
          @if (it.href) {
            <a role="menuitem" tabindex="-1" [href]="it.href" target="_blank" rel="noopener" (click)="close(false)"
               class="block rounded-md px-3 py-2 text-sm text-slate-800 no-underline hover:bg-slate-100 hover:no-underline focus:bg-slate-100 focus:outline-none max-sm:min-h-10 dark:text-slate-100 dark:hover:bg-slate-800 dark:focus:bg-slate-800">{{ it.label }}</a>
          } @else {
            <button type="button" role="menuitem" tabindex="-1" [disabled]="it.disabled" (click)="choose(it)"
                    [class]="'block w-full rounded-md px-3 py-2 text-start text-sm hover:bg-slate-100 focus:bg-slate-100 focus:outline-none disabled:opacity-50 max-sm:min-h-10 dark:hover:bg-slate-800 dark:focus:bg-slate-800 ' + (it.danger ? 'text-rose-700 dark:text-rose-400' : 'text-slate-800 dark:text-slate-100')">{{ it.label }}</button>
          }
        }
      </div>
    }
  `,
})
export class MoreMenu {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  readonly items = input<MenuItem[]>([]);
  /** What the menu belongs to, for the button's accessible name ("More: Backend Engineer"). */
  readonly context = input('');
  readonly picked = output<string>();

  protected readonly open = signal(false);
  protected readonly menuId = `more-menu-${++nextId}`;

  protected toggle(): void {
    if (this.open()) this.close(true);
    else this.show(0);
  }

  private show(at: number): void {
    this.open.set(true);
    setTimeout(() => this.entries().at(at)?.focus()); // after the menu has rendered
  }

  protected close(refocus: boolean): void {
    this.open.set(false);
    if (refocus) this.host.nativeElement.querySelector('button')?.focus();
  }

  protected choose(it: MenuItem): void {
    this.close(true);
    this.picked.emit(it.id);
  }

  private entries(): HTMLElement[] {
    return [...this.host.nativeElement.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)')];
  }

  protected buttonKey(e: KeyboardEvent): void {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      this.show(e.key === 'ArrowDown' ? 0 : -1);
    }
  }

  protected menuKey(e: KeyboardEvent): void {
    const list = this.entries();
    const at = list.indexOf(document.activeElement as HTMLElement);
    const go = (i: number) => { e.preventDefault(); list[(i + list.length) % list.length]?.focus(); };
    if (e.key === 'ArrowDown') go(at + 1);
    else if (e.key === 'ArrowUp') go(at - 1);
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(-1);
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(true); }
    else if (e.key === 'Tab') this.close(false);
  }

  protected outside(e: Event): void {
    if (this.open() && !this.host.nativeElement.contains(e.target as Node)) this.close(false);
  }

  protected leave(e: FocusEvent): void {
    const to = e.relatedTarget as Node | null;
    if (this.open() && to && !this.host.nativeElement.contains(to)) this.close(false);
  }
}
