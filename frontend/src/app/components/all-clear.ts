import { Component, inject } from '@angular/core';
import { TPipe } from '../i18n';
import { Shell } from '../shell';

/** The empty state of Needs you: nothing to do, and a way to be told when that changes. */
@Component({
  selector: 'app-all-clear',
  imports: [TPipe],
  template: `
    <div class="card space-y-3 text-center text-sm text-slate-500">
      <p>{{ 'needs.empty' | t }}</p>
      @if (shell.notifySupported && !shell.notify()) {
        <label class="inline-flex items-center gap-2" [title]="'shell.notifyTitle' | t">
          <input type="checkbox" [checked]="false" (change)="shell.toggleNotify()"> {{ 'shell.notify' | t }}
        </label>
        @if (shell.notifyHint()) { <p class="text-amber-600">{{ shell.notifyHint() }}</p> }
      }
    </div>
  `,
})
export class AllClear {
  protected readonly shell = inject(Shell);
}
