import { Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { Api } from '../../api';
import { I18n, TPipe } from '../../i18n';
import { DtPipe } from '../../locale';
import { REMOTE } from '../../remote';

interface PhoneDevice { id: number; name: string; created: string; last_seen: string }
interface PhoneStatus {
  enabled: boolean;
  online: boolean;
  error: string;
  relay: string;
  this_device: number | null;
  devices?: PhoneDevice[];
}
interface PairCode { code: string; url: string; qr: string; expires_in: number }

const GUIDE = 'https://github.com/silentco2/LinKit-All/blob/main/docs/phone.md';

/** Settings > Phone: on the PC, switch phone access on, pair by QR code and revoke phones; on the phone, this phone. */
@Component({
  selector: 'app-settings-phone',
  imports: [DtPipe, TPipe],
  template: `
    <section class="card space-y-5">
      <h2>{{ 'phone.title' | t }}</h2>
      @if (error()) { <div class="alert alert-error" role="alert" dir="auto">{{ error() }}</div> }
      @if (status(); as s) {
        @if (remote) {
          <p class="text-sm">{{ 'phone.onPhone' | t }}</p>
          @if (pushSupported) {
            <label class="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" [checked]="push()" [disabled]="busy()" (change)="togglePush(checked($event))"> {{ 'phone.push' | t }}
            </label>
            <p class="hint">{{ 'phone.pushHint' | t }}</p>
          } @else {
            <p class="hint">{{ 'phone.pushInstall' | t }}</p>
          }
        } @else {
          <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'phone.intro' | t }} <a [href]="guide" target="_blank" rel="noopener">{{ 'phone.guide' | t }}</a></p>
          <div class="space-y-3">
            <label class="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" [checked]="s.enabled" [disabled]="busy()" (change)="save(checked($event))"> {{ 'phone.enable' | t }}
            </label>
            @if (s.enabled) {
              @if (s.online) { <p class="text-sm text-green-700 dark:text-green-400" role="status">{{ 'phone.online' | t }}</p> }
              @else if (s.error) { <div class="alert alert-error" role="alert" dir="auto">{{ s.error }}</div> }
              @else { <p class="text-sm text-slate-500" role="status">{{ 'phone.connecting' | t }}</p> }
            }
            <details class="text-sm">
              <summary class="cursor-pointer">{{ 'phone.relay' | t }}</summary>
              <input id="phone-relay" class="input mt-2" dir="ltr" placeholder="https://" [attr.aria-label]="'phone.relay' | t"
                     [value]="relay()" (input)="relay.set(val($event))" (change)="save(s.enabled)">
              <p class="hint">{{ 'phone.relayHint' | t }}</p>
            </details>
          </div>

          @if (s.enabled && s.online) {
            <div class="border-t border-slate-100 pt-5 dark:border-slate-800">
              <h3 class="font-semibold">{{ 'phone.pairTitle' | t }}</h3>
              @if (pairing(); as p) {
                <img class="mt-3 size-56 rounded bg-white p-2" [src]="p.qr" [alt]="'phone.qrAlt' | t">
                <p class="hint">{{ 'phone.expires' | t: { n: minutesLeft() } }}</p>
              } @else {
                <p class="mt-1 text-sm text-slate-600 dark:text-slate-400">{{ 'phone.pairIntro' | t }}</p>
                <button type="button" class="btn btn-primary mt-3" [disabled]="busy()" (click)="pair()">{{ 'phone.pairBtn' | t }}</button>
              }
            </div>
          }

          <div class="border-t border-slate-100 pt-5 dark:border-slate-800">
            <h3 class="font-semibold">{{ 'phone.devices' | t }}</h3>
            <ul class="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
              @for (d of s.devices ?? []; track d.id) {
                <li class="flex flex-wrap items-center gap-3 py-2 text-sm">
                  <span class="font-medium" dir="auto">{{ d.name }}</span>
                  <span class="text-slate-500">{{ 'phone.lastSeen' | t: { when: (d.last_seen | dt) } }}</span>
                  <button type="button" class="btn ms-auto" [disabled]="busy()" (click)="revoke(d)">{{ 'phone.revoke' | t }}</button>
                </li>
              } @empty {
                <li class="py-2 text-sm text-slate-500">{{ 'phone.none' | t }}</li>
              }
            </ul>
          </div>
        }
      } @else if (!error()) {
        <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
      }
    </section>
  `,
})
export class PhoneSection implements OnInit, OnDestroy {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly remote = REMOTE;
  /** iPhone: only once LinKit is added to the home screen (iOS 16.4+). */
  protected readonly pushSupported = 'serviceWorker' in navigator && 'PushManager' in window;
  protected readonly push = signal(false);
  protected readonly guide = GUIDE;
  protected readonly status = signal<PhoneStatus | null>(null);
  protected readonly relay = signal('');
  protected readonly pairing = signal<PairCode | null>(null);
  protected readonly minutesLeft = signal(5);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  private timer: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    void this.load();
    if (REMOTE && this.pushSupported) {
      void navigator.serviceWorker.getRegistration().then(async (reg) => this.push.set(!!(await reg?.pushManager.getSubscription())));
    }
  }

  /** Opt-in web push (docs/phone.md): the PC only ever sends a count; the words are saved here, in this phone's language. */
  protected async togglePush(on: boolean): Promise<void> {
    await this.run(async () => {
      const reg = await navigator.serviceWorker.ready;
      if (!on) {
        await (await reg.pushManager.getSubscription())?.unsubscribe();
        await this.api.delete('/phone/push');
        this.push.set(false);
        return;
      }
      if ((await Notification.requestPermission()) !== 'granted') {
        this.push.set(false);
        throw new Error(this.i18n.t('shell.blocked'));
      }
      const { public_key } = await this.api.get<{ public_key: string }>('/phone/push');
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: fromBase64Url(public_key) });
      await (await caches.open('linkit-push')).put('/push-title', new Response(this.i18n.t('push.title')));
      await this.api.put('/phone/push', sub.toJSON());
      this.push.set(true);
    });
  }

  ngOnDestroy(): void {
    this.stop();
  }

  private async load(): Promise<void> {
    try {
      const s = await this.api.get<PhoneStatus>('/phone');
      this.status.set(s);
      if (!this.relay()) this.relay.set(s.relay);
      // still connecting: look again shortly (the tunnel needs a few seconds to reach a relay)
      if (s.enabled && !s.online && !s.error && !this.pairing()) setTimeout(() => void this.load(), 2000);
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  protected async save(enabled: boolean): Promise<void> {
    await this.run(async () => {
      this.status.set(await this.api.put<PhoneStatus>('/phone/remote', { enabled, relay: this.relay().trim() }));
      this.stop();
    });
  }

  /** Show a fresh code; while it shows, look for the new phone every 3 s and hide the code once it has paired. */
  protected async pair(): Promise<void> {
    await this.run(async () => {
      const p = await this.api.post<PairCode>('/phone/pair');
      const before = this.status()?.devices?.length ?? 0;
      const ends = Date.now() + p.expires_in * 1000;
      this.stop();
      this.pairing.set(p);
      this.minutesLeft.set(Math.ceil(p.expires_in / 60));
      this.timer = setInterval(async () => {
        this.minutesLeft.set(Math.max(0, Math.ceil((ends - Date.now()) / 60_000)));
        if (Date.now() > ends) return this.stop();
        await this.load();
        if ((this.status()?.devices?.length ?? 0) > before) this.stop();
      }, 3000);
    });
  }

  protected async revoke(d: PhoneDevice): Promise<void> {
    await this.run(async () => {
      await this.api.delete(`/phone/devices/${d.id}`);
      await this.load();
    });
  }

  private stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.pairing.set(null);
  }

  private async run(fn: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await fn();
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  protected val = (e: Event): string => (e.target as HTMLInputElement).value;
  protected checked = (e: Event): boolean => (e.target as HTMLInputElement).checked;
}

function fromBase64Url(text: string): Uint8Array<ArrayBuffer> {
  const bin = atob(text.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
