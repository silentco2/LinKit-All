import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { TPipe } from '../i18n';
import { REMOTE } from '../remote';

/** The phone's first page (docs/phone.md): the QR code opens /pair#CODE; the code is traded for the device cookie. */
@Component({
  selector: 'app-pair',
  imports: [RouterLink, TPipe],
  template: `
    <div class="mx-auto max-w-md">
      <h1>{{ 'pair.title' | t }}</h1>
      @if (remote) {
        <p class="mt-2 text-sm text-slate-600 dark:text-slate-400">{{ 'pair.intro' | t }}</p>
        <form class="card mt-6 space-y-4" (submit)="claim($event)">
          <div>
            <label class="label" for="pair-code">{{ 'pair.code' | t }}</label>
            <input id="pair-code" class="input font-mono tracking-widest" dir="ltr" maxlength="16" autocomplete="one-time-code"
                   autocapitalize="characters" spellcheck="false" [value]="code()" (input)="code.set(val($event))">
          </div>
          <div>
            <label class="label" for="pair-name">{{ 'pair.name' | t }}</label>
            <input id="pair-name" class="input" dir="auto" maxlength="80" [value]="name()" (input)="name.set(val($event))">
          </div>
          @if (error()) { <div class="alert alert-error" role="alert" dir="auto">{{ error() }}</div> }
          <button type="submit" class="btn btn-primary" [disabled]="busy() || !code().trim()">{{ 'pair.go' | t }}</button>
        </form>
      } @else {
        <p class="mt-2 text-sm">{{ 'pair.onPc' | t }}</p>
        <a class="btn mt-4" routerLink="/settings/phone">{{ 'pair.toSettings' | t }}</a>
      }
    </div>
  `,
})
export class PairPage {
  private readonly api = inject(Api);
  protected readonly remote = REMOTE;
  protected readonly code = signal(location.hash.slice(1));
  protected readonly name = signal(/iPhone|iPad/.test(navigator.userAgent) ? 'iPhone' : /Android/.test(navigator.userAgent) ? 'Android' : '');
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  constructor() {
    // the code is spent once used; keep it out of the address bar and history either way
    if (location.hash) history.replaceState(null, '', location.pathname);
  }

  protected async claim(e: Event): Promise<void> {
    e.preventDefault();
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.post('/phone/claim', { code: this.code(), name: this.name() });
      location.assign('/'); // a fresh start: the live connection and every page now carry the cookie
    } catch (err) {
      this.error.set((err as Error).message);
      this.busy.set(false);
    }
  }

  protected val = (e: Event): string => (e.target as HTMLInputElement).value;
}
