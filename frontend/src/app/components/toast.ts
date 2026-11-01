import { Component, DestroyRef, inject, input, output } from '@angular/core';

/**
 * A small message at the bottom of the page with an optional action button ("Undo"). It only draws; the page that
 * shows it decides how long it stays. While it shows, the page gets bottom padding (`body.has-toast main`, styles.css)
 * so it never covers the last card's buttons. `<app-toast [text]="…" action="Undo" (act)="undo()" />`
 */
@Component({
  selector: 'app-toast',
  template: `
    <div class="fixed inset-x-0 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-30 mx-auto flex w-fit max-w-[calc(100vw-2rem)] items-center gap-3 rounded-lg bg-slate-900 px-4 py-3 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900"
         role="status">
      <span>{{ text() }}</span>
      @if (action()) {
        <button type="button" class="rounded px-2 py-0.5 font-semibold underline max-sm:min-h-10 max-sm:px-3 hover:bg-white/10 dark:hover:bg-slate-900/10" (click)="act.emit()">{{ action() }}</button>
      }
    </div>
  `,
})
export class Toast {
  constructor() {
    document.body.classList.add('has-toast');
    inject(DestroyRef).onDestroy(() => document.body.classList.remove('has-toast'));
  }

  readonly text = input.required<string>();
  readonly action = input('');
  readonly act = output<void>();
}
