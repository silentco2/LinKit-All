import { Component, computed, effect, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from './api';
import { I18n, Lang, TPipe } from './i18n';
import { Live } from './live';
import { LiveEvent, Status } from './types';

const NOTIFY_KEY = 'linkit.notify';
const FRESH_MS = 60_000; // a run that ended longer ago than this is replayed history, not news

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, TPipe],
  template: `
    <div class="flex min-h-screen flex-col md:flex-row">
      @if (!welcome()) {
      <header class="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden dark:border-slate-800 dark:bg-slate-900">
        <div class="text-lg font-bold text-slate-900 dark:text-white">LinKit <span class="text-brand-600">All</span></div>
        <button type="button" class="btn" (click)="menuOpen.set(!menuOpen())" [attr.aria-expanded]="menuOpen()" aria-controls="main-nav">
          {{ 'shell.menu' | t }}
        </button>
      </header>
      }
      @if (!welcome()) {
      <nav id="main-nav" class="flex-col gap-1 border-b border-slate-200 bg-white p-4 md:sticky md:top-0 md:flex md:h-screen md:w-56 md:shrink-0 md:border-e md:border-b-0 dark:border-slate-800 dark:bg-slate-900"
           [class.hidden]="!menuOpen()" [class.flex]="menuOpen()" [attr.aria-label]="'shell.navLabel' | t">
        <div class="mb-4 px-2 md:mb-6">
          <div class="text-lg font-bold text-slate-900 dark:text-white">LinKit <span class="text-brand-600">All</span></div>
          <div class="text-xs text-slate-500">{{ 'shell.tagline' | t }}</div>
          @if (status(); as s) {
            <span class="badge mt-2" [class]="s.apply_live ? 'tier-mid' : 'tier-low'"
                  [title]="(s.apply_live ? 'shell.liveTitle' : 'shell.dryTitle') | t">
              {{ (s.apply_live ? 'shell.live' : 'shell.dry') | t }}
            </span>
          }
        </div>
        @for (item of nav; track item.path) {
          <a [routerLink]="item.path" (click)="menuOpen.set(false)" routerLinkActive="!bg-brand-50 !text-brand-700 dark:!bg-slate-800 dark:!text-white"
             class="flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium text-slate-600 no-underline hover:bg-slate-100 hover:no-underline dark:text-slate-300 dark:hover:bg-slate-800">
            {{ item.label | t }}
            @if (item.path === 'review' && reviewCount() > 0) {
              <span class="badge tier-mid">{{ reviewCount() }}</span>
            }
            @if (item.path === 'actions' && actionsCount() > 0) {
              <span class="badge tier-mid">{{ actionsCount() }}</span>
            }
            @if (item.path === 'live' && live.run()?.running) {
              <span class="size-2 animate-pulse rounded-full bg-emerald-500" [attr.aria-label]="'shell.running' | t"></span>
            }
          </a>
        }
        <div class="mt-4 space-y-2 px-2 text-xs text-slate-400 md:mt-auto">
          <div class="flex items-center gap-1" role="group" [attr.aria-label]="'shell.language' | t">
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="en" dir="ltr" [class.btn-primary]="i18n.lang() === 'en'" [attr.aria-pressed]="i18n.lang() === 'en'" (click)="setLang('en')">English</button>
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="ar" dir="rtl" [class.btn-primary]="i18n.lang() === 'ar'" [attr.aria-pressed]="i18n.lang() === 'ar'" (click)="setLang('ar')">العربية</button>
          </div>
          @if (notifySupported) {
            <label class="flex items-center gap-2" [title]="'shell.notifyTitle' | t">
              <input type="checkbox" [checked]="notify()" (change)="toggleNotify()"> {{ 'shell.notify' | t }}
            </label>
            @if (notifyHint()) { <p class="text-amber-600">{{ notifyHint() }}</p> }
          }
          <div>
          <span class="me-1 inline-block size-2 rounded-full" [class]="live.connected() ? 'bg-emerald-500' : 'bg-rose-500'"></span>
          {{ (live.connected() ? 'shell.connected' : 'shell.reconnecting') | t }}
          </div>
        </div>
      </nav>
      }
      <main class="min-w-0 flex-1 overflow-x-auto p-4 md:p-8">
        @if (status() && !ready() && !welcome()) {
          <div class="alert alert-info mb-6">
            {{ 'shell.setupA' | t }}<a routerLink="setup">{{ 'shell.setupB' | t }}</a>{{ 'shell.setupC' | t }}
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
  protected readonly i18n = inject(I18n);
  private readonly router = inject(Router);
  private readonly path = signal(window.location.pathname);
  /** First-run flow: no side nav and no "finish setup" banner, the page is its own guide. */
  protected readonly welcome = computed(() => this.path().startsWith('/welcome'));
  protected readonly menuOpen = signal(false);
  protected readonly status = signal<Status | null>(null);
  protected readonly reviewCount = signal(0);
  protected readonly actionsCount = signal(0);
  protected readonly notifySupported = typeof Notification !== 'undefined';
  protected readonly notify = signal(this.notifySupported && readNotifyPref() && Notification.permission === 'granted');
  protected readonly notifyHint = signal('');
  private lastRunEnd = '';
  protected readonly nav = [
    { path: 'setup', label: 'shell.nav.setup' },
    { path: 'jobs', label: 'shell.nav.jobs' },
    { path: 'review', label: 'shell.nav.review' },
    { path: 'actions', label: 'shell.nav.actions' },
    { path: 'answers', label: 'shell.nav.answers' },
    { path: 'vault', label: 'shell.nav.vault' },
    { path: 'live', label: 'shell.nav.live' },
    { path: 'report', label: 'shell.nav.report' },
  ];

  constructor() {
    this.router.events.subscribe((e) => {
      if (!(e instanceof NavigationEnd)) return;
      this.path.set(e.urlAfterRedirects.split(/[?#]/)[0]);
      void this.refresh(); // leaving /welcome: the "finish setup" banner must see the new status
    });
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

  protected setLang(lang: Lang): void {
    this.i18n.set(lang);
  }

  async toggleNotify(): Promise<void> {
    this.notifyHint.set('');
    if (this.notify()) return this.setNotify(false);
    if (Notification.permission === 'default') await Notification.requestPermission();
    const granted = Notification.permission === 'granted';
    if (!granted) this.notifyHint.set(this.i18n.t('shell.blocked'));
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
    if (end.error) return this.alert(this.i18n.t('shell.runFailed'), end.error, 'run');
    let pause: string | null = null;
    try {
      const { recent } = await this.api.get<{ recent: { status: string; pause_reason: string | null }[] }>('/runs');
      if (recent[0]?.status === 'paused') pause = recent[0].pause_reason ?? this.i18n.t('shell.resumeHint');
    } catch {
      // fall back to the plain message
    }
    if (pause) this.alert(this.i18n.t('shell.runPaused'), pause, 'run');
    else this.alert(this.i18n.t('shell.runFinished'), this.i18n.t('shell.runFinishedBody'), 'run');
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
        this.alert(this.i18n.t('shell.actionNeeded'), this.i18n.t('shell.actionNeededBody', { n: s.actions_open }), 'actions');
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
