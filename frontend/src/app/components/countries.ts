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

let flagsOk: boolean | undefined;

/**
 * Does this system draw flag emoji? Windows does not: it shows the two letters ("EG"). Checked once with a canvas:
 * a flag is one glyph, so its width is less than its two regional-indicator letters drawn apart.
 */
function flagsSupported(): boolean {
  if (flagsOk !== undefined) return flagsOk;
  try {
    const ctx = document.createElement('canvas').getContext('2d');
    if (!ctx) return (flagsOk = false);
    ctx.font = '32px sans-serif';
    const pair = ctx.measureText(flag0('EG')).width;
    flagsOk = pair < ctx.measureText(flag0('E')).width + ctx.measureText(flag0('G')).width - 1;
  } catch {
    flagsOk = false; // no canvas (a test, a locked-down browser): no flags is the safe side
  }
  return flagsOk;
}

const flag0 = (iso2: string): string => String.fromCodePoint(...[...iso2].map((c) => 0x1f1a5 + c.charCodeAt(0)));

/** "EG" -> the flag emoji, or "" where the system cannot draw flags (callers then show the name alone). */
export function flag(iso2: string): string {
  return iso2.length === 2 && flagsSupported() ? flag0(iso2.toUpperCase()) : '';
}

/** Lower-cased with accents and Arabic marks stripped, for "does this name contain what was typed". */
export function fold(s: string): string {
  return s.normalize('NFKD').replace(/[̀-ًͯ-ٟـ]/g, '').replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه').toLowerCase().trim();
}
