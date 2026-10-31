import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { GoLiveCard } from '../../components/golive';
import { I18n, TPipe } from '../../i18n';
import { Field } from './saved';
import { SettingsStore } from './store';
import { cardClass, Tuning } from './tuning';

const MODE = 'rounded-lg border p-3 text-start text-sm focus-visible:outline-2 focus-visible:outline-brand-500';

/** Settings > Applying: practice or real, the pace, and how the browser behaves. Everything saves as you edit. */
@Component({
  selector: 'app-settings-applying',
  imports: [Field, GoLiveCard, RouterLink, TPipe],
  template: `
    <div class="space-y-6">
      <section class="card space-y-4">
        <h2>{{ 'settings.apply.mode' | t }}</h2>
        <app-field key="apply.live" [label]="'settings.apply.modeLabel' | t">
          <div class="grid gap-3 sm:grid-cols-2" role="group" [attr.aria-label]="'settings.apply.modeLabel' | t">
            <button type="button" [class]="modeClass(!live())" [attr.aria-pressed]="!live()" (click)="setLive(false)">
              <span class="block font-medium">{{ 'settings.apply.practice' | t }}</span>
              <span class="block text-xs text-slate-500 dark:text-slate-400">{{ 'settings.apply.practiceHint' | t }}</span>
            </button>
            <button type="button" [class]="modeClass(live())" [attr.aria-pressed]="live()" (click)="setLive(true)">
              <span class="block font-medium">{{ 'settings.apply.real' | t }}</span>
              <span class="block text-xs text-slate-500 dark:text-slate-400">{{ 'settings.apply.realHint' | t }}</span>
            </button>
          </div>
        </app-field>

        @if (guide()) {
          <div class="rounded-lg border border-slate-200 p-4 dark:border-slate-700">
            <h3 class="mb-3 font-semibold">{{ 'golive.title' | t }}</h3>
            <app-golive (enabled)="guide.set(false)" (cancel)="guide.set(false)" />
          </div>
        }

        @if (live()) {
          <div class="alert alert-error" role="note"><strong>{{ 'settings.apply.realWarnTitle' | t }}</strong> {{ 'settings.apply.realWarnBody' | t }}</div>
          <app-field key="apply.submit_without_asking" for="confirm-each" [check]="true" [label]="'settings.apply.confirmEach' | t" [hint]="'settings.apply.confirmEachHint' | t">
            <input id="confirm-each" type="checkbox" class="mt-1" [checked]="!store.cfg.apply.submit_without_asking" (change)="confirmEach($event)">
          </app-field>
          @if (store.cfg.apply.submit_without_asking) {
            <div class="alert alert-error" role="alert"><strong>{{ 'setup.apply.noConfirmTitle' | t }}</strong> {{ 'setup.apply.noConfirmBody' | t }}</div>
          }
        }
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.apply.pace' | t }}</h2>
        @if (tuning.data(); as p) {
          <app-field key="apply.parallel_sites" [label]="'settings.apply.paceLabel' | t" [hint]="'settings.apply.paceHint' | t">
            <div class="grid gap-3 sm:grid-cols-3" role="radiogroup" [attr.aria-label]="'settings.apply.paceLabel' | t">
              @for (n of names(p.pace); track n) {
                <label [class]="card(paceNow() === n)">
                  <input type="radio" name="pace" class="sr-only" [checked]="paceNow() === n" (change)="tuning.pick('pace', n)">
                  <span class="block font-medium">{{ 'settings.apply.pace.' + n | t }}</span>
                  <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400" dir="auto">{{ line(p.pace[n]) }}</span>
                </label>
              }
            </div>
            @if (!paceNow()) {
              <div [class]="card(true) + ' mt-3'" role="status">
                <span class="block font-medium">{{ 'settings.apply.custom' | t }}</span>
                <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400">{{ 'settings.apply.customHint' | t }}
                  <a routerLink="/settings/advanced">{{ 'settings.apply.customLink' | t }}</a></span>
              </div>
            }
          </app-field>
        } @else if (tuning.error(); as e) {
          <div class="alert alert-error" role="alert" dir="auto">{{ e }}
            <button type="button" class="btn ms-2" (click)="tuning.load()">{{ 'welcome.retry' | t }}</button>
          </div>
        } @else {
          <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
        }
      </section>


      <section class="card space-y-4">
        <h2>{{ 'settings.apply.limits' | t }}</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="apply.max_per_run" for="lim-run" [label]="'setup.apply.maxRun' | t">
            <input id="lim-run" type="number" min="1" max="100" class="input" [value]="store.cfg.apply.max_per_run" (change)="store.update('apply.max_per_run', num($event))">
          </app-field>
          <app-field key="apply.daily_cap_per_site" for="lim-day" [label]="'setup.apply.daily' | t" [hint]="'setup.apply.dailyHint' | t">
            <input id="lim-day" type="number" min="1" max="200" class="input" [value]="store.cfg.apply.daily_cap_per_site" (change)="store.update('apply.daily_cap_per_site', num($event))">
          </app-field>
          <app-field key="apply.email_daily_cap" for="lim-mail" [label]="'setup.email.cap' | t" [hint]="'setup.email.capHint' | t">
            <input id="lim-mail" type="number" min="1" max="100" class="input" [value]="store.cfg.apply.email_daily_cap" (change)="store.update('apply.email_daily_cap', num($event))">
          </app-field>
        </div>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.apply.how' | t }}</h2>
        <app-field key="apply.headless" [label]="'settings.apply.browser' | t" [hint]="'settings.apply.showWindowHint' | t">
          <div class="grid gap-3 sm:grid-cols-2" role="radiogroup" [attr.aria-label]="'settings.apply.browser' | t">
            @for (hide of [false, true]; track hide) {
              <label [class]="card(store.cfg.apply.headless === hide)">
                <input type="radio" name="browser" class="sr-only" [checked]="store.cfg.apply.headless === hide" (change)="store.update('apply.headless', hide)">
                <span class="block font-medium">{{ (hide ? 'settings.apply.hideWindow' : 'settings.apply.showWindow') | t }}</span>
              </label>
            }
          </div>
        </app-field>
        <app-field key="apply.generic_agent" for="agent" [check]="true" [label]="'settings.apply.agent' | t" [hint]="'settings.apply.agentHint' | t">
          <input id="agent" type="checkbox" class="mt-1" [checked]="store.cfg.apply.generic_agent" (change)="store.update('apply.generic_agent', checked($event))">
        </app-field>
      </section>
    </div>
  `,
})
export class ApplyingSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  protected readonly tuning = inject(Tuning);
  private readonly i18n = inject(I18n);
  protected readonly card = cardClass;
  /** Switching to "Applying for real" opens the guided card instead of flipping the switch. */
  protected readonly guide = signal(false);

  ngOnInit(): void {
    void this.tuning.load();
  }

  protected live(): boolean {
    return this.store.cfg.apply.live;
  }

  protected paceNow(): string | null {
    return this.tuning.matching('pace');
  }

  protected names(set: Record<string, unknown>): string[] {
    return Object.keys(set);
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  /** The number in the box; an empty box is NaN, which the server rejects with a message for this field. */
  protected num(e: Event): number {
    const box = e.target as HTMLInputElement;
    return box.value.trim() === '' ? NaN : box.valueAsNumber;
  }

  protected modeClass(on: boolean): string {
    return `${MODE} ${on ? 'border-brand-500 bg-brand-50 text-brand-700 dark:bg-slate-800 dark:text-white' : 'border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'}`;
  }

  /** "1 site at a time · 60–120 s between applications · up to 10 a day per site · 5 per search" */
  protected line(v: Record<string, number>): string {
    const t = (k: string) => this.i18n.t(k, { n: v['parallel_sites'], min: v['min_pause_s'], max: v['max_pause_s'], cap: v['daily_cap_per_site'], run: v['max_per_run'] });
    return [t(v['parallel_sites'] === 1 ? 'settings.apply.sitesOne' : 'settings.apply.sitesMany'), t('settings.apply.paceRest')].join(' · ');
  }

  /**
   * Turning real applications on goes through the guided card (ux-plan 8.2), which saves it itself; turning them off is
   * instant. Going back to practice mode also drops "submit without asking", which only means something when applying
   * for real.
   */
  protected setLive(live: boolean): void {
    if (live === this.live()) return;
    this.guide.set(live);
    if (live) return;
    this.store.update('apply.live', live);
    if (!live && this.store.cfg.apply.submit_without_asking) this.store.update('apply.submit_without_asking', false);
  }

  /** The box shows "Confirm each submission"; unticking it asks first, and a "no" puts the tick back. */
  protected confirmEach(e: Event): void {
    const box = e.target as HTMLInputElement;
    if (!this.tuning.setNoAsk(!box.checked)) box.checked = true;
  }
}
