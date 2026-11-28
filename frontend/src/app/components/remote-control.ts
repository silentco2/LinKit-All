import { Component, ElementRef, inject, OnDestroy, signal, viewChild } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { DtPipe } from '../locale';
import { REMOTE } from '../remote';

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

const GUIDE = 'https://linkit-all.github.io/docs/phone/';

/**
 * Home > Remote control (docs/phone.md). On the PC, opening it turns the tunnel on and shows a
 * pairing QR code, with the paired phones below it. On the phone: this phone's notifications.
 */
@Component({
  selector: 'app-remote-control',
  imports: [DtPipe, TPipe],
  template: `
    <button type="button" class="btn" aria-haspopup="dialog" (click)="open()">{{ 'remote.open' | t }}</button>
    <dialog #box class="m-auto mt-[8vh] w-[min(95vw,30rem)] rounded-xl bg-white p-0 text-slate-900 backdrop:bg-black/50 dark:bg-slate-900 dark:text-slate-100"
            aria-labelledby="rc-title" (close)="stop()" (click)="$event.target === box && box.close()">
      <div class="space-y-5 p-5">
        <div class="flex items-start gap-3">
          <h2 id="rc-title" class="text-lg font-semibold">{{ 'remote.title' | t }}</h2>
          <button type="button" class="btn ms-auto px-2 py-1" [attr.aria-label]="'common.drawer.close' | t" (click)="box.close()">
            <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
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
            @if (s.online) {
              @if (pairing(); as p) {
                <div class="text-center">
                  <img class="mx-auto size-56 rounded bg-white p-2" [src]="p.qr" [alt]="'phone.qrAlt' | t">
                  <p class="hint">{{ 'phone.expires' | t: { n: minutesLeft() } }}</p>
                </div>
              } @else {
                <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="pair()">{{ 'remote.newCode' | t }}</button>
              }
            } @else if (s.error) {
              <div class="alert alert-error" role="alert" dir="auto">{{ s.error }}</div>
            } @else {
              <p class="text-sm text-slate-500" role="status">{{ 'phone.connecting' | t }}</p>
            }

            <div class="border-t border-slate-100 pt-4 dark:border-slate-800">
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

            <details class="text-sm">
              <summary class="cursor-pointer">{{ 'phone.relay' | t }}</summary>
              <input id="phone-relay" class="input mt-2" dir="ltr" placeholder="https://" [attr.aria-label]="'phone.relay' | t"
                     [value]="relay()" (input)="relay.set(val($event))" (change)="save(true)">
              <p class="hint">{{ 'phone.relayHint' | t }}</p>
            </details>
            @if (s.enabled) {
              <button type="button" class="btn" [disabled]="busy()" (click)="turnOff()">{{ 'remote.off' | t }}</button>
            }
          }
        } @else if (!error()) {
          <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
        }
      </div>
    </dialog>
  `,
})
export class RemoteControl implements OnDestroy {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly box = viewChild.required<ElementRef<HTMLDialogElement>>('box');
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
  private autoPair = false; // one QR code per opening; after it expires, a button makes the next

  /** Open the popup: on the PC this turns the tunnel on, then the QR code shows once it is online. */
  async open(): Promise<void> {
    this.box().nativeElement.showModal();
    this.error.set('');
    this.autoPair = !REMOTE;
    if (REMOTE && this.pushSupported) {
      void navigator.serviceWorker.getRegistration().then(async (reg) => this.push.set(!!(await reg?.pushManager.getSubscription())));
    }
    await this.load();
    const s = this.status();
    if (s && !REMOTE && !s.enabled) await this.save(true);
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
      if (!this.box().nativeElement.open) return;
      // still connecting: look again shortly (the tunnel needs a few seconds to reach a relay)
      if (s.enabled && !s.online && !s.error) setTimeout(() => void this.load(), 2000);
      else if (s.online && this.autoPair && !this.pairing()) await this.pair();
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  protected async save(enabled: boolean): Promise<void> {
    await this.run(async () => {
      this.stop();
      this.status.set(await this.api.put<PhoneStatus>('/phone/remote', { enabled, relay: this.relay().trim() }));
    });
    if (enabled) await this.load();
  }

  protected async turnOff(): Promise<void> {
    this.autoPair = false;
    await this.save(false);
  }

  /** Show a fresh code; while it shows, look for the new phone every 3 s and hide the code once it has paired. */
  protected async pair(): Promise<void> {
    this.autoPair = false;
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

  protected stop(): void {
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
