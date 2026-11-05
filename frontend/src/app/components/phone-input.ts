import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { TPipe } from '../i18n';
import { Combo, ComboOption } from './combo';
import { Countries, Country, flag, fold } from './countries';

/**
 * A phone number as a country-code box (flag and "+code"; type a name or digits to search) plus the number.
 * Value in and out is "+digits" (or "" when there is no number). The code defaults to `defaultIso` (the home country);
 * an existing value is split by its longest matching code.
 * `<app-phone-input inputId="phone" [value]="p" defaultIso="EG" (changed)="save($event)" />`
 */
@Component({
  selector: 'app-phone-input',
  imports: [Combo, TPipe],
  host: { class: 'block' },
  template: `
    <div class="flex gap-2" dir="ltr">
      <app-combo class="w-28 shrink-0" [inputId]="inputId() + '-code'" [(value)]="codeText" [options]="options()" panelClass="min-w-72" dir="ltr"
                 [label]="'phone.code' | t" inputMode="search" (focused)="query.set('')" (valueChange)="onCodeTyped($event)" (picked)="pickCode($event)" (blurred)="resetCode()" />
      <input [id]="inputId()" class="input min-w-0 flex-1" type="tel" inputmode="tel" dir="ltr" autocomplete="tel-national" [value]="national()" (change)="numberChanged($event)">
    </div>
  `,
})
export class PhoneInput {
  private readonly countries = inject(Countries);
  readonly value = input('');
  readonly defaultIso = input('');
  readonly inputId = input('');
  readonly changed = output<string>();

  protected readonly iso = signal('');
  protected readonly national = signal('');
  protected readonly codeText = signal('');
  protected readonly query = signal('');
  private emitted: string | null = null;

  private readonly shownCode = computed(() => {
    const c = this.countries.byIso(this.iso());
    return c ? `${flag(c.iso2)} +${c.phone}`.trim() : '+';
  });

  protected readonly options = computed<ComboOption[]>(() => {
    const q = fold(this.query()).replace(/^\+/, '');
    const hit = (c: Country) => !q || fold(c.name).includes(q) || (!!c.name_ar && fold(c.name_ar).includes(q)) || c.iso2.toLowerCase() === q || c.phone.startsWith(q);
    return this.countries.list().filter(hit).map((c) => ({ key: c.iso2, label: `${flag(c.iso2)} ${this.countries.name(c)} +${c.phone}`.trim() }));
  });

  constructor() {
    void this.countries.load();
    effect(() => {
      const v = this.value();
      const list = this.countries.list();
      const home = this.defaultIso();
      untracked(() => {
        if (v === this.emitted && list.length) return; // our own edit coming back: leave the box as typed
        this.parse(v, list, home);
      });
    });
    effect(() => { this.codeText.set(this.shownCode()); });
  }

  /** "+20 100 ..." -> code "20" + the rest; no "+" -> the home country's code and the text as typed. */
  private parse(v: string, list: Country[], home: string): void {
    const fallback = (home || navigator.language.split('-')[1] || '').toUpperCase();
    if (v.startsWith('+')) {
      const digits = v.replace(/\D/g, '');
      for (let n = 6; n > 0; n--) {
        const hits = list.filter((c) => c.phone === digits.slice(0, n));
        if (hits.length) {
          this.iso.set((hits.find((c) => c.iso2 === fallback) ?? hits[0]).iso2);
          this.national.set(digits.slice(n));
          return;
        }
      }
    }
    this.iso.set(fallback);
    this.national.set(v);
  }

  protected onCodeTyped(text: string): void {
    if (text !== this.shownCode()) this.query.set(text);
  }

  protected pickCode(o: ComboOption): void {
    this.iso.set(o.key);
    this.codeText.set(this.shownCode());
    this.emit();
  }

  protected resetCode(): void {
    this.codeText.set(this.shownCode());
  }

  protected numberChanged(e: Event): void {
    this.national.set((e.target as HTMLInputElement).value);
    this.emit();
  }

  private emit(): void {
    const digits = this.national().replace(/\D/g, '').replace(/^0+/, '');
    const c = this.countries.byIso(this.iso());
    const out = !this.national().trim() ? '' : c ? `+${c.phone}${digits}` : this.national().trim();
    this.emitted = out;
    this.changed.emit(out);
  }
}
