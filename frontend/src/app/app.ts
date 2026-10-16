import { Component, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from './api';
import { Live } from './live';
import { LiveEvent, Status } from './types';

const NOTIFY_KEY = 'linkit.notify';
const FRESH_MS = 60_000; // a run that ended longer ago than this is replayed history, not news

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
        <div class="mt-auto space-y-2 px-2 text-xs text-slate-400">
          @if (notifySupported) {
            <label class="flex items-center gap-2" title="Get a desktop alert when a run finishes or pauses, or when something needs you">
              <input type="checkbox" [checked]="notify()" (change)="toggleNotify()"> Desktop notifications
            </label>
            @if (notifyHint()) { <p class="text-amber-600">{{ notifyHint() }}</p> }
          }
          <div>
          <span class="mr-1 inline-block size-2 rounded-full" [class]="live.connected() ? 'bg-emerald-500' : 'bg-rose-500'"></span>
          {{ live.connected() ? 'Connected' : 'Reconnecting…' }}
          </div>
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
  protected readonly notifySupported = typeof Notification !== 'undefined';
  protected readonly notify = signal(this.notifySupported && readNotifyPref() && Notification.permission === 'granted');
  protected readonly notifyHint = signal('');
  private lastRunEnd = '';
  protected readonly nav = [
    { path: 'setup', label: 'Setup' },
    { path: 'jobs', label: 'Jobs' },
    { path: 'review', label: 'Review queue' },
    { path: 'actions', label: 'Action Center' },
    { path: 'answers', label: 'Answer bank' },
    { path: 'vault', label: 'Vault' },
    { path: 'live', label: 'Live run' },
    { path: 'report', label: 'Report' },
  ];

  constructor() {
    effect(() => {
      this.live.changed(); // reload counts whenever a stage finishes
      this.refresh();
    });
    effect(() => {
      // the newest run event; "started" means a run is going, anything else is its end
      const end = [...this.live.events()].reverse().find((e) => e.type === 'run');
      if (!end || end.status === 'started' || end.at === this.lastRunEnd) return;
      this.lastRunEnd = end.at;
      if (end.status !== 'cancelled' && Date.now() - Date.parse(end.at) < FRESH_MS) void this.runEnded(end);
    });
  }

  async toggleNotify(): Promise<void> {
    this.notifyHint.set('');
    if (this.notify()) return this.setNotify(false);
    if (Notification.permission === 'default') await Notification.requestPermission();
    const granted = Notification.permission === 'granted';
    if (!granted) this.notifyHint.set('Blocked: allow notifications for this site in your browser settings.');
    this.setNotify(granted);
  }

  private setNotify(on: boolean): void {
    this.notify.set(on);
    try {
      localStorage.setItem(NOTIFY_KEY, on ? '1' : '0');
    } catch {
      // storage can be blocked; the choice then lasts until the tab closes
    }
  }

  private async runEnded(end: LiveEvent): Promise<void> {
    if (!this.notify()) return;
    if (end.error) return this.alert('Run failed', end.error, 'run');
    let pause: string | null = null;
    try {
      const { recent } = await this.api.get<{ recent: { status: string; pause_reason: string | null }[] }>('/runs');
      if (recent[0]?.status === 'paused') pause = recent[0].pause_reason ?? 'It will continue when you start it again.';
    } catch {
      // fall back to the plain message
    }
    if (pause) this.alert('Run paused', pause, 'run');
    else this.alert('Run finished', 'Open LinKit All to see the results.', 'run');
  }

  private alert(title: string, body: string, tag: string): void {
    if (!this.notify() || !this.notifySupported || Notification.permission !== 'granted') return;
    try {
      const n = new Notification(title, { body, tag }); // same tag replaces an older alert
      n.onclick = () => {
        window.focus();
        n.close();
      };
    } catch {
      // some browsers refuse the constructor; the in-app badges still show the news
    }
  }

  ready(): boolean {
    const s = this.status();
    return !!s && s.profile_ready && s.cv_ready && s.search_ready && s.ai_ready;
  }

  async refresh(): Promise<void> {
    try {
      const s = await this.api.get<Status>('/status');
      const known = this.status() !== null; // the first load is not news
      this.status.set(s);
      this.reviewCount.set(s.states['awaiting_review'] ?? 0);
      if (known && s.actions_open > this.actionsCount()) {
        this.alert('Action needed', `${s.actions_open} job(s) are waiting for you in the Action Center.`, 'actions');
      }
      this.actionsCount.set(s.actions_open);
      if (!this.live.run()) this.live.run.set(s.run);
    } catch {
      // the server may be restarting; the live socket reconnects and triggers a reload
    }
  }
}

function readNotifyPref(): boolean {
  try {
    return localStorage.getItem(NOTIFY_KEY) === '1';
  } catch {
    return false;
  }
}
