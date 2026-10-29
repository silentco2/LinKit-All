import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { TabItem, Tabs } from '../components/tabs';
import { TPipe } from '../i18n';
import { LivePage } from './live';
import { ReportPage } from './report';

type Tab = 'now' | 'history';
const TABS: TabItem[] = [
  { id: 'now', label: 'activity.tab.now' },
  { id: 'history', label: 'activity.tab.history' },
];

/** Activity: what is happening now (old Live run) and what happened before (old Report). */
@Component({
  selector: 'app-activity',
  imports: [Tabs, TPipe, LivePage, ReportPage],
  template: `
    <h1>{{ 'activity.title' | t }}</h1>
    <div class="mt-5">
      <app-tabs [tabs]="tabs" [active]="active()" prefix="activity" label="activity.tabs" (pick)="pick($event)" />
    </div>
    <div class="mt-5" role="tabpanel" tabindex="0" [id]="'activity-panel-' + active()" [attr.aria-labelledby]="'activity-tab-' + active()">
      @if (active() === 'now') { <app-live /> } @else { <app-report /> }
    </div>
  `,
})
export class ActivityPage {
  private readonly router = inject(Router);
  private readonly params = toSignal(inject(ActivatedRoute).queryParamMap);
  protected readonly tabs = TABS;
  protected readonly active = computed<Tab>(() => (this.params()?.get('tab') === 'history' ? 'history' : 'now'));

  protected pick(tab: string): void {
    void this.router.navigate([], { queryParams: { tab: tab === 'now' ? null : tab }, queryParamsHandling: 'merge', replaceUrl: true });
  }
}
