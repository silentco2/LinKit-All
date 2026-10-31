import { Component, effect, inject, input, output, signal, untracked } from '@angular/core';
import { Api } from '../api';
import { I18n } from '../i18n';
import { Combo, ComboOption } from './combo';
import { Countries, fold } from './countries';

export interface PlacePick { label: string; city: string; country: string; kind: 'city' | 'country' }
type Place = { label: string; label_ar: string; city: string; country: string; iso2: string; kind: 'city' | 'country' };

const DEBOUNCE_MS = 200;

/**
 * Type a city or country, pick from the bundled list (works offline). The list shows the Arabic name when the UI is Arabic.
 * `value` is the text to show; `(picked)` emits `{label, city, country (ISO2), kind}`. Text that matches nothing is
 * emitted as a city with no country; clearing the box emits all-empty. `countriesOnly` lists countries only (and
 * never emits free text).
 * `<app-place-picker inputId="home" [value]="'Cairo, Egypt'" (picked)="set($event)" />`
 */
@Component({
  selector: 'app-place-picker',
  imports: [Combo],
  host: { class: 'block' },
  template: `
    <app-combo [inputId]="inputId()" [(value)]="text" [options]="options()" [placeholder]="placeholder()" [label]="ariaLabel()"
               (valueChange)="typed($event)" (picked)="pick($event)" (submitted)="commit()" (blurred)="commit()" />
  `,
})
export class PlacePicker {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly countries = inject(Countries);
  readonly inputId = input('');
  readonly value = input('');
  readonly placeholder = input('');
  readonly ariaLabel = input('');
  readonly countriesOnly = input(false);
  readonly picked = output<PlacePick>();

  protected readonly text = signal('');
  protected readonly options = signal<ComboOption[]>([]);
  private found = new Map<string, PlacePick>();
  private timer?: ReturnType<typeof setTimeout>;
  private seq = 0;
  private shown = ''; // the text the last pick or `value` put in the box

  constructor() {
    void this.countries.load();
    effect(() => {
      const v = this.value();
      untracked(() => { this.text.set(v); this.shown = v; });
    });
  }

  protected typed(text: string): void {
    clearTimeout(this.timer);
    const mine = ++this.seq;
    const q = text.trim();
    if (!q || text === this.shown) return this.options.set([]);
    if (this.countriesOnly()) return this.show(this.localCountries(q));
    this.timer = setTimeout(async () => {
      const lang = this.i18n.lang();
      const rows = await this.api.get<Place[]>(`/suggest/places?q=${encodeURIComponent(q)}&lang=${lang}`).catch(() => [] as Place[]);
      if (mine !== this.seq) return;
      this.show(rows.map((p) => ({ label: (lang === 'ar' && p.label_ar) || p.label, city: p.city, country: p.iso2, kind: p.kind })));
    }, DEBOUNCE_MS);
  }

  private localCountries(q: string): PlacePick[] {
    const f = fold(q);
    return this.countries.list()
      .filter((c) => fold(c.name).includes(f) || (c.name_ar && fold(c.name_ar).includes(f)) || c.iso2.toLowerCase() === f)
      .slice(0, 10)
      .map((c) => ({ label: this.countries.name(c), city: '', country: c.iso2, kind: 'country' as const }));
  }

  private show(rows: PlacePick[]): void {
    const key = (r: PlacePick) => `${r.country}|${r.city}|${r.label}`;
    this.found = new Map(rows.map((r) => [key(r), r]));
    this.options.set(rows.map((r) => ({ key: key(r), label: r.label })));
  }

  protected pick(o: ComboOption): void {
    const p = this.found.get(o.key);
    if (!p) return;
    this.seq++;
    this.options.set([]);
    this.text.set(p.label);
    this.shown = p.label;
    this.picked.emit(p);
  }

  /** Enter or leaving the box: keep what was typed as a free-text city, or put the old text back. */
  protected commit(): void {
    this.seq++;
    this.options.set([]);
    const text = this.text().trim();
    if (text === this.shown.trim()) return;
    if (!text) {
      this.shown = '';
      this.picked.emit({ label: '', city: '', country: '', kind: 'city' });
    } else if (this.countriesOnly()) {
      this.text.set(this.shown); // only a listed country counts
    } else {
      this.shown = text;
      this.picked.emit({ label: text, city: text.split(/[,،]/)[0].trim(), country: '', kind: 'city' });
    }
  }
}
