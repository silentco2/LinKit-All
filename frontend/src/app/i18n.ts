import { effect, inject, Injectable, Pipe, PipeTransform, signal } from '@angular/core';
import { ar } from './i18n/ar';
import { en } from './i18n/en';

export type Lang = 'en' | 'ar';
export type Params = Record<string, string | number>;

const LANG_KEY = 'linkit.lang';
const DICTS: Record<Lang, Record<string, string>> = { en, ar };

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === 'en' || saved === 'ar') return saved;
  } catch {
    // storage can be blocked; fall back to the browser language
  }
  return typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('ar') ? 'ar' : 'en';
}

/** Runtime translations: `t('setup.title')`. A missing Arabic key falls back to English, then to the key itself. */
@Injectable({ providedIn: 'root' })
export class I18n {
  readonly lang = signal<Lang>(initialLang());

  constructor() {
    effect(() => {
      const lang = this.lang();
      document.documentElement.lang = lang;
      document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
    });
  }

  /** Switch language and remember it (only an explicit choice is stored, so the browser default stays the default). */
  set(lang: Lang): void {
    this.lang.set(lang);
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      // the choice then lasts until the tab closes
    }
  }

  /** Reads the `lang` signal, so any template or computed that calls it re-renders on a language change. */
  t(key: string, params?: Params): string {
    const text = DICTS[this.lang()][key] ?? en[key] ?? key;
    return params ? text.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m)) : text;
  }
}

/**
 * `{{ 'setup.title' | t }}` or `{{ 'setup.parts' | t: { n: 3 } }}`.
 * Impure on purpose: a pure pipe is only re-run when its inputs change, and the key does not change with the language.
 * The signal read inside `t()` marks the view dirty, so this works without zone.js.
 */
@Pipe({ name: 't', pure: false })
export class TPipe implements PipeTransform {
  private readonly i18n = inject(I18n);

  transform(key: string, params?: Params): string {
    return this.i18n.t(key, params);
  }
}
