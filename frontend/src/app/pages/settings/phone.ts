import { Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { Api } from '../../api';
import { TPipe } from '../../i18n';
import { DtPipe } from '../../locale';
import { REMOTE } from '../../remote';

interface PhoneDevice { id: number; name: string; created: string; last_seen: string }
interface PhoneStatus {
  enabled: boolean;
  host: string;
  address: string;
  this_device: number | null;
  devices?: PhoneDevice[];
  detected_host?: string;
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
        } @else {
          <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'phone.intro' | t }} <a [href]="guide" target="_blank" rel="noopener">{{ 'phone.guide' | t }}</a></p>
          <div class="space-y-3">
            <label class="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" [checked]="enabled()" (change)="enabled.set(checked($event))"> {{ 'phone.enable' | t }}
            </label>
            <div>
              <label class="label" for="phone-host">{{ 'phone.host' | t }}</label>
              <input id="phone-host" class="input" dir="ltr" placeholder="pc.tail1234.ts.net" [value]="host()" (input)="host.set(val($event))">
              <p class="hint">{{ 'phone.hostHint' | t }}</p>
            </div>
            <button type="button" class="btn" [disabled]="busy()" (click)="save()">{{ 'phone.save' | t }}</button>
          </div>

          @if (s.enabled) {
            <div class="border-t border-slate-100 pt-5 dark:border-slate-800">
              <h3 class="font-semibold">{{ 'phone.pairTitle' | t }}</h3>
              @if (pairing(); as p) {
                <img class="mt-3 size-56 rounded bg-white p-2" [src]="p.qr" [alt]="'phone.qrAlt' | t">
                <p class="mt-2 text-sm">{{ 'phone.codeIs' | t }} <span class="font-mono text-lg tracking-widest whitespace-nowrap" dir="ltr">{{ p.code.slice(0, 4) }}-{{ p.code.slice(4) }}</span></p>
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
  protected readonly remote = REMOTE;
  protected readonly guide = GUIDE;
  protected readonly status = signal<PhoneStatus | null>(null);
  protected readonly enabled = signal(false);
  protected readonly host = signal('');
  protected readonly pairing = signal<PairCode | null>(null);
  protected readonly minutesLeft = signal(5);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  private timer: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    void this.load();
  }

  ngOnDestroy(): void {
    this.stop();
  }

  private async load(): Promise<void> {
    try {
      const s = await this.api.get<PhoneStatus>('/phone');
      this.status.set(s);
      this.enabled.set(s.enabled);
      if (!this.host()) this.host.set(s.host || s.detected_host || '');
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  protected async save(): Promise<void> {
    await this.run(async () => {
      this.status.set(await this.api.put<PhoneStatus>('/phone/remote', { enabled: this.enabled(), host: this.host() }));
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
