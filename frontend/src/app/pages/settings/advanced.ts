import { Component, inject, input, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../../api';
import { I18n, TPipe } from '../../i18n';
import { lines, unlines } from '../../types';
import { Field } from './saved';
import { SettingsStore } from './store';
import { cardClass, Tuning } from './tuning';

const MATCHING = ['matching.tier_high', 'matching.tier_mid', 'matching.ai_max_jobs', 'matching.batch_size', 'matching.auto_apply_low', 'filters.title_include', 'search.max_results_per_query'];
const APPLYING = ['apply.max_per_run', 'apply.daily_cap_per_site', 'apply.min_pause_s', 'apply.max_pause_s', 'apply.parallel_sites', 'apply.submit_without_asking'];
const TRUST = ['trust.enabled', 'trust.scam_threshold', 'trust.ghost_threshold', 'trust.filter_ghost', 'trust.allow_companies'];
const DISCOVERY = ['sources.boards_per_run'];

/** "Changed" and "Reset to preset / default" under one field, when its value is not the preset's or the default. */
@Component({
  selector: 'app-changed',
  imports: [TPipe],
  template: `
    @if (tuning.changed(key())) {
      <p class="mt-1 flex items-center gap-2 text-xs">
        <span class="badge bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200">{{ 'settings.adv.changed' | t }}</span>
        <button type="button" class="text-brand-700 underline dark:text-brand-100" [attr.aria-label]="aria()" (click)="tuning.reset(key())">{{ resetKey() | t }}</button>
      </p>
    }
  `,
})
export class Changed {
  protected readonly tuning = inject(Tuning);
  private readonly i18n = inject(I18n);
  readonly key = input.required<string>();
  /** The field's label, for the screen-reader name of the reset button. */
  readonly label = input.required<string>();

  protected resetKey(): string {
    return this.tuning.isPreset(this.key()) ? 'settings.adv.resetPreset' : 'settings.adv.resetDefault';
  }

  protected aria(): string {
    return `${this.i18n.t(this.resetKey())}: ${this.label()}`;
  }
}

/** Settings > Advanced: the raw numbers behind the presets, in collapsed groups. Changed values are marked and can be reset. */
@Component({
  selector: 'app-settings-advanced',
  imports: [Field, Changed, RouterLink, TPipe],
  template: `
    <div class="space-y-4">
      <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'settings.adv.intro' | t }}</p>
      @if (tuning.data(); as p) {
        <details class="card">
          <summary [class]="summary">{{ 'settings.adv.matching' | t }}@if (count(matching) > 0) { <span class="ms-2 text-xs font-normal text-amber-700 dark:text-amber-300">{{ 'settings.adv.nChanged' | t: { n: count(matching) } }}</span> }</summary>
          <div class="mt-4 space-y-5">
            <app-field key="matching.tier_high" [label]="'settings.adv.pickiness' | t" [hint]="'settings.adv.pickinessHint' | t">
              <div class="grid gap-3 sm:grid-cols-3" role="radiogroup" [attr.aria-label]="'settings.adv.pickiness' | t">
                @for (n of names(p.pickiness); track n) {
                  <label [class]="card(pickNow() === n)">
                    <input type="radio" name="pickiness" class="sr-only" [checked]="pickNow() === n" (change)="tuning.pick('pickiness', n)">
                    <span class="block font-medium">{{ 'settings.adv.pickiness.' + n | t }}</span>
                    <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400" dir="auto">{{ 'settings.adv.pickLine' | t: { high: p.pickiness[n]['tier_high'], mid: p.pickiness[n]['tier_mid'] } }}</span>
                  </label>
                }
              </div>
              @if (!pickNow()) {
                <div [class]="card(true) + ' mt-3'" role="status">
                  <span class="block font-medium">{{ 'settings.apply.custom' | t }}</span>
                  <span class="mt-1 block text-xs text-slate-500 dark:text-slate-400">{{ 'settings.adv.customHint' | t }}</span>
                </div>
              }
            </app-field>

            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <app-field key="matching.tier_high" for="adv-high" [label]="'settings.adv.high' | t" [hint]="'settings.adv.highHint' | t: { from: store.cfg.matching.tier_high }">
                  <input id="adv-high" type="number" min="1" max="10" class="input" [value]="store.cfg.matching.tier_high" (change)="store.update('matching.tier_high', num($event))">
                </app-field>
                <app-changed key="matching.tier_high" [label]="'settings.adv.high' | t" />
              </div>
              <div>
                <app-field key="matching.tier_mid" for="adv-mid" [label]="'settings.adv.mid' | t" [hint]="'settings.adv.midHint' | t: { from: store.cfg.matching.tier_mid, to: store.cfg.matching.tier_high - 1 }">
                  <input id="adv-mid" type="number" min="1" max="10" class="input" [value]="store.cfg.matching.tier_mid" (change)="store.update('matching.tier_mid', num($event))">
                </app-field>
                <app-changed key="matching.tier_mid" [label]="'settings.adv.mid' | t" />
              </div>
              <div>
                <app-field key="matching.ai_max_jobs" for="adv-aimax" [label]="'setup.scoring.aimax' | t" [hint]="'settings.adv.aimaxHint' | t">
                  <input id="adv-aimax" type="number" min="0" class="input" [value]="store.cfg.matching.ai_max_jobs" (change)="store.update('matching.ai_max_jobs', num($event))">
                </app-field>
                <app-changed key="matching.ai_max_jobs" [label]="'setup.scoring.aimax' | t" />
              </div>
              <div>
                <app-field key="matching.batch_size" for="adv-batch" [label]="'setup.scoring.batch' | t">
                  <input id="adv-batch" type="number" min="1" max="30" class="input" [value]="store.cfg.matching.batch_size" (change)="store.update('matching.batch_size', num($event))">
                </app-field>
                <app-changed key="matching.batch_size" [label]="'setup.scoring.batch' | t" />
              </div>
            </div>

            <div>
              <app-field key="matching.auto_apply_low" for="adv-low" [check]="true" [label]="'settings.adv.low' | t">
                <input id="adv-low" type="checkbox" class="mt-1" [checked]="store.cfg.matching.auto_apply_low" (change)="store.update('matching.auto_apply_low', checked($event))">
              </app-field>
              @if (store.cfg.matching.auto_apply_low) { <div class="alert alert-error mt-2" role="note">{{ 'settings.adv.lowWarn' | t }}</div> }
              <app-changed key="matching.auto_apply_low" [label]="'settings.adv.low' | t" />
            </div>

            <div>
              <app-field key="filters.title_include" for="adv-inc" [label]="'setup.filters.include' | t" [hint]="'settings.oneLine' | t">
                <textarea id="adv-inc" dir="auto" class="input h-24" [value]="unlines(store.cfg.filters.title_include)" (change)="store.update('filters.title_include', lines(val($event)))" placeholder="engineer&#10;developer"></textarea>
              </app-field>
              <app-changed key="filters.title_include" [label]="'setup.filters.include' | t" />
            </div>

            <div class="max-w-xs">
              <app-field key="search.max_results_per_query" for="adv-max" [label]="'setup.search.max' | t">
                <input id="adv-max" type="number" min="1" max="1000" class="input" [value]="store.cfg.search.max_results_per_query" (change)="store.update('search.max_results_per_query', num($event))">
              </app-field>
              <app-changed key="search.max_results_per_query" [label]="'setup.search.max' | t" />
            </div>
          </div>
        </details>

        <details class="card">
          <summary [class]="summary">{{ 'settings.adv.applying' | t }}@if (count(applying) > 0) { <span class="ms-2 text-xs font-normal text-amber-700 dark:text-amber-300">{{ 'settings.adv.nChanged' | t: { n: count(applying) } }}</span> }</summary>
          <div class="mt-4 space-y-5">
            <p class="hint">{{ 'settings.adv.paceNote' | t }} <a routerLink="/settings/applying">{{ 'settings.s.applying' | t }}</a></p>
            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <app-field key="apply.max_per_run" for="adv-run" [label]="'setup.apply.maxRun' | t">
                  <input id="adv-run" type="number" min="1" max="100" class="input" [value]="store.cfg.apply.max_per_run" (change)="store.update('apply.max_per_run', num($event))">
                </app-field>
                <app-changed key="apply.max_per_run" [label]="'setup.apply.maxRun' | t" />
              </div>
              <div>
                <app-field key="apply.daily_cap_per_site" for="adv-day" [label]="'setup.apply.daily' | t" [hint]="'setup.apply.dailyHint' | t">
                  <input id="adv-day" type="number" min="1" max="200" class="input" [value]="store.cfg.apply.daily_cap_per_site" (change)="store.update('apply.daily_cap_per_site', num($event))">
                </app-field>
                <app-changed key="apply.daily_cap_per_site" [label]="'setup.apply.daily' | t" />
              </div>
              <div>
                <app-field key="apply.min_pause_s" for="adv-min" [label]="'setup.apply.minPause' | t">
                  <input id="adv-min" type="number" min="0" class="input" [value]="store.cfg.apply.min_pause_s" (change)="store.update('apply.min_pause_s', num($event))">
                </app-field>
                <app-changed key="apply.min_pause_s" [label]="'setup.apply.minPause' | t" />
              </div>
              <div>
                <app-field key="apply.max_pause_s" for="adv-maxp" [label]="'setup.apply.maxPause' | t" [hint]="'setup.apply.pauseHint' | t">
                  <input id="adv-maxp" type="number" min="0" class="input" [value]="store.cfg.apply.max_pause_s" (change)="store.update('apply.max_pause_s', num($event))">
                </app-field>
                <app-changed key="apply.max_pause_s" [label]="'setup.apply.maxPause' | t" />
              </div>
            </div>
            @if (pauseInvalid()) { <p class="text-sm text-rose-700 dark:text-rose-400" role="alert">{{ 'setup.apply.pauseInvalid' | t }}</p> }
            <div class="max-w-xs">
              <app-field key="apply.parallel_sites" for="adv-par" [label]="'setup.apply.parallel' | t" [hint]="'setup.apply.parallelHint' | t">
                <input id="adv-par" type="number" min="1" max="3" class="input" [value]="store.cfg.apply.parallel_sites" (change)="store.update('apply.parallel_sites', num($event))">
              </app-field>
              <app-changed key="apply.parallel_sites" [label]="'setup.apply.parallel' | t" />
            </div>

            <div>
              <app-field key="apply.submit_without_asking" for="adv-noask" [check]="true" [label]="'setup.apply.noAsk' | t" [hint]="'settings.adv.noAskHint' | t">
                <input id="adv-noask" type="checkbox" class="mt-1" [disabled]="!store.cfg.apply.live" [checked]="store.cfg.apply.submit_without_asking" (change)="noAsk($event)">
              </app-field>
              @if (store.cfg.apply.live && store.cfg.apply.submit_without_asking) {
                <div class="alert alert-error mt-2" role="alert"><strong>{{ 'setup.apply.noConfirmTitle' | t }}</strong> {{ 'setup.apply.noConfirmBody' | t }}</div>
              }
              <app-changed key="apply.submit_without_asking" [label]="'setup.apply.noAsk' | t" />
            </div>
          </div>
        </details>

        <details class="card">
          <summary [class]="summary">{{ 'settings.adv.trust' | t }}@if (count(trust) > 0) { <span class="ms-2 text-xs font-normal text-amber-700 dark:text-amber-300">{{ 'settings.adv.nChanged' | t: { n: count(trust) } }}</span> }</summary>
          <div class="mt-4 space-y-5">
            <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'settings.adv.trustIntro' | t }}</p>
            <div>
              <app-field key="trust.enabled" for="adv-tr" [check]="true" [label]="'settings.adv.trustOn' | t">
                <input id="adv-tr" type="checkbox" class="mt-1" [checked]="store.cfg.trust.enabled" (change)="store.update('trust.enabled', checked($event))">
              </app-field>
              <app-changed key="trust.enabled" [label]="'settings.adv.trustOn' | t" />
            </div>
            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <app-field key="trust.scam_threshold" for="adv-scam" [label]="'setup.trust.scam' | t" [hint]="'setup.trust.scamHint' | t">
                  <input id="adv-scam" type="number" min="1" max="100" class="input" [value]="store.cfg.trust.scam_threshold" (change)="store.update('trust.scam_threshold', num($event))">
                </app-field>
                <app-changed key="trust.scam_threshold" [label]="'setup.trust.scam' | t" />
              </div>
              <div>
                <app-field key="trust.ghost_threshold" for="adv-ghost" [label]="'settings.adv.stale' | t" [hint]="'settings.adv.staleHint' | t">
                  <input id="adv-ghost" type="number" min="1" max="100" class="input" [value]="store.cfg.trust.ghost_threshold" (change)="store.update('trust.ghost_threshold', num($event))">
                </app-field>
                <app-changed key="trust.ghost_threshold" [label]="'settings.adv.stale' | t" />
              </div>
            </div>
            <div>
              <app-field key="trust.filter_ghost" for="adv-fg" [check]="true" [label]="'settings.adv.filterStale' | t">
                <input id="adv-fg" type="checkbox" class="mt-1" [checked]="store.cfg.trust.filter_ghost" (change)="store.update('trust.filter_ghost', checked($event))">
              </app-field>
              <app-changed key="trust.filter_ghost" [label]="'settings.adv.filterStale' | t" />
            </div>
            <div>
              <app-field key="trust.allow_companies" for="adv-allow" [label]="'setup.trust.allow' | t" [hint]="'setup.trust.allowHint' | t">
                <textarea id="adv-allow" dir="auto" class="input h-24" [value]="unlines(store.cfg.trust.allow_companies)" (change)="store.update('trust.allow_companies', lines(val($event)))"></textarea>
              </app-field>
              <app-changed key="trust.allow_companies" [label]="'setup.trust.allow' | t" />
            </div>
            <div class="space-y-2">
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="filterStale()">{{ 'settings.adv.staleNow' | t }}</button>
              <div aria-live="polite" role="status">
                @if (result(); as r) { <p class="text-sm" [class]="r.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'" dir="auto">{{ r.text }}</p> }
              </div>
            </div>
          </div>
        </details>

        <details class="card">
          <summary [class]="summary">{{ 'settings.adv.discovery' | t }}@if (count(discovery) > 0) { <span class="ms-2 text-xs font-normal text-amber-700 dark:text-amber-300">{{ 'settings.adv.nChanged' | t: { n: count(discovery) } }}</span> }</summary>
          <div class="mt-4 max-w-xs">
            <app-field key="sources.boards_per_run" for="adv-boards" [label]="'setup.sources.perRun' | t">
              <input id="adv-boards" type="number" min="0" max="20000" class="input" [value]="store.cfg.sources.boards_per_run" (change)="store.update('sources.boards_per_run', num($event))">
            </app-field>
            <app-changed key="sources.boards_per_run" [label]="'setup.sources.perRun' | t" />
          </div>
        </details>
      } @else if (tuning.error(); as e) {
        <div class="alert alert-error" role="alert" dir="auto">{{ e }}
          <button type="button" class="btn ms-2" (click)="tuning.load()">{{ 'welcome.retry' | t }}</button>
        </div>
      } @else {
        <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
      }
    </div>
  `,
})
export class AdvancedSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  protected readonly tuning = inject(Tuning);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly lines = lines;
  protected readonly unlines = unlines;
  protected readonly card = cardClass;
  protected readonly summary = 'cursor-pointer text-base font-semibold';
  protected readonly matching = MATCHING;
  protected readonly applying = APPLYING;
  protected readonly trust = TRUST;
  protected readonly discovery = DISCOVERY;
  protected readonly busy = signal(false);
  protected readonly result = signal<{ ok: boolean; text: string } | null>(null);

  ngOnInit(): void {
    void this.tuning.load();
  }

  protected count(keys: string[]): number {
    return keys.filter((k) => this.tuning.changed(k)).length;
  }

  protected pickNow(): string | null {
    return this.tuning.matching('pickiness');
  }

  protected names(set: Record<string, unknown>): string[] {
    return Object.keys(set);
  }

  protected val(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  /** The number in the box; an empty box is NaN, which the server rejects with a message for this field. */
  protected num(e: Event): number {
    const box = e.target as HTMLInputElement;
    return box.value.trim() === '' ? NaN : box.valueAsNumber;
  }

  protected pauseInvalid(): boolean {
    const a = this.store.cfg.apply;
    return a.min_pause_s > a.max_pause_s;
  }

  /** Ticking asks first; a "no" puts the box back as it was. */
  protected noAsk(e: Event): void {
    const box = e.target as HTMLInputElement;
    if (!this.tuning.setNoAsk(box.checked)) box.checked = false;
  }

  /** Bulk-filter stored jobs at the saved stale threshold, after a confirmation; shows how many were filtered. */
  protected async filterStale(): Promise<void> {
    const n = this.store.cfg.trust.ghost_threshold;
    if (!confirm(this.i18n.t('settings.adv.staleConfirm', { n }))) return;
    this.busy.set(true);
    this.result.set(null);
    try {
      const r = await this.api.filterGhost(n);
      this.result.set({ ok: true, text: this.i18n.t('settings.adv.staleDone', { n: r.count }) });
    } catch (e) {
      this.result.set({ ok: false, text: (e as Error).message });
    } finally {
      this.busy.set(false);
    }
  }
}
