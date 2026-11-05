import { Component, effect, inject, input, output, signal, untracked } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { Combo, ComboOption } from './combo';
import { Countries, fold } from './countries';

export interface PlacePick { label: string; city: string; country: string; kind: 'city' | 'country' }
type Place = { label: string; label_ar: string; city: string; country: string; iso2: string; kind: 'city' | 'country' };

const DEBOUNCE_MS = 200;

/**
 * Type a city or country, pick from the bundled list (works offline). The list shows the Arabic name when the UI is Arabic.
 * `value` is the text to show; `(picked)` emits `{label, city, country (ISO2), kind}`. Text that matches nothing is
 * emitted as a city with no country; clearing the box emits all-empty. Enter picks the first suggestion (after
 * waiting for a pending search). `countriesOnly` lists countries only (and never emits free text); `requirePick`
 * never emits free text either: Enter on text that matches nothing shows a hint instead.
 * `<app-place-picker inputId="home" [value]="'Cairo, Egypt'" (picked)="set($event)" />`
 */
@Component({
  selector: 'app-place-picker',
  imports: [Combo, TPipe],
  host: { class: 'block' },
  template: `
    <app-combo [inputId]="inputId()" [(value)]="text" [options]="options()" [placeholder]="placeholder()" [label]="ariaLabel()"
               (valueChange)="typed($event)" (picked)="pick($event)" (submitted)="submit()" (blurred)="commit()" />
    @if (miss()) { <p role="alert" class="mt-1 text-xs text-red-600 dark:text-red-400">{{ 'places.pickHint' | t }}</p> }
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
  readonly requirePick = input(false);
  readonly picked = output<PlacePick>();

  protected readonly text = signal('');
  protected readonly options = signal<ComboOption[]>([]);
  private found = new Map<string, PlacePick>();
  private timer?: ReturnType<typeof setTimeout>;
  private seq = 0;
  private shown = ''; // the text the last pick or `value` put in the box
  protected readonly miss = signal(false);
  private ready: Promise<unknown> = Promise.resolve(); // settles when the pending search has answered
  private release?: () => void;

  constructor() {
    void this.countries.load();
    effect(() => {
      const v = this.value();
      untracked(() => { this.text.set(v); this.shown = v; });
    });
  }

  protected typed(text: string): void {
    clearTimeout(this.timer);
    this.release?.();
    this.miss.set(false);
    const mine = ++this.seq;
    const q = text.trim();
    if (!q || text === this.shown) return this.options.set([]);
    if (this.countriesOnly()) return this.show(this.localCountries(q));
    let done!: () => void;
    this.ready = new Promise<void>((r) => (done = r));
    this.release = done;
    this.timer = setTimeout(async () => {
      const lang = this.i18n.lang();
      const rows = await this.api.get<Place[]>(`/suggest/places?q=${encodeURIComponent(q)}&lang=${lang}`).catch(() => [] as Place[]);
      if (mine === this.seq) this.show(rows.map((p) => ({ label: (lang === 'ar' && p.label_ar) || p.label, city: p.city, country: p.iso2, kind: p.kind })));
      done();
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

  /** Enter with no option marked: take the first suggestion (waiting up to 1 s for the search), else fall back to `commit`. */
  protected async submit(): Promise<void> {
    const text = this.text();
    await Promise.race([this.ready, new Promise((r) => setTimeout(r, 1000))]);
    if (this.text() !== text) return; // the user kept typing
    const first = this.options()[0];
    if (first) return this.pick(first);
    const t = text.trim();
    if (this.requirePick() && t && t !== this.shown.trim()) {
      this.seq++;
      this.miss.set(true);
      return;
    }
    this.commit();
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
    } else if (this.requirePick()) {
      return; // a place needs a country: wait for a pick
    } else {
      this.shown = text;
      this.picked.emit({ label: text, city: text.split(/[,،]/)[0].trim(), country: '', kind: 'city' });
    }
  }
}
