import { Component, computed, effect, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from './api';
import { I18n, Lang, TPipe } from './i18n';
import { Live } from './live';
import { Shell } from './shell';
import { LiveEvent, setupDone } from './types';

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
          @if (shell.status(); as s) {
            <span class="badge mt-2" [class]="s.apply_live ? 'tier-mid' : 'tier-low'"
                  [title]="(s.apply_live ? 'shell.liveTitle' : 'shell.dryTitle') | t">
              {{ (s.apply_live ? 'shell.live' : 'shell.dry') | t }}
            </span>
          }
        </div>
        @for (item of nav; track item.path) {
          <a [routerLink]="item.path" (click)="menuOpen.set(false)" routerLinkActive="!bg-brand-50 !text-brand-700 dark:!bg-slate-800 dark:!text-white" ariaCurrentWhenActive="page"
             class="flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium text-slate-600 no-underline hover:bg-slate-100 hover:no-underline dark:text-slate-300 dark:hover:bg-slate-800">
            {{ item.label | t }}
            @if (item.path === 'needs-you' && needsCount() > 0) {
              <span class="badge tier-mid">{{ needsCount() }}</span>
            }
            @if (item.path === 'activity' && live.run()?.running) {
              <span class="size-2 animate-pulse rounded-full bg-emerald-500" role="img" [attr.aria-label]="'shell.running' | t"></span>
            }
            @if (item.path === 'settings' && setupLeft(); as n) {
              <span class="badge tier-mid">{{ 'shell.setupChip' | t: { n: n.done, total: 4 } }}</span>
            }
          </a>
        }
        <div class="mt-4 space-y-2 px-2 text-xs text-slate-400 md:mt-auto">
          <div class="flex items-center gap-1" role="group" [attr.aria-label]="'shell.language' | t">
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="en" dir="ltr" [class.btn-primary]="i18n.lang() === 'en'" [attr.aria-pressed]="i18n.lang() === 'en'" (click)="setLang('en')">English</button>
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="ar" dir="rtl" [class.btn-primary]="i18n.lang() === 'ar'" [attr.aria-pressed]="i18n.lang() === 'ar'" (click)="setLang('ar')">العربية</button>
          </div>
          @if (shell.notifySupported) {
            <label class="flex items-center gap-2" [title]="'shell.notifyTitle' | t">
              <input type="checkbox" [checked]="shell.notify()" (change)="shell.toggleNotify()"> {{ 'shell.notify' | t }}
            </label>
            @if (shell.notifyHint()) { <p class="text-amber-600">{{ shell.notifyHint() }}</p> }
          }
          <div>
          <span class="me-1 inline-block size-2 rounded-full" [class]="live.connected() ? 'bg-emerald-500' : 'bg-rose-500'"></span>
          {{ (live.connected() ? 'shell.connected' : 'shell.reconnecting') | t }}
          </div>
        </div>
      </nav>
      }
      <main class="min-w-0 flex-1 overflow-x-auto p-4 md:p-8">
        <router-outlet />
      </main>
    </div>
  `,
})
export class App {
  protected readonly live = inject(Live);
  protected readonly shell = inject(Shell);
  private readonly api = inject(Api);
  protected readonly i18n = inject(I18n);
  private readonly router = inject(Router);
  private readonly path = signal(window.location.pathname);
  /** First-run flow: no side nav, the page is its own guide. */
  protected readonly welcome = computed(() => this.path().startsWith('/welcome'));
  protected readonly menuOpen = signal(false);
  /** One badge for everything waiting on the user: jobs to approve plus applications to finish. */
  protected readonly needsCount = computed(() => {
    const s = this.shell.status();
    return s ? (s.states['awaiting_review'] ?? 0) + s.actions_open : 0;
  });
  /** The "Setup N/4" chip on Settings, until the required steps are done. */
  protected readonly setupLeft = computed(() => {
    const s = this.shell.status();
    return s && !s.setup.required_done ? { done: setupDone(s.setup) } : null;
  });
  private lastRunEnd = '';
  private lastPath = '';
  protected readonly nav = [
    { path: 'home', label: 'shell.nav.home' },
    { path: 'jobs', label: 'shell.nav.jobs' },
    { path: 'needs-you', label: 'shell.nav.needsYou' },
    { path: 'activity', label: 'shell.nav.activity' },
    { path: 'settings', label: 'shell.nav.settings' },
  ];

  constructor() {
    this.router.events.subscribe((e) => {
      if (!(e instanceof NavigationEnd)) return;
      const path = e.urlAfterRedirects.split(/[?#]/)[0];
      this.path.set(path);
      void this.shell.refresh(); // leaving /welcome: the setup chip must see the new status
      if (path !== this.lastPath) focusHeading(); // a tab or filter change in the URL keeps the focus where it is
      this.lastPath = path;
    });
    effect(() => {
      this.live.changed(); // reload counts whenever a stage finishes
      void this.shell.refresh();
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

  private async runEnded(end: LiveEvent): Promise<void> {
    if (!this.shell.notify()) return;
    const alert = (title: string, body: string) => this.shell.alert(title, body, 'run', '/activity');
    if (end.error) return alert(this.i18n.t('shell.runFailed'), end.error);
    let pause: string | null = null;
    try {
      const { recent } = await this.api.get<{ recent: { status: string; pause_reason: string | null }[] }>('/runs');
      if (recent[0]?.status === 'paused') pause = recent[0].pause_reason ?? this.i18n.t('shell.resumeHint');
    } catch {
      // fall back to the plain message
    }
    if (pause) alert(this.i18n.t('shell.runPaused'), pause);
    else alert(this.i18n.t('shell.runFinished'), this.i18n.t('shell.runFinishedBody'));
  }
}

/** After a page change, move focus to the page's <h1> (once it has rendered) so a screen reader starts there. */
function focusHeading(tries = 20): void {
  const h1 = document.querySelector<HTMLElement>('main h1');
  if (h1) {
    h1.tabIndex = -1;
    h1.focus({ preventScroll: true });
  } else if (tries > 0) {
    setTimeout(() => focusHeading(tries - 1), 50);
  }
}
