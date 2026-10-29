import { inject, Injectable, signal } from '@angular/core';
import { Api } from '../../api';
import { AiBody } from '../../components/ai-connect';
import { I18n } from '../../i18n';
import { ApplicationAnswers, Profile, SearchConfig } from '../../types';

/** What a field's indicator shows. No entry = nothing to show. */
export type FieldState = { state: 'saving' | 'saved' | 'error'; error?: string };
type Obj = 'search' | 'profile' | 'answers';
type Detail = { loc: (string | number)[]; msg: string; type: string; ctx?: Record<string, unknown> };
type Sent = { ok: true } | { ok: false; status: number; detail: unknown };

const DEBOUNCE_MS = 400;
const TICK_MS = 2000;
const URLS: Record<Obj, string> = { search: '/search', profile: '/profile', answers: '/profile/answers' };
const PROFILE_FIELDS = ['full_name', 'email', 'phone', 'location', 'skills', 'locked_facts'] as const;

/**
 * One in-memory copy each of the search config, the profile and the answers, saved as the user edits.
 *
 * A field is named by a key: `profile.<field>`, `answers.<field>`, or a path into the search config
 * (`filters.salary_floor_monthly`, `search.queries`, `ai`). Edit with `update(key, value)`; read with `get(key)`.
 * Each edit marks the key "saving", and about 400 ms later the whole object is PUT (never two PUTs of one object at the
 * same time; edits made meanwhile go out right after). `fields()[key]` then says saved or the error, which <app-field>
 * and <app-saved> show. A 422 puts the message on the field its `loc` points at, keeps the typed value, and keeps the
 * other pending edits unsent until it is fixed (the server rejects the whole object).
 */
