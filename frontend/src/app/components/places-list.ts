import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { Place } from '../types';
import { ChipSelect } from './chip-select';
import { Countries } from './countries';
import { PlacePick, PlacePicker } from './place-picker';

/**
 * "Where you want to work": one row per place with "I can work here" / "I'd need a visa" (neither is pre-selected: a work right is never assumed, a row still on "ask" shows a prompt), a remove button and a picker to add
 * a city or country. `places` in, `(changed)` out with the whole new list; the parent saves it (the server derives the
 * location filters and the work-permit answers from it). The label shows in Arabic when the UI is Arabic.
 * `<app-places-list [places]="list" (changed)="save($event)" />`
 */
@Component({
  selector: 'app-places-list',
  imports: [ChipSelect, PlacePicker, TPipe],
  host: { class: 'block' },
  template: `
    <div class="space-y-3">
      @if (places().length) {
        <ul class="space-y-2">
          @for (p of places(); track p.label) {
            <li class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
              <bdi class="min-w-0 flex-1 basis-40 break-words font-medium">{{ shown(p) }}</bdi>
              <app-chip-select class="order-3 w-full sm:order-2 sm:w-auto" [options]="workOptions()" [selected]="p.work === 'ask' ? [] : [p.work]" [single]="true" [label]="'places.workIn' | t: { name: shown(p) }" (changed)="setWork(p, $event[0])" />
              <button type="button" class="order-2 rounded-full px-2 text-slate-500 sm:order-3 hover:bg-slate-100 dark:hover:bg-slate-800" [attr.aria-label]="'settings.jobs.remove' | t: { name: shown(p) }" (click)="remove(p)"><span aria-hidden="true">×</span></button>
              @if (p.work === 'ask') { <p class="order-4 w-full text-xs text-slate-600 dark:text-slate-400" dir="auto">{{ 'places.ask' | t }}</p> }
            </li>
          }
        </ul>
      }
      @for (g of [gen()]; track g) {
        <app-place-picker [inputId]="inputId()" [placeholder]="'welcome.jobs.addPlace' | t" [ariaLabel]="'welcome.jobs.addPlace' | t" (picked)="add($event)" />
      }
      <p class="hint !mt-0">{{ 'places.hint' | t }}</p>
    </div>
  `,
})
export class PlacesList {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly countries = inject(Countries);
  readonly places = input<Place[]>([]);
  readonly inputId = input('place-add');
  readonly changed = output<Place[]>();

  protected readonly gen = signal(0); // a new number re-creates the picker, which empties its box
  private readonly arNames = signal<Record<string, string>>({});
  protected readonly workOptions = computed(() => [
    { value: 'allowed', label: this.i18n.t('places.allowed') },
    { value: 'visa', label: this.i18n.t('places.visa') },
  ]);

  constructor() {
    void this.countries.load();
    effect(() => {
      if (this.i18n.lang() !== 'ar') return;
      for (const p of this.places()) if (p.city && p.country) untracked(() => void this.loadAr(p));
    });
  }

  /** The stored label is English; look the Arabic one up once per city. */
  private async loadAr(p: Place): Promise<void> {
    const key = `${p.city}|${p.country}`;
    if (key in this.arNames()) return;
    this.arNames.update((m) => ({ ...m, [key]: '' }));
    const rows = await this.api.get<{ city: string; iso2: string; label_ar: string }[]>(`/suggest/places?q=${encodeURIComponent(p.city)}&lang=ar`).catch(() => []);
    const hit = rows.find((r) => r.city === p.city && r.iso2 === p.country);
    this.arNames.update((m) => ({ ...m, [key]: hit?.label_ar ?? '' }));
  }

  protected shown(p: Place): string {
    if (this.i18n.lang() !== 'ar') return p.label;
    if (!p.city) {
      const c = p.country ? this.countries.byIso(p.country) : undefined;
      return c ? this.countries.name(c) : p.label;
    }
    return this.arNames()[`${p.city}|${p.country}`] || p.label;
  }

  protected setWork(p: Place, work: string | undefined): void {
    if (work !== 'allowed' && work !== 'visa') return;
    this.changed.emit(this.places().map((x) => (x === p ? { ...x, work } : x)));
  }

  protected remove(p: Place): void {
    this.changed.emit(this.places().filter((x) => x !== p));
  }

  protected add(pick: PlacePick): void {
    if (!pick.label) return;
    this.gen.update((n) => n + 1);
    // stored in English (the picker's label is in the UI language): "Cairo, Egypt" / "Egypt"
    const c = pick.country ? this.countries.byIso(pick.country) : undefined;
    const label = c ? (pick.city ? `${pick.city}, ${c.name}` : c.name) : pick.label;
    if (this.places().some((x) => x.label.toLowerCase() === label.toLowerCase())) return;
    this.changed.emit([...this.places(), { label, city: pick.city, country: pick.country, work: 'ask' }]);
  }
}
