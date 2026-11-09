import { computed, inject, Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from './api';
import { I18n } from './i18n';
import { Live } from './live';
import { Status } from './types';

const NOTIFY_KEY = 'linkit.notify';

/** The server status every page shares (one fetch, reloaded after each stage), and the desktop-notification switch. */
@Injectable({ providedIn: 'root' })
export class Shell {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly live = inject(Live);
  private readonly router = inject(Router);
  readonly status = signal<Status | null>(null);
  /** Jobs just approved or skipped whose request waits out the Undo window: already gone from the count the user sees. */
  readonly pendingReview = signal(0);
  /** Jobs waiting for a yes or no, as the user sees it (the server count minus what was just approved or skipped). */
  readonly reviewCount = computed(() => Math.max(0, (this.status()?.states['awaiting_review'] ?? 0) - this.pendingReview()));
  /** The one number for everything waiting on the user: nav badge, Needs you tabs and Home all read it. */
  readonly needsCount = computed(() => this.reviewCount() + this.finishCount());
  /** Cards on Needs you > Finish applications: parked applications plus the Google check, if any. */
  readonly finishCount = computed(() => finish(this.status()));
  readonly notifySupported = typeof Notification !== 'undefined';
  readonly notify = signal(this.notifySupported && readNotifyPref() && Notification.permission === 'granted');
  readonly notifyHint = signal('');

  async refresh(): Promise<void> {
    try {
      const s = await this.api.get<Status>('/status');
      const known = this.status() !== null; // the first load is not news
      const before = finish(this.status());
      this.status.set(s);
      if (known && finish(s) > before) {
        this.alert(this.i18n.t('shell.actionNeeded'), this.i18n.plural('shell.actionNeededBody', finish(s)), 'actions', '/needs-you?tab=finish');
      }
      if (!this.live.run()) this.live.run.set(s.run);
    } catch {
      // the server may be restarting; the live socket reconnects and triggers a reload
    }
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

  /** A desktop alert; clicking it opens `url`, the one place that has the thing to do. */
  alert(title: string, body: string, tag: string, url: string): void {
    if (!this.notify() || !this.notifySupported || Notification.permission !== 'granted') return;
    try {
      const n = new Notification(title, { body, tag }); // same tag replaces an older alert
      n.onclick = () => {
        window.focus();
        void this.router.navigateByUrl(url);
        n.close();
      };
    } catch {
      // some browsers refuse the constructor; the in-app badges still show the news
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

function finish(s: Status | null): number {
  return (s?.actions_open ?? 0) + (s?.google_check ? 1 : 0);
}
