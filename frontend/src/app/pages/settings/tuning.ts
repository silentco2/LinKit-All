import { inject, Injectable, signal } from '@angular/core';
import { Api } from '../../api';
import { I18n } from '../../i18n';
import { Presets } from '../../types';
import { SettingsStore } from './store';

type Group = 'pace' | 'pickiness';
const FIELDS: Record<Group, { section: string; keys: string[] }> = {
  pace: { section: 'apply', keys: ['parallel_sites', 'min_pause_s', 'max_pause_s', 'daily_cap_per_site', 'max_per_run'] },
  pickiness: { section: 'matching', keys: ['tier_high', 'tier_mid'] },
};

/** Classes of a radio card (Pace, Pickiness): the input inside is visually hidden, the card shows the focus ring. */
export function cardClass(on: boolean): string {
  return `block cursor-pointer rounded-lg border p-3 text-sm has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-500 ${on ? 'border-brand-500 bg-brand-50 text-brand-700 dark:bg-slate-800 dark:text-white' : 'border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'}`;
}

/**
 * The Pace and Pickiness presets and the defaults, and what the saved numbers are measured against. Which preset is
 * "selected" is never stored: it is the one whose numbers all match (else "Custom"), so it follows the raw fields live.
 */
@Injectable({ providedIn: 'root' })
export class Tuning {
  private readonly api = inject(Api);
  private readonly store = inject(SettingsStore);
  private readonly i18n = inject(I18n);
  readonly data = signal<Presets | null>(null);
  readonly error = signal('');

  async load(): Promise<void> {
    if (this.data()) return;
    this.error.set('');
    try {
      this.data.set(await this.api.get<Presets>('/presets'));
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  /** The preset whose numbers all match the saved ones, else null (Custom). */
  matching(group: Group): string | null {
    return this.diffs(group).find((d) => d.n === 0)?.name ?? null;
  }

  /** The preset the numbers are measured against: the matching one, else the closest (Balanced on a tie). */
  private nearest(group: Group): string {
    return [...this.diffs(group)].sort((a, b) => a.n - b.n || +(a.name !== 'balanced') - +(b.name !== 'balanced'))[0].name;
  }

  private diffs(group: Group): { name: string; n: number }[] {
    const { section, keys } = FIELDS[group];
    const set = this.data()?.[group] ?? {};
    return Object.entries(set).map(([name, v]) => ({ name, n: keys.filter((k) => this.store.get(`${section}.${k}`) !== v[k]).length }));
  }

  private group(key: string): Group | null {
    const [section, field] = key.split('.');
    return (Object.keys(FIELDS) as Group[]).find((g) => FIELDS[g].section === section && FIELDS[g].keys.includes(field)) ?? null;
  }

  /** True when `key` is measured against a preset, not the plain default. */
  isPreset(key: string): boolean {
    return this.group(key) !== null;
  }

  baseline(key: string): unknown {
    const d = this.data();
    if (!d) return undefined;
    const g = this.group(key);
    if (g) return d[g][this.nearest(g)][key.split('.')[1]];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return key.split('.').reduce((o: any, p) => o?.[p], d.defaults);
  }

  changed(key: string): boolean {
    const b = this.baseline(key);
    return b !== undefined && JSON.stringify(this.store.get(key)) !== JSON.stringify(b);
  }

  reset(key: string): void {
    this.store.update(key, structuredClone(this.baseline(key)));
  }

  /** Write a whole preset, one touch per key so every field keeps its own saved mark and error. */
  pick(group: Group, name: string): void {
    const { section, keys } = FIELDS[group];
    const values = this.data()![group][name];
    for (const k of keys) this.store.update(`${section}.${k}`, values[k]);
  }

  /**
   * Turn "submit without asking" on or off. Turning it on asks first (applications then go out with no chance to look
   * at them) and returns false when the user says no.
   */
  setNoAsk(on: boolean): boolean {
    if (on && !confirm(`${this.i18n.t('setup.apply.noConfirmTitle')} ${this.i18n.t('setup.apply.noConfirmBody')}\n\n${this.i18n.t('settings.apply.noAskConfirm')}`)) return false;
    this.store.update('apply.submit_without_asking', on);
    return true;
  }
}