@Injectable({ providedIn: 'root' })
export class SettingsStore {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);

  cfg!: SearchConfig;
  profile!: Profile;
  answers!: ApplicationAnswers;
  readonly loaded = signal(false);
  readonly loadError = signal('');
  /** Errors that belong to no single field. */
  readonly alert = signal('');
  readonly fields = signal<Record<string, FieldState>>({});

  private readonly dirty: Record<Obj, Map<string, number>> = { search: new Map(), profile: new Map(), answers: new Map() };
  private readonly timers: Partial<Record<Obj, ReturnType<typeof setTimeout>>> = {};
  private readonly running: Partial<Record<Obj, Promise<void>>> = {};
  private readonly owner = new Map<string, string>();
  private readonly ticks = new Map<string, ReturnType<typeof setTimeout>>();
  private rev = 0;

  /** Read all three from the server, unless edits are still waiting to be saved. */
  async load(): Promise<void> {
    if (Object.values(this.dirty).some((m) => m.size) || Object.keys(this.running).length) return;
    this.loadError.set('');
    try {
      const [cfg, profile, answers] = await Promise.all([
        this.api.get<SearchConfig>('/search'),
        this.api.get<Profile>('/profile'),
        this.api.get<ApplicationAnswers>('/profile/answers'),
      ]);
      this.cfg = cfg;
      this.profile = profile;
      this.answers = answers;
      this.fields.set({});
      this.alert.set('');
      this.loaded.set(true);
    } catch (e) {
      this.loadError.set((e as Error).message);
    }
  }

  // ---- reading and editing ------------------------------------------------------------

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  get(key: string): any {
    const { root, path } = this.resolve(key);
    return path.reduce((o, p) => o?.[p], root);
  }

  /**
   * Set `key` and save. `also` are keys written by the same edit (the "Where" list writes two lists): their errors show
   * on `key`.
   */
  update(key: string, value: unknown, also: string[] = []): void {
    const { root, path } = this.resolve(key);
    const parent = path.slice(0, -1).reduce((o, p) => o[p], root);
    parent[path[path.length - 1]] = value;
    this.touch(key, also);
  }

  /** For edits that change several keys: apply them yourself, then call this once. */
  touch(key: string, also: string[] = []): void {
    const obj = objOf(key);
    const rev = ++this.rev;
    for (const k of [key, ...also]) {
      this.dirty[obj].set(k, rev);
      if (k !== key) this.owner.set(k, key);
      else this.owner.delete(k); // edited by hand now: it reports for itself again
    }
    this.mark(key, { state: 'saving' });
    clearTimeout(this.timers[obj]);
    this.timers[obj] = setTimeout(() => void this.flush(obj), DEBOUNCE_MS);
  }

  /** Save the AI choice now and wait for it (the connect box calls this once a test passed). Throws the error. */
  async saveAi(ai: AiBody): Promise<void> {
    this.update('ai', ai);
    clearTimeout(this.timers.search);
    await this.flush('search');
    const s = this.fields()['ai'];
    if (s?.state === 'error') throw new Error(s.error);
  }

  // ---- saving --------------------------------------------------------------------------

  private flush(obj: Obj): Promise<void> {
    clearTimeout(this.timers[obj]);
    // an edit that arrives while a save is running is picked up by that save's loop
    return (this.running[obj] ??= this.loop(obj).finally(() => delete this.running[obj]));
  }

  private async loop(obj: Obj): Promise<void> {
    while (this.dirty[obj].size) {
      const sent = new Map(this.dirty[obj]);
      const r = await this.put(obj);
      if (!r.ok) return this.failed(obj, sent, r);
      for (const [k, rev] of sent) {
        if (this.dirty[obj].get(k) === rev) this.dirty[obj].delete(k); // edited again meanwhile: stays for the next round
        if (this.dirty[obj].has(k)) continue;
        if (!this.owner.has(k)) this.saved(k); // an alias shows no tick of its own; its owner's tick says it
        this.owner.delete(k); // the save that set the alias is done: later edits of it behave normally
      }
      this.alert.set('');
    }
  }

  private async put(obj: Obj): Promise<Sent> {
    const body = obj === 'profile' ? Object.fromEntries(PROFILE_FIELDS.map((f) => [f, this.profile[f]])) : obj === 'answers' ? this.answers : this.cfg;
    const send = () => fetch(`/api${URLS[obj]}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    try {
      let res = await send();
      if (res.status === 409 && obj === 'answers') {
        await this.put('profile'); // the answers live on the profile row, which a fresh install has not created yet
        res = await send();
      }
      if (res.ok) return { ok: true };
      const data = await res.json().catch(() => null);
      return { ok: false, status: res.status, detail: data?.detail ?? `${res.status} ${res.statusText}` };
    } catch {
      return { ok: false, status: 0, detail: this.i18n.t('settings.err.network') };
    }
  }

  private failed(obj: Obj, sent: Map<string, number>, r: { status: number; detail: unknown }): void {
    const errors = new Map<string, string>();
    const stray: string[] = [];
    if (Array.isArray(r.detail)) {
      for (const d of r.detail as Detail[]) {
        const path = d.loc.slice(1).map(String); // drop "body"
        let hit: string | undefined;
        for (let n = path.length; n > 0 && !hit; n--) {
          const k = (obj === 'search' ? '' : `${obj}.`) + path.slice(0, n).join('.');
          if (sent.has(k)) hit = this.owner.get(k) ?? k;
        }
        const text = this.explain(d);
        if (hit) errors.set(hit, errors.get(hit) ?? text);
        else stray.push(`${path.join('.')}: ${d.msg}`);
      }
    } else {
      stray.push(String(r.detail));
    }
    this.alert.set(stray.join('; '));
    const rest = this.i18n.t(errors.size ? 'settings.blocked' : 'settings.failed');
    for (const k of sent.keys()) {
      if (this.owner.has(k)) continue;
      this.mark(k, { state: 'error', error: errors.get(k) ?? (stray.length && !errors.size ? stray[0] : rest) });
    }
  }

  /** A pydantic error as one short sentence in the UI language. */
  private explain(d: Detail): string {
    const t = (k: string, n: unknown) => this.i18n.t(k, { n: String(n) });
    if (d.type === 'greater_than_equal') return t('settings.err.min', d.ctx?.['ge']);
    if (d.type === 'less_than_equal') return t('settings.err.max', d.ctx?.['le']);
    if (d.type.startsWith('int') || d.type.startsWith('float')) return this.i18n.t('settings.err.number');
    return d.msg;
  }

  private saved(key: string): void {
    this.mark(key, { state: 'saved' });
    clearTimeout(this.ticks.get(key));
    this.ticks.set(key, setTimeout(() => this.fields.update((f) => (f[key]?.state === 'saved' ? Object.fromEntries(Object.entries(f).filter(([k]) => k !== key)) : f)), TICK_MS));
  }

  private mark(key: string, s: FieldState): void {
    clearTimeout(this.ticks.get(key));
    this.fields.update((f) => ({ ...f, [key]: s }));
  }

  private resolve(key: string): { root: any; path: string[] } { // eslint-disable-line @typescript-eslint/no-explicit-any
    const obj = objOf(key);
    const path = key.split('.');
    return obj === 'search' ? { root: this.cfg, path } : { root: obj === 'profile' ? this.profile : this.answers, path: path.slice(1) };
  }
}

function objOf(key: string): Obj {
  return key.startsWith('profile.') ? 'profile' : key.startsWith('answers.') ? 'answers' : 'search';
}
