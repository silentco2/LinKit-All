import { Component, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { Hint } from '../components/hint';
import { TabItem, Tabs } from '../components/tabs';
import { TPipe } from '../i18n';
import { Shell } from '../shell';
import { ActionsPage } from './actions';
import { ReviewPage } from './review';

type Tab = 'approve' | 'finish';

/** Needs you: jobs waiting for a yes or no (old Review) and applications that stopped on something (old Action Center). */
@Component({
  selector: 'app-needs-you',
  imports: [Hint, Tabs, TPipe, ReviewPage, ActionsPage],
  template: `
    <h1>{{ 'needs.title' | t }}</h1>
    <app-hint id="needs-you">{{ 'hint.needs' | t }}</app-hint>
    @if (active(); as tab) {
      <div class="mt-5">
        <app-tabs [tabs]="tabs()" [active]="tab" prefix="needs" label="needs.tabs" (pick)="pick($event)" />
      </div>
      <div class="mt-5" role="tabpanel" tabindex="0" [id]="'needs-panel-' + tab" [attr.aria-labelledby]="'needs-tab-' + tab">
        @if (tab === 'approve') { <app-review /> } @else { <app-actions /> }
      </div>
    }
  `,
})
export class NeedsYouPage {
  private readonly shell = inject(Shell);
  private readonly router = inject(Router);
  private readonly params = toSignal(inject(ActivatedRoute).queryParamMap);
  /** Without `?tab=`, open the tab that has something, finish first; decided once so the page does not jump while you work. */
  private readonly first = signal<Tab | null>(null);

  protected readonly tabs = computed<TabItem[]>(() => {
    const s = this.shell.status();
    return [
      { id: 'approve', label: 'needs.tab.approve', count: s?.states['awaiting_review'] ?? 0 },
      { id: 'finish', label: 'needs.tab.finish', count: s?.actions_open ?? 0 },
    ];
  });
  protected readonly active = computed<Tab | null>(() => {
    const asked = this.params()?.get('tab');
    return asked === 'approve' || asked === 'finish' ? asked : this.first();
  });

  constructor() {
    effect(() => {
      const s = this.shell.status();
      if (!s || this.first()) return;
      this.first.set(s.actions_open > 0 || !s.states['awaiting_review'] ? 'finish' : 'approve');
    });
  }

  protected pick(tab: string): void {
    void this.router.navigate([], { queryParams: { tab }, queryParamsHandling: 'merge', replaceUrl: true });
  }
}
