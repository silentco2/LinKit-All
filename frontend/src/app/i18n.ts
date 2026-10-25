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

  /**
   * A server message (Action Center item, job event) in the UI language. The server sends an English `message` plus a
   * stable `code` and `params`; `park.<code>` is used when it exists, else the English message (old rows have no code).
   */
  msg(item: { message: string; code?: string | null; params?: Record<string, unknown> | null }): string {
    const key = item.code ? `park.${item.code}` : '';
    if (!key || !(key in en)) return item.message;
    const loc = this.lang() === 'ar' ? 'ar-EG' : 'en';
    const params: Params = {};
    for (const [k, v] of Object.entries(item.params ?? {})) params[k] = typeof v === 'number' ? new Intl.NumberFormat(loc).format(v) : String(v);
    return this.t(key, params);
  }

  /** A job source / ATS key as a readable name: `source.<key>` when listed, else the key title-cased (`zip_recruiter` -> "Zip Recruiter"). */
  source(key: string): string {
    const k = `source.${key.toLowerCase()}`;
    if (k in en) return this.t(k);
    return key.replace(/[_-]+/g, ' ').replace(/\b[a-z]/g, (c) => c.toUpperCase());
  }
}

/** `{{ item | msg }}`: see `I18n.msg`. Impure for the same reason as `t`. */
@Pipe({ name: 'msg', pure: false })
export class MsgPipe implements PipeTransform {
  private readonly i18n = inject(I18n);

  transform(item: { message: string; code?: string | null; params?: Record<string, unknown> | null }): string {
    return this.i18n.msg(item);
  }
}

/** `{{ 'zip_recruiter' | src }}`: see `I18n.source`. */
@Pipe({ name: 'src', pure: false })
export class SourcePipe implements PipeTransform {
  private readonly i18n = inject(I18n);

  transform(key: string): string {
    return this.i18n.source(key);
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
