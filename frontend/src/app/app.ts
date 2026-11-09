import { Component, computed, effect, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from './api';
import { I18n, Lang, TPipe } from './i18n';
import { Live } from './live';
import { fmtNum, localeOf, runReason } from './locale';
import { Shell } from './shell';
import { LiveEvent, setupDone } from './types';

const FRESH_MS = 60_000; // a run that ended longer ago than this is replayed history, not news

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, TPipe],
  template: `
    <div class="flex min-h-screen flex-col">
      @if (!welcome()) {
      <header class="desk-top">
        <a routerLink="/home" class="wordmark">LinKit All</a>
        <nav id="main-nav" class="order-last w-full flex-col gap-1 md:order-none md:flex md:w-auto md:flex-row md:gap-5"
             [class.hidden]="!menuOpen()" [class.flex]="menuOpen()" [attr.aria-label]="'shell.navLabel' | t">
          @for (item of nav; track item.path) {
            <a [routerLink]="item.path" (click)="menuOpen.set(false)" routerLinkActive="is-active" ariaCurrentWhenActive="page" class="nav-link max-md:min-h-10">
              {{ item.label | t }}
              @if (item.path === 'needs-you' && shell.needsCount() > 0) {
                <span class="text-rose-600 dark:text-rose-400">{{ num(shell.needsCount()) }}</span>
              }
              @if (item.path === 'home' && live.run()?.running) {
                <span class="size-1.5 animate-pulse rounded-full bg-emerald-500" role="img" [attr.aria-label]="'shell.running' | t"></span>
              }
              @if (item.path === 'settings' && setupLeft(); as n) {
                <span class="font-normal text-slate-500">{{ 'shell.setupChip' | t: { n: n.done, total: 4 } }}</span>
              }
            </a>
          }
        </nav>
        <div class="ms-auto flex min-w-0 items-center gap-3 text-sm">
          @if (!live.connected()) { <span class="text-rose-600 dark:text-rose-400" role="status">{{ 'shell.reconnecting' | t }}</span> }
          @if (shell.status(); as s) {
            <span class="whitespace-nowrap" [class]="s.apply_live ? 'font-medium text-rose-600 dark:text-rose-400' : 'text-slate-500'" [title]="(s.apply_live ? 'shell.liveTitle' : 'shell.dryTitle') | t">
              {{ (s.apply_live ? 'shell.live' : 'shell.dry') | t }}
            </span>
          }
          @if (shell.needsCount() > 0) {
            <a routerLink="/needs-you" class="flex min-h-10 min-w-10 items-center justify-center font-medium text-rose-600 hover:no-underline md:hidden dark:text-rose-400" [attr.aria-label]="('shell.nav.needsYou' | t) + ': ' + num(shell.needsCount())">{{ num(shell.needsCount()) }}</a>
          }
          <button type="button" class="btn min-h-10 md:hidden" (click)="menuOpen.set(!menuOpen())" [attr.aria-expanded]="menuOpen()" aria-controls="main-nav">
            {{ 'shell.menu' | t }}
          </button>
        </div>
      </header>
      }
      <main class="mx-auto w-full max-w-[76rem] min-w-0 flex-1 overflow-x-auto px-4 pt-4 pb-12 md:px-8" [class.pt-8]="welcome()">
        <router-outlet />
      </main>
      @if (!welcome()) {
      <footer class="mx-auto flex w-full max-w-[76rem] flex-wrap items-center gap-x-6 gap-y-1 px-4 pb-6 text-xs text-slate-500 md:px-8">
        <div class="flex items-center gap-3" role="group" [attr.aria-label]="'shell.language' | t">
          <button type="button" class="lang-btn" lang="en" dir="ltr" [attr.aria-pressed]="i18n.lang() === 'en'" (click)="setLang('en')">English</button>
          <button type="button" class="lang-btn" lang="ar" dir="rtl" [attr.aria-pressed]="i18n.lang() === 'ar'" (click)="setLang('ar')">العربية</button>
        </div>
        @if (shell.notifySupported) {
          <label class="flex items-center gap-2" [title]="'shell.notifyTitle' | t">
            <input type="checkbox" [checked]="shell.notify()" (change)="shell.toggleNotify()"> {{ 'shell.notify' | t }}
          </label>
          @if (shell.notifyHint()) { <p class="text-amber-700 dark:text-amber-400">{{ shell.notifyHint() }}</p> }
        }
        @if (live.connected()) { <span>{{ 'shell.connected' | t }}</span> }
      </footer>
      }
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
  protected readonly num = (n: number): string => fmtNum(localeOf(this.i18n.lang()), n);
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
    const alert = (title: string, body: string) => this.shell.alert(title, body, 'run', '/home');
    if (end.error) {
      // a run that stopped for a known reason is said in words; anything else is "Something went wrong." (never the raw text)
      const known = end.reason_code && end.reason_code !== 'pipeline_error' && this.i18n.has('run.reason.' + end.reason_code);
      return alert(this.i18n.t('shell.runFailed'), known ? runReason(this.i18n, end.reason_code, end.reason_params, end.error) : this.i18n.t('live.err.generic'));
    }
    let pause: string | null = null;
    try {
      const { recent } = await this.api.get<{ recent: { status: string; pause_reason: string | null; reason_code: string | null; reason_params: Record<string, unknown> }[] }>('/runs');
      if (recent[0]?.status === 'paused') {
        const r = recent[0];
        const known = r.reason_code && r.reason_code !== 'pipeline_error' && this.i18n.has('run.reason.' + r.reason_code);
        pause = known ? runReason(this.i18n, r.reason_code, r.reason_params, r.pause_reason ?? '') : this.i18n.t('shell.resumeHint');
      }
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
