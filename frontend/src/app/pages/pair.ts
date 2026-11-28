import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { TPipe } from '../i18n';
import { hasPc, pendingCode, savePairing } from '../net';
import { REMOTE } from '../remote';

type Step = 'pairing' | 'homeScreen' | 'scan' | 'unpaired' | 'failed';

/**
 * The phone's first page (docs/phone.md). The QR code on the PC opens
 * linkit-all.github.io/app/#pc=..&code=..&relay=..; this page trades the code for the token at
 * once, no typing. An iPhone pairs in its Home Screen copy (it keeps its own storage), so
 * Safari first asks for Add to Home Screen.
 */
@Component({
  selector: 'app-pair',
  imports: [RouterLink, TPipe],
  template: `
    <div class="mx-auto max-w-md">
      <h1>{{ (step() === 'homeScreen' ? 'pair.home.title' : 'pair.title') | t }}</h1>
      @if (remote) {
        @switch (step()) {
          @case ('pairing') { <p class="mt-3" role="status">{{ 'pair.intro' | t }}</p> }
          @case ('homeScreen') { <p class="mt-3">{{ 'pair.home.steps' | t }}</p> }
          @case ('scan') { <p class="mt-3">{{ 'pair.scan' | t }}</p> }
          @case ('unpaired') { <p class="mt-3">{{ 'pair.unpaired' | t }}</p> }
          @case ('failed') {
            <div class="alert alert-error mt-3" role="alert" dir="auto">{{ error() }}</div>
            <p class="mt-3 text-sm">{{ 'pair.scan' | t }}</p>
            <button type="button" class="btn mt-3" (click)="claim()">{{ 'pair.retry' | t }}</button>
          }
        }
      } @else {
        <p class="mt-2 text-sm">{{ 'pair.onPc' | t }}</p>
        <a class="btn mt-4" routerLink="/home">{{ 'pair.toSettings' | t }}</a>
      }
    </div>
  `,
})
export class PairPage implements OnInit {
  private readonly api = inject(Api);
  protected readonly remote = REMOTE;
  protected readonly step = signal<Step>('pairing');
  protected readonly error = signal('');
  private readonly code = pendingCode();

  ngOnInit(): void {
    if (!REMOTE) return;
    const iphone = /iPhone|iPad/.test(navigator.userAgent);
    const homeScreen = (navigator as { standalone?: boolean }).standalone === true || matchMedia('(display-mode: standalone)').matches;
    if (!this.code) this.step.set(hasPc() ? 'unpaired' : 'scan');
    else if (iphone && !homeScreen) this.step.set('homeScreen');
    else void this.claim();
  }

  protected async claim(): Promise<void> {
    this.step.set('pairing');
    try {
      const name = /iPhone/.test(navigator.userAgent) ? 'iPhone' : /iPad/.test(navigator.userAgent) ? 'iPad' : /Android/.test(navigator.userAgent) ? 'Android' : 'Phone';
      const { token } = await this.api.post<{ id: number; token: string }>('/phone/claim', { code: this.code, name });
      savePairing(token);
      location.assign(document.baseURI); // a fresh start: the live view and every page now carry the token
    } catch (e) {
      this.error.set((e as Error).message);
      this.step.set('failed');
    }
  }
}
