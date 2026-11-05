import { effect, inject, Injectable, Pipe, PipeTransform, signal } from '@angular/core';
import { ar } from './i18n/ar';
import { en } from './i18n/en';

export type Lang = 'en' | 'ar';
export type Params = Record<string, string | number>;

const shown = (v: string | number, loc: string): string => (typeof v === 'number' ? new Intl.NumberFormat(loc).format(v) : String(v));

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
    // a number param is written in the language's own digits (٣ in Arabic), so a sentence never mixes two numeral systems
    const loc = this.lang() === 'ar' ? 'ar-EG' : 'en';
    return params ? text.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? shown(params[name], loc) : m)) : text;
  }

  /**
   * `{base}.{zero|one|two|few|many|other}` picked with the browser's CLDR rules for the UI language (Arabic has all six).
   * Tries an exact `.zero` for 0 (English can opt in to "No jobs"), then the rule's category, then `.other`; the UI
   * language first, then English. `{n}` is filled with `n` formatted for the language unless `params` sets it.
   */
  plural(base: string, n: number, params?: Params): string {
    const lang = this.lang();
    const cats = [...(n === 0 ? ['zero'] : []), new Intl.PluralRules(lang).select(n), 'other'];
    for (const dict of [DICTS[lang], en]) {
      for (const c of cats) {
        const text = dict[`${base}.${c}`];
        if (text !== undefined) return this.t(`${base}.${c}`, { n, ...params });
      }
    }
    return base;
  }

  /**
   * A server message (Action Center item, job event, live log line) in the UI language. The server sends an English
   * `message` plus a stable `code` and `params`; `<prefix><code>` is used when it exists (`park.` by default, `log.` for
   * the live log), else the English message (old rows have no code). A `reason` param may pick a variant
   * (`park.tailor_skipped.declined`).
   */
  msg(item: { message: string; code?: string | null; params?: Record<string, unknown> | null }, prefix = 'park.'): string {
    let key = item.code ? `${prefix}${item.code}` : '';
    const params: Params = {};
    for (const [k, v] of Object.entries(item.params ?? {})) params[k] = typeof v === 'number' ? v : String(v);
    if (typeof params['reason'] === 'string' && `${key}.${params['reason']}` in en) key = `${key}.${params['reason']}`;
    const plural = `${key}.other` in en; // a message about a count ("3 questions need your answer") has its plural forms
    if (!key || !(key in en || plural)) return item.message;
    // codes whose params are keys of something else: say them in words
    if (typeof params['source'] === 'string') params['source'] = this.source(params['source']);
    if (typeof params['tier'] === 'string' && `common.tier.${params['tier']}` in en) params['tier'] = this.t(`common.tier.${params['tier']}`);
    if (item.code === 'apply_start') params['mode'] = this.t(item.params?.['live'] ? 'live.mode.real' : 'live.mode.practice');
    if (item.code === 'apply_job' && typeof params['status'] === 'string') params['status'] = this.t(`live.job.${params['status']}`);
    return plural && typeof params['n'] === 'number' ? this.plural(key, params['n'], params) : this.t(key, params);
  }

  /** Is there a translation for `key` (English is the complete dictionary)? */
  has(key: string): boolean {
    return key in en;
  }

  /** The AI behind a provider key, as a person would say it ("ChatGPT (Codex)", "Claude", "your AI"). */
  provider(key: string | null | undefined): string {
    const k = `ai.name.${key ?? ''}`;
    return this.t(k in en ? k : 'ai.name.other');
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
