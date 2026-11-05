import { Component, computed, inject, Injectable, OnInit, signal } from '@angular/core';
import { Api, ApiError } from '../api';
import { I18n, TPipe } from '../i18n';
import { fmtNum, localeOf } from '../locale';
import { SettingsStore } from '../pages/settings/store';
import { Shell } from '../shell';
import { LibreOfficeStatus, SearchConfig } from '../types';

/**
 * LibreOffice is optional: it lets LinKit tailor the CV for each job. This holds what the card and the Applying
 * switch share: the install status, and the choice `apply.tailor_cv` (null = not decided, true = tailor, false = send my CV as it is).
 */
@Injectable({ providedIn: 'root' })
export class LibreOffice {
  private readonly api = inject(Api);
  private readonly shell = inject(Shell);
  private readonly store = inject(SettingsStore);
  readonly info = signal<LibreOfficeStatus | null>(null);
  /** undefined until the first load. */
  readonly tailor = signal<boolean | null | undefined>(undefined);
  readonly error = signal('');
  readonly justInstalled = signal(false);
  private timer: ReturnType<typeof setTimeout> | undefined;

  async load(): Promise<void> {
    try {
      const [info, tailor] = await Promise.all([this.api.get<LibreOfficeStatus>('/tools/libreoffice'), this.readTailor()]);
      this.info.set(info);
      this.tailor.set(tailor);
      if (info.installing) this.poll();
    } catch {
      // the card then stays hidden; the next page load tries again
    }
  }

  private async readTailor(): Promise<boolean | null> {
    const cfg = this.store.loaded() ? this.store.cfg : await this.api.get<SearchConfig>('/search');
    return cfg.apply.tailor_cv ?? null;
  }

  /** Save the choice. Through the settings store when it is loaded: it keeps its own copy of the config and saves it whole. */
  async setTailor(value: boolean | null): Promise<void> {
    this.tailor.set(value);
    this.error.set('');
    try {
      if (this.store.loaded()) this.store.update('apply.tailor_cv', value);
      else {
        const cfg = await this.api.get<SearchConfig>('/search'); // fresh: do not overwrite other pages' edits
        await this.api.put('/search', { ...cfg, apply: { ...cfg.apply, tailor_cv: value } });
      }
      await this.shell.refresh();
    } catch (e) {
      this.error.set((e as Error).message);
      await this.load();
    }
  }

  async install(): Promise<void> {
    this.error.set('');
    try {
      await this.api.post('/tools/libreoffice/install');
    } catch (e) {
      if (e instanceof ApiError && e.code === 'lo_not_available') await this.load(); // no download yet: the card now offers "Get LibreOffice"
      else this.error.set((e as Error).message);
      return;
    }
    this.poll();
  }

  private poll(): void {
    clearTimeout(this.timer);
    const tick = async (): Promise<void> => {
      try {
        const info = await this.api.get<LibreOfficeStatus>('/tools/libreoffice');
        this.info.set(info);
        if (info.installing) this.timer = setTimeout(() => void tick(), 1000);
        else if (info.installed) {
          this.justInstalled.set(true);
          await this.shell.refresh();
        }
      } catch {
        this.timer = setTimeout(() => void tick(), 2000);
      }
    };
    void tick();
  }

  /** "Check again": the user may have installed it themselves. */
  async recheck(): Promise<boolean> {
    await Promise.all([this.shell.refresh(), this.load()]);
    return !!this.info()?.installed;
  }
}

/** The LibreOffice offer: amber, no terminal commands. Collapses to one line once the user chose to use the CV as it is. */
@Component({
  selector: 'app-libreoffice-card',
  imports: [TPipe],
  template: `
    @if (lo.info(); as info) {
      @if (info.installed) {
        @if (lo.justInstalled()) { <div class="alert alert-ok" role="status">{{ 'lo.installed' | t }}</div> }
      } @else if (lo.tailor() === false) {
        <p class="text-sm text-slate-600 dark:text-slate-400" role="status">{{ 'lo.asIs' | t }} · <button type="button" class="linkish" (click)="lo.setTailor(null)">{{ 'lo.change' | t }}</button></p>
      } @else {
        <div class="alert alert-warn space-y-3" role="region" [attr.aria-label]="'lo.title' | t">
          <p>{{ 'lo.text' | t }}</p>
          @if (info.installing) {
            <div role="status">
              <progress class="block h-2 w-full" max="1" [value]="info.progress" [attr.aria-label]="'lo.installing' | t: { pct: pct() }"></progress>
              <p class="mt-1 text-xs">{{ 'lo.installing' | t: { pct: pct() } }}</p>
            </div>
          } @else {
            <div class="flex flex-wrap items-center gap-3 max-sm:flex-col max-sm:items-stretch">
              @if (info.available) {
                <button type="button" class="btn btn-primary" (click)="lo.install()">{{ 'lo.install' | t }}</button>
              } @else {
                <a class="btn btn-primary no-underline hover:no-underline" href="https://www.libreoffice.org/download/" target="_blank" rel="noopener noreferrer">{{ 'lo.get' | t }}</a>
                <button type="button" class="btn" (click)="check()" [disabled]="checking()">{{ 'lo.check' | t }}</button>
              }
              <button type="button" class="btn" (click)="lo.setTailor(false)">{{ 'lo.decline' | t }}</button>
            </div>
            @if (!info.available) { <p class="text-xs">{{ (notFound() ? 'lo.notFound' : 'lo.getHint') | t }}</p> }
          }
          @if (info.error || lo.error(); as err) { <p class="text-sm font-medium" role="alert" dir="auto">{{ err }}</p> }
        </div>
      }
    }
  `,
})
export class LibreOfficeCard implements OnInit {
  protected readonly lo = inject(LibreOffice);
  private readonly i18n = inject(I18n);
  protected readonly checking = signal(false);
  protected readonly notFound = signal(false);
  protected readonly pct = computed(() => fmtNum(localeOf(this.i18n.lang()), this.lo.info()?.progress ?? 0, { style: 'percent' }));

  ngOnInit(): void {
    void this.lo.load();
  }

  protected async check(): Promise<void> {
    this.checking.set(true);
    this.notFound.set(!(await this.lo.recheck()));
    this.checking.set(false);
  }
}
