import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { Api } from '../../api';
import { ChipOption, ChipSelect } from '../../components/chip-select';
import { Countries } from '../../components/countries';
import { PlacesList } from '../../components/places-list';
import { TagInput } from '../../components/tag-input';
import { I18n, TPipe } from '../../i18n';
import { expandQueries, Place, WorkMode } from '../../types';
import { Field } from './saved';
import { SettingsStore } from './store';

const WORK_MODES: WorkMode[] = ['remote', 'hybrid', 'onsite'];
const SENIORITIES = ['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'executive'];
const POSTED: [string, number | null, string][] = [
  ['24', 24, 'posted.h24'], ['72', 72, 'posted.d3'], ['168', 168, 'posted.w1'], ['336', 336, 'posted.w2'], ['720', 720, 'posted.m1'], ['any', null, 'posted.any'],
];
const ONE: Record<string, string[]> = Object.fromEntries([...POSTED.map(([k]) => k), 'custom'].map((k) => [k, [k]])); // stable arrays for [selected]
const FALLBACK_CURRENCIES = ['EGP', 'SAR', 'AED', 'QAR', 'KWD', 'BHD', 'OMR', 'JOD', 'USD', 'EUR', 'GBP'];

/** Settings > Jobs & places: what to look for and where. Everything saves as you edit. */
@Component({
  selector: 'app-settings-jobs',
  imports: [ChipSelect, Field, PlacesList, TagInput, TPipe],
  template: `
    <div class="space-y-6">
      <section class="card space-y-5">
        <h2>{{ 'welcome.jobs.title' | t }}</h2>

        <app-field key="search.queries" for="role-add" [label]="'welcome.jobs.roles' | t" [hint]="'setup.search.queriesHint' | t">
          <app-tag-input inputId="role-add" [values]="store.cfg.search.queries" [suggest]="titles" [split]="expand" [placeholder]="'welcome.jobs.addRole' | t"
                         (changed)="store.update('search.queries', $event)" />
        </app-field>

        <app-field key="search.places" [label]="'welcome.jobs.where' | t">
          <app-places-list [places]="shown()" (changed)="setPlaces($event)" />
        </app-field>

        <app-field key="filters.work_modes" [label]="'welcome.jobs.modes' | t">
          <app-chip-select [options]="modeOptions()" [selected]="store.cfg.filters.work_modes" [label]="'welcome.jobs.modes' | t" (changed)="setModes($event)" />
          @if (modesNote()) { <p class="mt-1 text-xs text-rose-700 dark:text-rose-400" role="alert">{{ 'settings.jobs.modesNeed' | t }}</p> }
        </app-field>

        <app-field key="filters.seniority" [label]="'welcome.jobs.level' | t" [hint]="'settings.jobs.levelHint' | t">
          <app-chip-select [options]="levelOptions()" [selected]="store.cfg.filters.seniority" [label]="'welcome.jobs.level' | t" (changed)="store.update('filters.seniority', $event)" />
        </app-field>

        <app-field key="search.posted_within_hours" [label]="'settings.jobs.posted' | t">
          <app-chip-select [options]="postedOptions()" [selected]="postedSelected()" [single]="true" [label]="'settings.jobs.posted' | t" (changed)="setPosted($event[0])" />
          @if (custom()) {
            <div class="mt-3 flex max-w-xs gap-2" dir="ltr">
              <input type="number" min="1" step="1" class="input" [attr.aria-label]="'posted.custom' | t" [value]="customAmount()" (change)="setCustom($event)">
              <select class="input !w-auto" [attr.aria-label]="'posted.unit' | t" (change)="setUnit($event)">
                <option value="hours" [selected]="unit() === 'hours'">{{ 'posted.hours' | t }}</option>
                <option value="days" [selected]="unit() === 'days'">{{ 'posted.days' | t }}</option>
              </select>
            </div>
          }
        </app-field>
      </section>

      <section class="card space-y-5">
        <h2>{{ 'setup.filters.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.filters.intro' | t }}</p>
        <app-field key="filters.title_exclude" for="exc" [label]="'setup.filters.exclude' | t">
          <app-tag-input inputId="exc" [values]="store.cfg.filters.title_exclude" placeholder="intern" (changed)="store.update('filters.title_exclude', $event)" />
        </app-field>
        <app-field key="filters.company_blacklist" for="black" [label]="'setup.filters.blacklist' | t">
          <app-tag-input inputId="black" [values]="store.cfg.filters.company_blacklist" (changed)="store.update('filters.company_blacklist', $event)" />
        </app-field>
      </section>

      <section class="card space-y-5">
        <h2>{{ 'settings.jobs.salary' | t }}</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="answers.salary_expectation" for="salary" [label]="'settings.jobs.salaryMonthly' | t">
            <input id="salary" type="number" min="0" step="1" dir="ltr" class="input" [value]="store.answers.salary_expectation" (change)="setSalary($event)">
          </app-field>
          <app-field key="answers.salary_currency" for="cur" [label]="'setup.filters.currency' | t">
            @if (ratesTried()) {
              <select id="cur" class="input" dir="ltr" (change)="store.update('answers.salary_currency', val($event))">
                @for (c of currencyList(); track c) { <option [value]="c" [selected]="c === currency()">{{ c }}</option> }
              </select>
            }
          </app-field>
        </div>
        <app-field key="filters.skip_below_expectation" for="skip" [check]="true" [label]="'settings.jobs.skipBelow' | t">
          <input id="skip" type="checkbox" class="mt-1" [checked]="store.cfg.filters.skip_below_expectation" (change)="store.update('filters.skip_below_expectation', checked($event))">
        </app-field>
        @if (fxDate()) { <p class="hint !mt-0">{{ 'settings.jobs.salaryNote' | t: { date: fxDate() } }}</p> }
      </section>
    </div>
  `,
})
export class JobsSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly countries = inject(Countries);

  protected readonly expand = expandQueries;
  protected readonly titles = (q: string) => this.api.get<string[]>(`/suggest/titles?q=${encodeURIComponent(q)}`);

  protected readonly shown = signal<Place[]>([]);
  protected readonly modesNote = signal(false);
  protected readonly custom = signal(false);
  protected readonly unit = signal<'hours' | 'days'>('days');
  protected readonly currencies = signal<string[]>(FALLBACK_CURRENCIES);
  protected readonly fxDate = signal('');
  /** The currency list is drawn once the rates answered (or failed): a list that changes under a <select> loses its selection. */
  protected readonly ratesTried = signal(false);
  /** The user took the pre-added home country off the list (nothing saved: no places means anywhere). */
  private homeOff = false;

  ngOnInit(): void {
    this.unit.set(this.hours() !== null && this.hours()! % 24 !== 0 ? 'hours' : 'days');
    this.custom.set(this.hours() !== null && !POSTED.some(([, h]) => h === this.hours()));
    this.syncPlaces();
    void this.countries.load().then(() => this.syncPlaces());
    this.api.get<{ date: string; currencies: string[] }>('/fx').then((fx) => {
      if (fx.currencies.length) this.currencies.set(fx.currencies);
      this.fxDate.set(fx.date);
    }).catch(() => {}).finally(() => this.ratesTried.set(true));
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  // ---- places ------------------------------------------------------------------------------

  /** The saved places; with none saved, the home country with no work right chosen (written only when the user edits). */
  private syncPlaces(): void {
    const saved = this.store.cfg.search.places;
    const iso = this.store.profile.home_country;
    const home = iso ? this.countries.byIso(iso) : undefined;
    this.shown.set(saved.length ? saved : home && !this.homeOff ? [{ label: home.name, city: '', country: home.iso2, work: 'ask' }] : saved);
  }

  protected setPlaces(list: Place[]): void {
    if (!list.length) this.homeOff = true;
    if (list.length || this.store.cfg.search.places.length) this.store.update('search.places', list);
    this.syncPlaces();
  }

  // ---- work modes, level, posted within ----------------------------------------------------

  // computed: a new array on every check would make Angular think the input keeps changing
  protected readonly modeOptions = computed<ChipOption[]>(() => WORK_MODES.map((m) => ({ value: m, label: this.i18n.t(`mode.${m}`) })));
  protected readonly levelOptions = computed<ChipOption[]>(() => SENIORITIES.map((s) => ({ value: s, label: this.i18n.t(`setup.seniority.${s}`) })));
  protected readonly postedOptions = computed<ChipOption[]>(() => [...POSTED.map(([value, , key]) => ({ value, label: this.i18n.t(key) })), { value: 'custom', label: this.i18n.t('posted.customChip') }]);

  protected setModes(modes: string[]): void {
    this.modesNote.set(!modes.length);
    if (modes.length) this.store.update('filters.work_modes', modes);
  }

  private hours(): number | null {
    return this.store.cfg.search.posted_within_hours;
  }

  protected postedSelected(): string[] {
    return ONE[this.custom() ? 'custom' : (POSTED.find(([, h]) => h === this.hours())?.[0] ?? 'custom')];
  }

  protected setPosted(v: string): void {
    this.custom.set(v === 'custom');
    if (v === 'custom') return this.unit.set(this.hours() !== null && this.hours()! % 24 !== 0 ? 'hours' : 'days');
    this.store.update('search.posted_within_hours', POSTED.find(([k]) => k === v)?.[1] ?? null);
  }

  protected customAmount(): number | string {
    const h = this.hours();
    return h === null ? '' : this.unit() === 'days' ? Math.max(1, Math.round(h / 24)) : h;
  }

  protected setCustom(e: Event): void {
    const n = Math.round((e.target as HTMLInputElement).valueAsNumber);
    if (n >= 1) this.store.update('search.posted_within_hours', n * (this.unit() === 'days' ? 24 : 1));
    else (e.target as HTMLInputElement).value = String(this.customAmount()); // empty or 0: keep the saved period
  }

  protected setUnit(e: Event): void {
    const was = this.customAmount();
    this.unit.set(this.val(e) === 'hours' ? 'hours' : 'days');
    if (typeof was === 'number') this.store.update('search.posted_within_hours', was * (this.unit() === 'days' ? 24 : 1));
  }

  // ---- salary ------------------------------------------------------------------------------

  /** The saved currency, else the home country's. */
  protected currency(): string {
    const home = this.countries.byIso(this.store.profile.home_country)?.currency;
    return this.store.answers.salary_currency || home || this.currencies()[0];
  }

  /** The list, plus the current currency when the rates do not know it. */
  protected currencyList(): string[] {
    const cur = this.currency();
    return this.currencies().includes(cur) ? this.currencies() : [cur, ...this.currencies()];
  }

  /** Saving an amount also saves the currency that is showing, so the pair always travels together. */
  protected setSalary(e: Event): void {
    const v = this.val(e).trim();
    this.store.update('answers.salary_expectation', v);
    if (v && !this.store.answers.salary_currency) this.store.update('answers.salary_currency', this.currency());
  }
}
