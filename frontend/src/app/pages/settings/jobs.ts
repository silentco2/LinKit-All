import { Component, inject, OnInit, signal } from '@angular/core';
import { TPipe } from '../../i18n';
import { expandQueries, lines, unlines } from '../../types';
import { Saved, Field } from './saved';
import { SettingsStore } from './store';

const CHIP = 'inline-flex items-center gap-1 rounded-full border border-brand-500 bg-brand-50 py-0.5 ps-3 pe-1 text-sm font-medium text-brand-700 dark:bg-slate-800 dark:text-white';

/** Settings > Jobs & places: what to look for and where. Everything saves as you edit. */
@Component({
  selector: 'app-settings-jobs',
  imports: [Field, Saved, TPipe],
  template: `
    <div class="space-y-6">
      <section class="card space-y-5">
        <h2>{{ 'welcome.jobs.title' | t }}</h2>

        <app-field key="search.queries" for="role-add" [label]="'welcome.jobs.roles' | t" [hint]="'setup.search.queriesHint' | t">
          <div class="flex flex-wrap items-center gap-2" role="list">
            @for (r of store.cfg.search.queries; track r) {
              <span role="listitem" [class]="chip">
                <bdi>{{ r }}</bdi>
                <button type="button" class="rounded-full px-1.5 hover:bg-brand-100 dark:hover:bg-slate-700" [attr.aria-label]="'settings.jobs.remove' | t: { name: r }" (click)="removeRole(r)"><span aria-hidden="true">×</span></button>
              </span>
            }
          </div>
          <div class="mt-2 flex max-w-md gap-2">
            <input #roleIn id="role-add" class="input" dir="auto" [placeholder]="'welcome.jobs.addRole' | t" (keydown.enter)="addRole(roleIn)" (change)="addRole(roleIn)">
            <button type="button" class="btn" (click)="addRole(roleIn)">{{ 'welcome.jobs.add' | t }}</button>
          </div>
        </app-field>

        <app-field key="search.locations" for="place-add" [label]="'welcome.jobs.where' | t" [hint]="'setup.search.locationsHint' | t">
          <div class="flex flex-wrap items-center gap-2" role="list">
            @for (p of places(); track p) {
              <span role="listitem" [class]="chip">
                <bdi>{{ p }}</bdi>
                <button type="button" class="rounded-full px-1.5 hover:bg-brand-100 dark:hover:bg-slate-700" [attr.aria-label]="'settings.jobs.remove' | t: { name: p }" (click)="removePlace(p)"><span aria-hidden="true">×</span></button>
              </span>
            }
          </div>
          <div class="mt-2 flex max-w-md gap-2">
            <input #placeIn id="place-add" class="input" dir="auto" [placeholder]="'welcome.jobs.addPlace' | t" (keydown.enter)="addPlace(placeIn)" (change)="addPlace(placeIn)">
            <button type="button" class="btn" (click)="addPlace(placeIn)">{{ 'welcome.jobs.add' | t }}</button>
          </div>
          <label class="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" role="switch" [checked]="remoteOn()" (change)="setRemote($event)"> {{ 'welcome.jobs.remote' | t }}
          </label>
        </app-field>

        <app-field key="filters.seniority" [label]="'welcome.jobs.level' | t" [hint]="'settings.jobs.levelHint' | t">
          <div class="flex flex-wrap items-center gap-2" role="group">
            @for (s of seniorities; track s) {
              <button type="button" [class]="levelClass(has(s))" [attr.aria-pressed]="has(s)" (click)="toggleLevel(s)">{{ 'setup.seniority.' + s | t }}</button>
            }
          </div>
        </app-field>

        <div class="max-w-xs">
          <app-field key="search.posted_within_days" for="days" [label]="'setup.search.days' | t">
            <input id="days" type="number" min="1" step="1" class="input" [value]="store.cfg.search.posted_within_days" (change)="store.update('search.posted_within_days', num($event))">
          </app-field>
        </div>
      </section>

      <section class="card space-y-5">
        <h2>{{ 'setup.filters.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.filters.intro' | t }}</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="filters.title_exclude" for="exc" [label]="'setup.filters.exclude' | t" [hint]="'settings.oneLine' | t">
            <textarea id="exc" dir="auto" class="input h-24" [value]="unlines(store.cfg.filters.title_exclude)" (change)="store.update('filters.title_exclude', lines(val($event)))" placeholder="intern&#10;director"></textarea>
          </app-field>
          <app-field key="filters.company_blacklist" for="black" [label]="'setup.filters.blacklist' | t" [hint]="'settings.oneLine' | t">
            <textarea id="black" dir="auto" class="input h-24" [value]="unlines(store.cfg.filters.company_blacklist)" (change)="store.update('filters.company_blacklist', lines(val($event)))"></textarea>
          </app-field>
        </div>

        <app-field key="filters.one_per_company" for="one" [check]="true" [label]="'setup.filters.onePer' | t">
          <input id="one" type="checkbox" class="mt-1" [checked]="store.cfg.filters.one_per_company" (change)="store.update('filters.one_per_company', checked($event))">
        </app-field>

        <div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" role="switch" [checked]="salaryOn()" (change)="setSalary($event)"> {{ 'settings.jobs.salaryOn' | t }}
            </label>
            <app-saved class="ms-auto" field="filters.salary_floor_monthly" />
          </div>
          @if (salaryOn()) {
            <div class="mt-3 grid gap-4 sm:grid-cols-2">
              <app-field key="filters.salary_floor_monthly" for="salary" [label]="'setup.filters.salary' | t">
                <input id="salary" type="number" min="1" step="1" class="input" [value]="store.cfg.filters.salary_floor_monthly || ''" (change)="store.update('filters.salary_floor_monthly', num($event, 0))">
              </app-field>
              <app-field key="filters.salary_currency" for="cur" [label]="'setup.filters.currency' | t">
                <select id="cur" class="input" dir="ltr" (change)="store.update('filters.salary_currency', val($event))">
                  @for (c of currencies(); track c) { <option [value]="c" [selected]="c === store.cfg.filters.salary_currency">{{ c }}</option> }
                </select>
              </app-field>
            </div>
            <p class="hint">{{ 'settings.jobs.salaryHint' | t }}</p>
          }
        </div>
      </section>
    </div>
  `,
})
export class JobsSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  protected readonly lines = lines;
  protected readonly unlines = unlines;
  protected readonly chip = CHIP;
  protected readonly seniorities = ['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'executive'];
  private readonly allCurrencies = ['EGP', 'SAR', 'AED', 'QAR', 'KWD', 'BHD', 'OMR', 'JOD', 'USD', 'EUR', 'GBP'];
  protected readonly salaryOn = signal(false);

  ngOnInit(): void {
    this.salaryOn.set(this.store.cfg.filters.salary_floor_monthly > 0);
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  /** The number in the box; an empty box is NaN, which the server rejects with a message for this field. */
  protected num(e: Event, empty = NaN): number {
    const box = e.target as HTMLInputElement;
    return box.value.trim() === '' ? empty : box.valueAsNumber;
  }

  // ---- roles ---------------------------------------------------------------------------

  /** The text of an "add" box, which is emptied; "" when there is none. */
  private take(box: HTMLInputElement): string {
    const v = box.value.trim();
    box.value = '';
    return v;
  }

  protected addRole(box: HTMLInputElement): void {
    const v = this.take(box);
    if (!v) return;
    // "React/Next.JS Developer" becomes two chips
    this.store.update('search.queries', expandQueries([...this.store.cfg.search.queries, v]));
  }

  protected removeRole(r: string): void {
    this.store.update('search.queries', this.store.cfg.search.queries.filter((q) => q !== r));
  }

  // ---- one "Where" list: search.locations as typed, filters.locations lowercased -------------------

  /** The union of both lists without "Remote" (that is the switch), so lists that drifted apart show everything. */
  protected places(): string[] {
    const seen = new Map<string, string>();
    for (const p of [...this.store.cfg.search.locations, ...this.store.cfg.filters.locations]) {
      const t = p.trim();
      if (t && t.toLowerCase() !== 'remote' && !seen.has(t.toLowerCase())) seen.set(t.toLowerCase(), t);
    }
    return [...seen.values()];
  }

  protected remoteOn(): boolean {
    return this.store.cfg.filters.work_modes.includes('remote');
  }

  /** Write both lists (and the work modes when `remote` changed) from one list of places. */
  private writeWhere(places: string[], remote: boolean, modesToo: boolean): void {
    const all = remote ? [...places, 'Remote'] : places;
    const { search, filters } = this.store.cfg;
    search.locations = all;
    filters.locations = all.map((p) => p.toLowerCase());
    if (modesToo) filters.work_modes = remote ? ['remote', 'hybrid', 'onsite'] : ['hybrid', 'onsite'];
    this.store.touch('search.locations', ['filters.locations', ...(modesToo ? ['filters.work_modes'] : [])]);
  }

  protected addPlace(box: HTMLInputElement): void {
    const v = this.take(box);
    if (!v || this.places().some((p) => p.toLowerCase() === v.toLowerCase())) return;
    this.writeWhere([...this.places(), v], this.remoteOn(), false);
  }

  protected removePlace(p: string): void {
    this.writeWhere(this.places().filter((x) => x !== p), this.remoteOn(), false);
  }

  protected setRemote(e: Event): void {
    this.writeWhere(this.places(), this.checked(e), true);
  }

  // ---- level, salary ---------------------------------------------------------------------

  protected has(level: string): boolean {
    return this.store.cfg.filters.seniority.includes(level as never);
  }

  protected levelClass(on: boolean): string {
    return `rounded-full border px-3 py-1 text-sm ${on ? 'border-brand-500 bg-brand-50 font-medium text-brand-700 dark:bg-slate-800 dark:text-white' : 'border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400'}`;
  }

  protected toggleLevel(level: string): void {
    const cur = this.store.cfg.filters.seniority as string[];
    this.store.update('filters.seniority', this.seniorities.filter((s) => (s === level ? !cur.includes(s) : cur.includes(s))));
  }

  /** Off saves "no floor" (0); on only shows the box, nothing changes until a number is entered. */
  protected setSalary(e: Event): void {
    const on = this.checked(e);
    this.salaryOn.set(on);
    if (!on) this.store.update('filters.salary_floor_monthly', 0);
  }

  protected currencies(): string[] {
    const cur = this.store.cfg.filters.salary_currency;
    return this.allCurrencies.includes(cur) ? this.allCurrencies : [cur, ...this.allCurrencies];
  }
}
