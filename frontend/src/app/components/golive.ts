import { Component, inject, OnInit, output, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { SettingsStore } from '../pages/settings/store';
import { Shell } from '../shell';
import { GoLive, SearchConfig } from '../types';

type Check = keyof GoLive['checklist'];
/** Each checklist line, and the Settings page that fixes it. */
const CHECKS: { id: Check; label: string; link: string }[] = [
  { id: 'cv_approved', label: 'golive.check.cv', link: '/settings/profile' },
  { id: 'answers_reviewed', label: 'golive.check.answers', link: '/settings/answers' },
  { id: 'caps_set', label: 'golive.check.caps', link: '/settings/applying' },
  { id: 'confirm_each', label: 'golive.check.confirm', link: '/settings/applying' },
];

/**
 * "Ready to apply for real?" (ux-plan 8.2): filled-form screenshots from practice runs, a checklist, and the one button
 * that turns real applications on after a final confirm that names the action. Used on Home and in Settings > Applying.
 */
@Component({
  selector: 'app-golive',
  imports: [RouterLink, TPipe],
  template: `
    @if (error()) { <div class="alert alert-error mb-3" role="alert" dir="auto">{{ error() }}</div> }
    @if (data(); as d) {
      @if (on()) {
        <div class="alert alert-ok" role="status">{{ 'golive.on' | t }}</div>
      } @else if (!d.eligible) {
        <div class="alert alert-info" role="status">{{ 'golive.notEligible' | t }}</div>
        <div class="mt-3"><button type="button" class="btn" (click)="cancel.emit()">{{ 'golive.notNow' | t }}</button></div>
      } @else {
        <div class="space-y-4">
          <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'golive.intro' | t }}</p>
          <ul class="grid gap-3 sm:grid-cols-3">
            @for (s of d.samples; track s.job_id) {
              <li class="min-w-0 text-sm">
                @if (s.screenshots[0]; as shot) {
                  <a [href]="shot" target="_blank" rel="noopener noreferrer" [attr.aria-label]="'golive.open' | t">
                    <img [src]="shot" [alt]="s.title" loading="lazy" class="h-32 w-full rounded-lg border border-slate-200 object-cover object-top dark:border-slate-700">
                  </a>
                }
                <p class="mt-1 truncate font-medium" dir="auto">{{ s.title }}</p>
                <p class="truncate text-xs text-slate-500" dir="auto">{{ s.company }}</p>
                @if (s.tailored) { <span class="badge tier-high mt-1">{{ 'golive.tailored' | t }}</span> }
              </li>
            }
          </ul>

          <ul class="space-y-1.5 text-sm" [attr.aria-label]="'golive.checklist' | t">
            @for (c of checks; track c.id) {
              <li class="flex flex-wrap items-center gap-x-2">
                @if (d.checklist[c.id]) {
                  <span class="font-bold text-emerald-600 dark:text-emerald-400" aria-hidden="true">✓</span><span class="sr-only">{{ 'golive.done' | t }}:</span>
                } @else {
                  <span class="font-bold text-rose-600 dark:text-rose-400" aria-hidden="true">✗</span><span class="sr-only">{{ 'golive.todo' | t }}:</span>
                }
                <span>{{ c.label | t }}</span>
                @if (!d.checklist[c.id]) { <a [routerLink]="c.link">{{ 'golive.fix' | t }}</a> }
              </li>
            }
          </ul>

          @if (confirming()) {
            <div class="alert alert-error" role="alertdialog" [attr.aria-label]="'golive.confirm' | t">
              <p><strong>{{ 'golive.confirm' | t }}</strong> {{ 'golive.confirmBody' | t }}</p>
              <div class="mt-3 flex flex-wrap gap-2">
                <button type="button" class="btn btn-primary" (click)="turnOn()" [disabled]="busy()">{{ 'golive.confirmYes' | t }}</button>
                <button type="button" class="btn" (click)="confirming.set(false)" [disabled]="busy()">{{ 'golive.confirmNo' | t }}</button>
              </div>
            </div>
          } @else {
            <div class="flex flex-wrap items-center gap-3">
              <button type="button" class="btn btn-primary" [disabled]="!ready(d) || busy()" (click)="confirming.set(true)">{{ 'golive.turnOn' | t }}</button>
              <button type="button" class="btn" (click)="cancel.emit()">{{ 'golive.notNow' | t }}</button>
              @if (!ready(d)) { <span class="hint mt-0">{{ 'golive.needs' | t }}</span> }
            </div>
          }
        </div>
      }
    } @else if (!error()) {
      <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
    }
  `,
})
export class GoLiveCard implements OnInit {
  private readonly api = inject(Api);
  private readonly shell = inject(Shell);
  private readonly store = inject(SettingsStore);
  private readonly i18n = inject(I18n);
  /** Real applications were just turned on (the status then says live, so the host keeps this card to show the message). */
  readonly enabled = output<void>();
  readonly cancel = output<void>();
  protected readonly data = signal<GoLive | null>(null);
  protected readonly error = signal('');
  protected readonly confirming = signal(false);
  protected readonly busy = signal(false);
  protected readonly on = signal(false);
  protected readonly checks = CHECKS;

  async ngOnInit(): Promise<void> {
    try {
      const d = await this.api.get<GoLive>('/golive');
      this.data.set(d);
      this.on.set(d.live);
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  /** The CV and "confirm each submission" are required; answers and daily limits are shown but advisory. */
  protected ready = (d: GoLive): boolean => d.checklist.cv_approved && d.checklist.confirm_each;

  protected async turnOn(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      if (this.store.loaded()) await this.viaStore();
      else {
        // the whole config is one document: read it fresh so other pages' edits are not overwritten
        const cfg = await this.api.get<SearchConfig>('/search');
        await this.api.put('/search', { ...cfg, apply: { ...cfg.apply, live: true } });
      }
      await this.shell.refresh(); // the header badge flips
      this.on.set(true);
      this.confirming.set(false);
      this.enabled.emit();
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  /** The settings store keeps its own copy of the config and saves it whole, so the change has to go through it. */
  private async viaStore(): Promise<void> {
    this.store.update('apply.live', true);
    for (let i = 0; i < 50; i++) { // the store saves about 400 ms after an edit
      await new Promise((r) => setTimeout(r, 100));
      const f = this.store.fields()['apply.live'];
      if (f?.state === 'saved') return;
      if (f?.state === 'error') {
        this.store.update('apply.live', false);
        throw new Error(f.error);
      }
    }
    throw new Error(this.i18n.t('settings.err.network'));
  }
}
