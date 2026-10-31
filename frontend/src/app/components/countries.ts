import { inject, Injectable, signal } from '@angular/core';
import { Api } from '../api';
import { I18n } from '../i18n';

export interface Country { iso2: string; name: string; name_ar: string; phone: string; currency: string; jobspy: string }

/** The bundled country list (`GET /api/countries`), loaded once and shared by the phone box, the place box and Settings. */
@Injectable({ providedIn: 'root' })
export class Countries {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  readonly list = signal<Country[]>([]);
  private loading?: Promise<void>;

  load(): Promise<void> {
    return (this.loading ??= this.api.get<Country[]>('/countries').then((l) => this.list.set(l)).catch(() => { this.loading = undefined; }));
  }

  byIso(iso: string): Country | undefined {
    const up = iso.toUpperCase();
    return this.list().find((c) => c.iso2 === up);
  }

  /** The name in the UI language (English when there is no checked Arabic name). */
  name(c: Country): string {
    return this.i18n.lang() === 'ar' && c.name_ar ? c.name_ar : c.name;
  }
}

/** "EG" -> the flag emoji (some systems show the two letters instead; both are fine). */
export function flag(iso2: string): string {
  return iso2.length === 2 ? String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0))) : '';
}

/** Lower-cased with accents and Arabic marks stripped, for "does this name contain what was typed". */
export function fold(s: string): string {
  return s.normalize('NFKD').replace(/[̀-ًͯ-ٟـ]/g, '').replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه').toLowerCase().trim();
}
