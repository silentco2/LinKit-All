import { Component, computed, input, signal } from '@angular/core';
import { TPipe } from '../i18n';

const KEY = 'linkit.hints';

function read(): Set<string> {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return new Set(Array.isArray(v) ? v.map(String) : []);
  } catch {
    return new Set(); // storage blocked or garbled: show the hints
  }
}

/** Hints already dismissed. Kept in memory too, so with storage blocked a dismissal lasts for the session. */
const seen = signal<ReadonlySet<string>>(read());

/** "Show tips again" (Settings): forget every dismissal. */
export function resetHints(): void {
  seen.set(new Set());
  try {
    localStorage.removeItem(KEY);
  } catch {
    // nothing stored that we could clear
  }
}

/**
 * One dismissible line per page, shown on the first visit only (ux-plan 11.5): `<app-hint id="home">text</app-hint>`.
 * The text is projected; `id` is the page name and the key in `linkit.hints` (a per-viewer convenience).
 */
@Component({
  selector: 'app-hint',
  imports: [TPipe],
  template: `
    @if (shown()) {
      <div class="alert alert-info mt-3 flex items-start justify-between gap-3" role="note">
        <p dir="auto"><ng-content /></p>
        <button type="button" class="shrink-0 rounded px-1.5 text-slate-500 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-brand-500 dark:hover:text-white"
                [attr.aria-label]="'hint.dismiss' | t" (click)="dismiss()">✕</button>
      </div>
    }
  `,
})
export class Hint {
  readonly id = input.required<string>();
  protected readonly shown = computed(() => !seen().has(this.id()));

  protected dismiss(): void {
    seen.update((s) => new Set(s).add(this.id()));
    try {
      localStorage.setItem(KEY, JSON.stringify([...seen()]));
    } catch {
      // the dismissal lasts until the tab closes
    }
  }
}
