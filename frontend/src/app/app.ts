import { Component, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from './api';
import { Live } from './live';
import { Status } from './types';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="flex min-h-screen">
      <nav class="sticky top-0 flex h-screen w-56 shrink-0 flex-col gap-1 border-r border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900" aria-label="Main">
        <div class="mb-6 px-2">
          <div class="text-lg font-bold text-slate-900 dark:text-white">LinKit <span class="text-brand-600">All</span></div>
          <div class="text-xs text-slate-500">Job search on autopilot</div>
          @if (status(); as s) {
            <span class="badge mt-2" [class]="s.apply_live ? 'tier-mid' : 'tier-low'"
                  [title]="s.apply_live ? 'Real applications are submitted' : 'Nothing is submitted; forms are filled and checked only'">
              {{ s.apply_live ? 'Live applying' : 'Dry run' }}
            </span>
          }
        </div>
        @for (item of nav; track item.path) {
          <a [routerLink]="item.path" routerLinkActive="!bg-brand-50 !text-brand-700 dark:!bg-slate-800 dark:!text-white"
             class="flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium text-slate-600 no-underline hover:bg-slate-100 hover:no-underline dark:text-slate-300 dark:hover:bg-slate-800">
            {{ item.label }}
            @if (item.path === 'review' && reviewCount() > 0) {
              <span class="badge tier-mid">{{ reviewCount() }}</span>
            }
            @if (item.path === 'actions' && actionsCount() > 0) {
              <span class="badge tier-mid">{{ actionsCount() }}</span>
            }
            @if (item.path === 'live' && live.run()?.running) {
              <span class="size-2 animate-pulse rounded-full bg-emerald-500" aria-label="Run in progress"></span>
            }
          </a>
        }
        <div class="mt-auto px-2 text-xs text-slate-400">
          <span class="mr-1 inline-block size-2 rounded-full" [class]="live.connected() ? 'bg-emerald-500' : 'bg-rose-500'"></span>
          {{ live.connected() ? 'Connected' : 'Reconnecting…' }}
        </div>
      </nav>
      <main class="min-w-0 flex-1 p-8">
        @if (status() && !ready()) {
          <div class="alert alert-info mb-6">
            Setup isn't finished yet. <a routerLink="setup">Open the setup wizard</a> to add your profile, CV, AI and search.
          </div>
        }
        <router-outlet />
      </main>
    </div>
  `,
})
export class App {
  protected readonly live = inject(Live);
  private readonly api = inject(Api);
  protected readonly status = signal<Status | null>(null);
  protected readonly reviewCount = signal(0);
  protected readonly actionsCount = signal(0);
  protected readonly nav = [
    { path: 'setup', label: 'Setup' },
    { path: 'jobs', label: 'Jobs' },
    { path: 'review', label: 'Review queue' },
    { path: 'actions', label: 'Action Center' },
    { path: 'live', label: 'Live run' },
    { path: 'report', label: 'Report' },
  ];

  constructor() {
    effect(() => {
      this.live.changed(); // reload counts whenever a stage finishes
      this.refresh();
    });
  }

  ready(): boolean {
    const s = this.status();
    return !!s && s.profile_ready && s.cv_ready && s.search_ready && s.ai_ready;
  }

  async refresh(): Promise<void> {
    try {
      const s = await this.api.get<Status>('/status');
      this.status.set(s);
      this.reviewCount.set(s.states['awaiting_review'] ?? 0);
      this.actionsCount.set(s.actions_open);
      if (!this.live.run()) this.live.run.set(s.run);
    } catch {
      // the server may be restarting; the live socket reconnects and triggers a reload
    }
  }
}
