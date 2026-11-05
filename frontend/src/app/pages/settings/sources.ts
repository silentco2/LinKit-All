import { NgTemplateOutlet } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../../api';
import { Countries } from '../../components/countries';
import { KeyForm } from '../../components/key-form';
import { TagInput } from '../../components/tag-input';
import { VaultGate } from '../../components/vault-gate';
import { I18n, SourcePipe, TPipe } from '../../i18n';
import { ApiKeyProvider, InferPayload, JobSource, SearchConfig, SourceList } from '../../types';
import { Field, Saved } from './saved';
import { SettingsStore } from './store';

type Note = { kind: 'ok' | 'info' | 'error'; text: string };
type GroupId = 'sites' | 'regional' | 'aggregator' | 'board' | 'company' | 'telegram';
/** One line of the list: a switch (`toggle`), or a user's own entry with a remove button (`remove`). */
interface Row {
  id: string;
  label: string;
  title?: string; // hover text: the full URL behind a readable name
  plain?: boolean; // the label is already the text to show (a URL or a channel), not a source name
  region?: string;
  description?: string;
  rec?: boolean;
  on?: boolean;
  needsKey?: string | null;
  toggle?: () => void;
  remove?: () => void;
}
interface Section { id: GroupId; label: string; count: number; rows: Row[] }

const GROUPS: GroupId[] = ['sites', 'regional', 'aggregator', 'board', 'company', 'telegram'];
const JOBSPY = ['linkedin', 'indeed', 'glassdoor', 'google', 'zip_recruiter'];
const REGIONAL = ['wuzzuf', 'bayt', 'forasna'];
/** These two have their own place on this page, so they never appear as plugin rows. */
const OWN_ROW = new Set(['telegram', 'linkedin_posts']);

