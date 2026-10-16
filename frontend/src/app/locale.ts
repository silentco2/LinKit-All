import { registerLocaleData } from '@angular/common';
import localeAr from '@angular/common/locales/ar-EG';
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
