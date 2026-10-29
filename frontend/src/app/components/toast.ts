import { Component, input, output } from '@angular/core';

/**
 * A small message at the bottom of the page with an optional action button ("Undo"). It only draws; the page that
 * shows it decides how long it stays. `<app-toast [text]="…" action="Undo" (act)="undo()" />`
 */
@Component({
  selector: 'app-toast',
  template: `
    <div class="fixed inset-x-0 bottom-4 z-30 mx-auto flex w-fit max-w-[calc(100vw-2rem)] items-center gap-3 rounded-lg bg-slate-900 px-4 py-3 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900"
         role="status">
      <span dir="auto">{{ text() }}</span>
      @if (action()) {
        <button type="button" class="rounded px-2 py-0.5 font-semibold underline hover:bg-white/10 dark:hover:bg-slate-900/10" (click)="act.emit()">{{ action() }}</button>
      }
    </div>
  `,
})
export class Toast {
  readonly text = input.required<string>();
  readonly action = input('');
  readonly act = output<void>();
}
