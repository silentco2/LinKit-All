import { registerLocaleData } from '@angular/common';
import localeAr from '@angular/common/locales/ar-EG';
import { inject, Pipe, PipeTransform } from '@angular/core';
import { I18n, Lang } from './i18n';

registerLocaleData(localeAr); // DatePipe needs the data for any non-English locale

/** Intl / DatePipe locale for the UI language. */
export const localeOf = (lang: Lang): string => (lang === 'ar' ? 'ar-EG' : 'en');

export const fmtNum = (loc: string, n: number | null | undefined, opts?: Intl.NumberFormatOptions): string =>
  n === null || n === undefined ? '' : new Intl.NumberFormat(loc, opts).format(n);

/** Translate `prefix + value`; a value we have no label for (a new server state, say) is shown as it came. */
export function labelOr(i18n: I18n, prefix: string, value: string): string {
  const key = prefix + value;
  const text = i18n.t(key);
  return text === key ? value : text;
}

/** What `dt` shows: `when` = "Sat 1 Nov, 09:00", `time` = "09:00:01", `date`, `medium` (date + time) and `short`. */
const DATE_STYLES: Record<string, Intl.DateTimeFormatOptions> = {
  when: { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false },
  time: { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false },
  date: { dateStyle: 'medium' },
  medium: { dateStyle: 'medium', timeStyle: 'medium' },
  short: { dateStyle: 'short', timeStyle: 'short' },
};

/** A date or time in the language's own digits (Angular's DatePipe always writes 0-9, which mixed with Arabic-Indic numbers). */
export const fmtDate = (loc: string, value: string | Date | null | undefined, style: keyof typeof DATE_STYLES = 'short'): string => {
  const d = value instanceof Date ? value : value ? new Date(value) : null;
  return d && !Number.isNaN(d.getTime()) ? new Intl.DateTimeFormat(loc, DATE_STYLES[style]).format(d) : '';
};

/** `{{ iso | dt: 'when' }}`: see `fmtDate`. Impure like `t`, so it follows a language change. */
@Pipe({ name: 'dt', pure: false })
export class DtPipe implements PipeTransform {
  private readonly i18n = inject(I18n);

  transform(value: string | Date | null | undefined, style: keyof typeof DATE_STYLES = 'short'): string {
    return fmtDate(localeOf(this.i18n.lang()), value, style);
  }
}

/** "EGP" -> "EGP · Egyptian Pound" / "EGP · الجنيه المصري": a bare currency code means little to most people. */
export function currencyLabel(lang: Lang, code: string): string {
  if (!code) return '';
  try {
    const name = new Intl.DisplayNames(localeOf(lang), { type: 'currency' }).of(code);
    return name && name !== code ? `${code} · ${name}` : code;
  } catch {
    return code;
  }
}
