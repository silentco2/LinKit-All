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

/** What `dt` shows: `when` = "Sat 1 Nov, 09:00", `time` = "09:00:01", `date`, `medium` (date + time), `short`, and `stamp` = "1 Nov 2026, 09:00" (a month name, so no US/EU mix-up). */
const DATE_STYLES: Record<string, Intl.DateTimeFormatOptions> = {
  when: { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false },
  time: { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false },
  date: { dateStyle: 'medium' },
  medium: { dateStyle: 'medium', timeStyle: 'medium' },
  short: { dateStyle: 'short', timeStyle: 'short' },
  stamp: { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false },
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

/** A `YYYY-MM-DD` the server sends as a calendar day, as a local date (`new Date('2026-11-04')` is UTC and can show the day before). */
export const dayOf = (iso: string | null | undefined): Date | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
};

/** Why a run stopped or paused, in the UI language (`run.reason.<code>`); `fallback` (the server's English text) when the code is unknown. */
export function runReason(i18n: I18n, code: string | null | undefined, params: Record<string, unknown> | undefined, fallback: string): string {
  if (!code) return fallback;
  const p = { ...params };
  let key = code;
  if (code === 'ai_usage_limit') {
    p['provider'] = i18n.provider(String(p['provider'] ?? ''));
    const until = dayOf(typeof p['until'] === 'string' ? p['until'] : null);
    if (until) p['until'] = fmtDate(localeOf(i18n.lang()), until, 'date');
    else key = 'ai_usage_limit.noDate';
  }
  return i18n.msg({ message: fallback, code: key, params: p }, 'run.reason.');
}

/**
 * The CV file as the user knows it. A PDF or ODT is stored as a converted `.docx`; the server keeps no separate field for
 * the original name, but it is the same name with the original extension, so "cv.docx" + "pdf" shows "cv.pdf, converted for editing".
 */
export function cvLabel(i18n: I18n, name: string | null | undefined, format: string | null | undefined): string {
  if (!name) return '';
  if (format !== 'pdf' && format !== 'odt') return name;
  return i18n.t('setup.cv.convertedFrom', { name: name.replace(/\.[^.]+$/, '') + '.' + format });
}

// Years of experience per level, the bands `core/infer.py` uses (lead, manager and executive share "10+").
const LEVEL_YEARS: Record<string, [number, number]> = { intern: [0, 1], junior: [1, 3], mid: [3, 6], senior: [6, 10], lead: [10, 0], manager: [10, 0], executive: [10, 0] };

/** One plain line for a level chip: "Mid — about 3–6 years; works independently". */
export function levelTip(i18n: I18n, level: string): string {
  const [a, b] = LEVEL_YEARS[level] ?? [0, 0];
  return i18n.t(`setup.seniority.tip.${level}`, { a, b });
}