/** Settings > Sources: one "Job sources" list (switches, your career pages and Telegram channels, inline API keys), then LinkedIn hiring posts. */
@Component({
  selector: 'app-settings-sources',
  imports: [Field, Saved, KeyForm, NgTemplateOutlet, VaultGate, SourcePipe, TPipe, TagInput, RouterLink],
  template: `
    <ng-template #rowTpl let-r="r">
      <li class="px-3 py-2">
        @if (r.remove) {
          <div class="flex items-center gap-2 text-sm">
            <bdi class="min-w-0 flex-1 break-all font-medium" [attr.dir]="r.title ? 'auto' : 'ltr'" [attr.title]="r.title || null">{{ r.label }}</bdi>
            <button type="button" class="rounded-full px-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" [attr.aria-label]="'settings.jobs.remove' | t: { name: r.label }" (click)="r.remove()"><span aria-hidden="true">×</span></button>
          </div>
        } @else {
          <label class="flex items-start gap-2 text-sm">
            <input type="checkbox" class="mt-1" [checked]="r.on" (change)="r.toggle()">
            <span class="min-w-0 flex-1">
              <span class="font-medium"><bdi>{{ r.plain ? r.label : (r.label | src) }}</bdi></span>
              @if (r.region) { <span class="text-xs text-slate-500"> · <bdi>{{ r.region }}</bdi></span> }
              @if (r.rec) { <span class="badge alert-info ms-2">{{ 'settings.src.badge' | t }}</span> }
              @if (r.description) { <span class="block text-xs text-slate-500 dark:text-slate-400" dir="auto">{{ r.description }}</span> }
            </span>
          </label>
          @if (r.needsKey; as key) {
            <button type="button" class="badge ms-6 mt-1 underline" [class]="keyOk(key) ? 'tier-high' : 'tier-mid'" [attr.aria-expanded]="openKey() === r.id" (click)="openKey.set(openKey() === r.id ? null : r.id)">
              {{ (keyOk(key) ? 'setup.sources.keyReady' : 'setup.sources.needsKey') | t }}
            </button>
            @if (openKey() === r.id && provider(key); as p) {
              <div class="ms-6 mt-2 space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <p class="hint" dir="auto">{{ p.note }}</p>
                <app-vault-gate reason="settings.src.keyVault" (ready)="loadKeys()">
                  <app-key-form [provider]="p" (changed)="keys.set($event)" />
                </app-vault-gate>
              </div>
            }
          }
        }
      </li>
    </ng-template>

    <div class="space-y-6">
      <section class="card space-y-4">
        @let v = view();
        <h2>{{ 'src.title' | t }}</h2>

        <div>
          <label class="label" for="src-add">{{ 'src.add' | t }}</label>
          <form class="flex gap-2" (submit)="add($event, box)">
            <input #box id="src-add" dir="ltr" class="input" autocomplete="off" [placeholder]="'src.add.placeholder' | t">
            <button type="submit" class="btn btn-primary" [disabled]="adding()">{{ 'welcome.jobs.add' | t }}</button>
          </form>
          @if (addNote(); as n) { <div class="alert mt-2" [class.alert-ok]="n.kind === 'ok'" [class.alert-error]="n.kind === 'error'" role="status" dir="auto">{{ n.text }}</div> }
          <p class="hint">{{ 'src.add.hint' | t }}@if (list().ats_count) { {{ i18n.plural('setup.sources.ats', list().ats_count) }} }</p>
        </div>

        @if (loadFailed()) { <div class="alert alert-error" role="alert">{{ 'setup.sources.loadFailed' | t }}</div> }
        <div class="flex flex-wrap items-center gap-2">
          <input type="search" class="input max-w-xs" [value]="query()" (input)="query.set(val($event))" [attr.aria-label]="'setup.sources.search' | t" [placeholder]="'setup.sources.search' | t">
          <button type="button" class="btn" [class.btn-primary]="recOnly()" [attr.aria-pressed]="recOnly()" (click)="recOnly.set(!recOnly())">{{ 'settings.src.recommended' | t }}</button>
          <span class="text-xs text-slate-500">{{ 'setup.sources.count' | t: { on: onCount(v), n: total(v) } }}</span>
          <span class="ms-auto flex gap-2">
            @for (k of savedKeys; track k) { <app-saved [field]="k" /> }
          </span>
        </div>

        @for (s of v; track s.id) {
          <div>
            <h3 class="mb-1 text-sm font-semibold">{{ s.label | t }} <span class="font-normal text-slate-500">({{ s.count }})</span></h3>
            @if (s.id === 'sites' && indeedCountry(); as c) {
              <p class="hint !mt-0 mb-1">{{ 'src.indeed' | t: { country: c } }} <a routerLink="/settings/jobs">{{ 'settings.s.jobs' | t }}</a></p>
            }
            <ul tabindex="0" role="group" [attr.aria-label]="s.label | t" class="max-h-80 divide-y divide-slate-200 overflow-y-auto rounded border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
              @for (r of s.rows; track r.id) {
                <ng-container [ngTemplateOutlet]="rowTpl" [ngTemplateOutletContext]="{ r }" />
              }
            </ul>
          </div>
        } @empty {
          <p class="text-sm text-slate-500">{{ (loading() ? 'common.loading' : 'setup.sources.empty') | t }}</p>
        }
      </section>

      <section class="card space-y-4">
        <h2>{{ 'setup.linkedin.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.linkedin.intro' | t }}</p>
        <div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" role="switch" [checked]="liOn()" (change)="toggle('sources.enabled', 'linkedin_posts')">{{ 'setup.linkedin.enable' | t }}
            </label>
            <app-saved class="ms-auto" field="sources.enabled" />
          </div>
          <p class="hint">{{ 'setup.linkedin.note' | t }}</p>
        </div>
        @if (liCheckNeeded()) { <div class="alert alert-error" role="alert">{{ 'setup.linkedin.google.needed' | t }}</div> }
        <div>
          <button type="button" class="btn" (click)="liSolve()" [disabled]="liBusy()">{{ 'setup.linkedin.google.solve' | t }}</button>
          <p class="hint">{{ 'setup.linkedin.google.hint' | t }}</p>
        </div>
        @if (liNote(); as n) { <div class="alert" [class.alert-ok]="n.kind === 'ok'" [class.alert-info]="n.kind === 'info'" [class.alert-error]="n.kind === 'error'" role="status" dir="auto">{{ n.text }}</div> }
        <app-field key="sources.linkedin_keywords" for="li-keywords" [label]="'setup.linkedin.keywords' | t" [hint]="'setup.linkedin.keywordsHint' | t">
          <app-tag-input inputId="li-keywords" [values]="keywords()" [ariaLabel]="'setup.linkedin.keywords' | t" [placeholder]="'setup.linkedin.keywordsPlaceholder' | t" (changed)="store.update('sources.linkedin_keywords', $event)" />
          @if (!store.cfg.sources.linkedin_keywords.length && keywords().length) { <p class="hint">{{ 'setup.linkedin.fromRoles' | t }}</p> }
        </app-field>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="sources.linkedin_window" for="li-window" [label]="'setup.linkedin.window' | t">
            <select id="li-window" class="input" (change)="store.update('sources.linkedin_window', val($event))">
              <option value="day" [selected]="store.cfg.sources.linkedin_window === 'day'">{{ 'setup.linkedin.window.day' | t }}</option>
              <option value="week" [selected]="store.cfg.sources.linkedin_window === 'week'">{{ 'setup.linkedin.window.week' | t }}</option>
            </select>
          </app-field>
          <app-field key="sources.linkedin_max_posts" for="li-max" [label]="'setup.linkedin.maxPosts' | t">
            <input id="li-max" type="number" min="1" max="50" class="input" [value]="store.cfg.sources.linkedin_max_posts" (change)="store.update('sources.linkedin_max_posts', num($event))">
          </app-field>
        </div>
      </section>
    </div>
  `,
})
export class SourcesSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  protected readonly i18n = inject(I18n);
  private readonly countries = inject(Countries);
  protected readonly savedKeys = ['sources.enabled', 'sources.jobspy', 'sources.regional', 'sources.companies', 'sources.telegram_channels'];
  protected readonly list = signal<SourceList>({ ats_count: 0, sources: [] });
  protected readonly keys = signal<ApiKeyProvider[]>([]);
  /** What the country/track presets recommend (empty when LinKit has nothing to go on): plugin names and jobspy/regional ids. */
  protected readonly rec = signal<Set<string>>(new Set());
  protected readonly loading = signal(true);
  protected readonly loadFailed = signal(false);
  protected readonly query = signal('');
  protected readonly recOnly = signal(false);
  protected readonly openKey = signal<string | null>(null);
  protected readonly adding = signal(false);
  protected readonly addNote = signal<Note | null>(null);

  protected readonly liBusy = signal(false);
  protected readonly liNote = signal<Note | null>(null);
  protected readonly liCheckNeeded = signal(false);

  ngOnInit(): void {
    void this.countries.load();
    this.api.get<SourceList>('/sources').then((l) => this.list.set(l)).catch(() => this.loadFailed.set(true)).finally(() => this.loading.set(false));
    void this.loadKeys();
    // no CV or country yet: nothing is recommended, which is fine
    this.api.get<InferPayload>('/infer').then((p) => this.rec.set(new Set([...p.sources.enabled, ...p.sources.jobspy, ...p.sources.regional]))).catch(() => undefined);
    this.api.get<{ needed: boolean }>('/linkedin/google-check').then((r) => this.liCheckNeeded.set(r.needed)).catch(() => undefined);
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  /** The number in the box; an empty box is NaN, which the server rejects with a message for this field. */
  protected num(e: Event): number {
    const box = e.target as HTMLInputElement;
    return box.value.trim() === '' ? NaN : box.valueAsNumber;
  }

  private has(key: string, item: string): boolean {
    return (this.store.get(key) as string[]).includes(item);
  }

  /** Add or remove one item of a list setting and save. */
  protected toggle(key: string, item: string): void {
    const cur = this.store.get(key) as string[];
    this.store.update(key, cur.includes(item) ? cur.filter((x) => x !== item) : [...cur, item]);
  }

  private drop(key: string, item: string): void {
    this.store.update(key, (this.store.get(key) as string[]).filter((x) => x !== item));
  }

  // ---- the list ---------------------------------------------------------------------------

  private plugin(s: JobSource): Row {
    return {
      id: s.name, label: s.label, plain: true, region: s.region, description: s.description, rec: this.rec().has(s.name), on: this.has('sources.enabled', s.name),
      needsKey: s.needs_key,
      toggle: () => {
        this.toggle('sources.enabled', s.name);
        // turning on a source that needs a key and has none opens its key form right there
        if (this.has('sources.enabled', s.name) && s.needs_key && !this.keyOk(s.needs_key)) this.openKey.set(s.name);
      },
    };
  }

  /** The sections as shown now: every row of every group, narrowed by the search box and the Recommended filter. */
  protected view(): Section[] {
    const c = this.store.cfg.sources;
    const plugins = this.list().sources.filter((s) => !OWN_ROW.has(s.name));
    const fixed = (key: string, ids: string[]): Row[] =>
      ids.map((id) => ({ id: `${key}:${id}`, label: id, rec: this.rec().has(id), on: this.has(key, id), toggle: () => this.toggle(key, id) }));
    const rows: Record<GroupId, Row[]> = {
      sites: fixed('sources.jobspy', JOBSPY),
      regional: fixed('sources.regional', REGIONAL),
      aggregator: plugins.filter((s) => s.kind === 'aggregator').map((s) => this.plugin(s)),
      board: plugins.filter((s) => s.kind === 'board').map((s) => this.plugin(s)),
      company: [
        ...plugins.filter((s) => s.kind === 'company').map((s) => this.plugin(s)),
        ...c.companies.map((u): Row => ({ id: `url:${u}`, label: this.companyLabel(u), title: u, remove: () => this.drop('sources.companies', u) })),
      ],
      telegram: [
        { id: 'telegram', label: this.i18n.t('setup.search.telegram'), plain: true, description: this.i18n.t('setup.search.telegramHint'), on: this.has('sources.enabled', 'telegram'), toggle: () => this.toggle('sources.enabled', 'telegram') },
        ...c.telegram_channels.map((ch): Row => ({ id: `tg:${ch}`, label: /^\w+$/.test(ch) ? `@${ch}` : ch, remove: () => this.drop('sources.telegram_channels', ch) })),
      ],
    };
    const q = this.query().trim().toLowerCase();
    const match = (r: Row) => (!this.recOnly() || !!r.rec) && (!q || `${r.id} ${r.label} ${r.region ?? ''} ${r.description ?? ''} ${this.i18n.source(r.label)}`.toLowerCase().includes(q));
    return GROUPS.map((id) => {
      const all = rows[id];
      const shown = all.filter(match);
      const count = id === 'telegram' ? shown.filter((r) => r.remove).length : shown.length;
      return { id, label: id === 'sites' ? 'src.group.sites' : id === 'regional' ? 'src.group.regional' : id === 'telegram' ? 'src.group.telegram' : `setup.sources.group.${id}`, count, rows: shown };
    }).filter((s) => s.rows.length);
  }

  /** "Stripe · Greenhouse" / "Notion · careers page" from the server; the raw URL until it has a name for it. */
  protected companyLabel(url: string): string {
    const label = this.store.cfg.sources.company_labels?.[url];
    return label ? this.readable(label) : url;
  }

  /** The server writes "careers page" in English; say it in the UI language. */
  private readable(label: string): string {
    const tail = ' · careers page';
    return label.endsWith(tail) ? label.slice(0, -tail.length) + ' · ' + this.i18n.t('src.careersPage') : label;
  }

  protected onCount(v: Section[]): number {
    return v.reduce((n, s) => n + s.rows.filter((r) => r.on).length, 0);
  }

  protected total(v: Section[]): number {
    return v.reduce((n, s) => n + s.rows.filter((r) => r.toggle).length, 0);
  }

  protected indeedCountry(): string {
    const raw = this.store.cfg.sources.jobspy_country;
    const c = this.countries.list().find((x) => x.jobspy.toLowerCase() === raw.toLowerCase() || x.name.toLowerCase() === raw.toLowerCase());
    return c ? this.countries.name(c) : raw;
  }

  // ---- add one source -----------------------------------------------------------------------

  /** A Telegram link / @name or a careers page: the server saves it; we take over the fields it changed so the next autosave keeps them. */
  protected async add(e: Event, box: HTMLInputElement): Promise<void> {
    e.preventDefault();
    const value = box.value.trim();
    if (!value) return;
    this.adding.set(true);
    this.addNote.set(null);
    try {
      const r = await this.api.post<{ kind: 'telegram' | 'ats' | 'careers'; label: string; config: Partial<SearchConfig['sources']> }>('/sources/add', { value });
      Object.assign(this.store.cfg.sources, r.config);
      box.value = '';
      const text =
        r.kind === 'telegram' ? this.i18n.t('src.added.telegram', { name: r.label })
        : this.i18n.t('src.added.company', { name: this.readable(r.label) });
      this.addNote.set({ kind: 'ok', text });
    } catch (err) {
      this.addNote.set({ kind: 'error', text: (err as Error).message });
    } finally {
      this.adding.set(false);
    }
  }

  protected provider(name: string): ApiKeyProvider | undefined {
    return this.keys().find((k) => k.name === name);
  }

  protected keyOk(name: string): boolean {
    return !!this.provider(name)?.configured;
  }

  protected async loadKeys(): Promise<void> {
    try {
      this.keys.set(await this.api.get<ApiKeyProvider[]>('/keys'));
    } catch {
      // the key form is simply not offered; the list still works
    }
  }

  // ---- LinkedIn hiring posts ---------------------------------------------------------------

  protected liOn(): boolean {
    return this.has('sources.enabled', 'linkedin_posts');
  }

  /** The chips: the saved keywords, else the job titles (the run falls back to them too). The first edit saves the full list. */
  protected keywords(): string[] {
    const own = this.store.cfg.sources.linkedin_keywords;
    return own.length ? own : this.store.cfg.search.queries;
  }

  /** Opens Google in the app browser, on the searches' own profile; the user solves the check there. */
  protected async liSolve(): Promise<void> {
    this.liBusy.set(true);
    this.liNote.set(null);
    try {
      await this.api.post('/linkedin/google-check');
      this.liNote.set({ kind: 'info', text: this.i18n.t('setup.linkedin.google.opened') });
    } catch (e) {
      this.liNote.set({ kind: 'error', text: (e as Error).message });
    } finally {
      this.liBusy.set(false);
    }
  }
}
