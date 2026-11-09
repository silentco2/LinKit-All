import { NgTemplateOutlet } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../../api';
import { ChipOption, ChipSelect } from '../../components/chip-select';
import { Countries } from '../../components/countries';
import { KeyForm } from '../../components/key-form';
import { VaultGate } from '../../components/vault-gate';
import { I18n, SourcePipe, TPipe } from '../../i18n';
import { ApiKeyProvider, InferPayload, JobSource, SearchConfig, SourceList } from '../../types';
import { Saved } from './saved';
import { SettingsStore } from './store';

type Note = { kind: 'ok' | 'info' | 'error'; text: string };
type GroupId = 'sites' | 'regional' | 'aggregator' | 'board' | 'company' | 'telegram';
/** One line of the list: a switch (`toggle`), or a user's own entry with a remove button (`remove`). */
interface Row {
  id: string;
  group: GroupId;
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
interface View { chips: ChipOption[]; rows: Row[]; on: number; total: number; sites: boolean }

const GROUPS: GroupId[] = ['sites', 'regional', 'aggregator', 'board', 'company', 'telegram'];
const GROUP_LABEL: Record<GroupId, string> = {
  sites: 'src.group.sites', regional: 'src.group.regional', aggregator: 'setup.sources.group.aggregator',
  board: 'setup.sources.group.board', company: 'setup.sources.group.company', telegram: 'src.group.telegram',
};
const JOBSPY = ['linkedin', 'indeed', 'glassdoor', 'google', 'zip_recruiter'];
const REGIONAL = ['wuzzuf', 'bayt', 'forasna'];
/** These two get their own hand-made row in the list, so they never appear as plugin rows. */
const OWN_ROW = new Set(['telegram', 'linkedin_posts']);

/** Settings > Sources: one "Job sources" list with filter chips (switches, your career pages and Telegram channels, inline API keys), including LinkedIn hiring posts. */
@Component({
  selector: 'app-settings-sources',
  imports: [Saved, KeyForm, NgTemplateOutlet, VaultGate, SourcePipe, TPipe, RouterLink, ChipSelect],
  template: `
    <ng-template #rowTpl let-r="r">
      <li class="px-3 py-2">
        @if (r.remove) {
          <div class="flex items-center gap-2 text-sm">
            <bdi class="min-w-0 flex-1 break-all font-medium" [attr.dir]="r.title ? 'auto' : 'ltr'" [attr.title]="r.title || null">{{ r.label }}</bdi>
            @if (group() === 'all') { <span class="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">{{ groupLabel(r.group) | t }}</span> }
            <button type="button" class="rounded-md px-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" [attr.aria-label]="'settings.jobs.remove' | t: { name: r.label }" (click)="r.remove()"><span aria-hidden="true">×</span></button>
          </div>
        } @else {
          <label class="flex items-start gap-2 text-sm">
            <input type="checkbox" class="mt-1" [checked]="r.on" (change)="r.toggle()">
            <span class="min-w-0 flex-1">
              <span class="font-medium"><bdi>{{ r.plain ? r.label : (r.label | src) }}</bdi></span>
              @if (r.region) { <span class="text-xs text-slate-500"> <span class="gap-dot"></span><bdi>{{ r.region }}</bdi></span> }
              @if (group() === 'all') { <span class="ms-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">{{ groupLabel(r.group) | t }}</span> }
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
        <div class="space-y-3">
          <div class="flex flex-wrap items-center gap-2">
            <input type="search" class="input max-w-xs" [value]="query()" (input)="query.set(val($event))" [attr.aria-label]="'setup.sources.search' | t" [placeholder]="'setup.sources.search' | t">
            <app-chip-select [options]="flagChips()" [selected]="flags()" [label]="'src.filter.show' | t" (changed)="flags.set($event)" />
            <span class="ms-auto flex gap-2">
              @for (k of savedKeys; track k) { <app-saved [field]="k" /> }
            </span>
          </div>
          <app-chip-select [options]="v.chips" [selected]="[group()]" [single]="true" [label]="'src.filter.group' | t" (changed)="setGroup($event)" />
          <p class="text-xs text-slate-500">{{ 'setup.sources.count' | t: { on: v.on, n: v.total } }}</p>
        </div>

        @if (v.sites && indeedCountry(); as c) {
          <p class="hint !mt-0">{{ 'src.indeed' | t: { country: c } }} <a routerLink="/settings/jobs">{{ 'settings.s.jobs' | t }}</a></p>
        }
        @if (v.rows.length) {
          <ul tabindex="0" role="group" [attr.aria-label]="'src.title' | t" class="max-h-[36rem] divide-y divide-slate-200 overflow-y-auto rounded border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
            @for (r of v.rows; track r.id) {
              <ng-container [ngTemplateOutlet]="rowTpl" [ngTemplateOutletContext]="{ r }" />
            }
          </ul>
        } @else {
          <p class="text-sm text-slate-500">{{ (loading() ? 'common.loading' : 'setup.sources.empty') | t }}</p>
        }
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
  /** The group chip that is on ('all' shows every group), and the Recommended / Turned on filters. */
  protected readonly group = signal<GroupId | 'all'>('all');
  protected readonly flags = signal<string[]>([]);
  protected readonly openKey = signal<string | null>(null);
  protected readonly adding = signal(false);
  protected readonly addNote = signal<Note | null>(null);

  ngOnInit(): void {
    void this.countries.load();
    this.api.get<SourceList>('/sources').then((l) => this.list.set(l)).catch(() => this.loadFailed.set(true)).finally(() => this.loading.set(false));
    void this.loadKeys();
    // no CV or country yet: nothing is recommended, which is fine
    this.api.get<InferPayload>('/infer').then((p) => this.rec.set(new Set([...p.sources.enabled, ...p.sources.jobspy, ...p.sources.regional]))).catch(() => undefined);
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
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
      id: s.name, group: s.kind as GroupId, label: s.label, plain: true, region: s.region, description: s.description, rec: this.rec().has(s.name), on: this.has('sources.enabled', s.name),
      needsKey: s.needs_key,
      toggle: () => {
        this.toggle('sources.enabled', s.name);
        // turning on a source that needs a key and has none opens its key form right there
        if (this.has('sources.enabled', s.name) && s.needs_key && !this.keyOk(s.needs_key)) this.openKey.set(s.name);
      },
    };
  }

  /** The list as shown now: search and the Recommended / Turned on chips narrow every group (the group chips count what is left), then the group chip picks one. */
  protected view(): View {
    const c = this.store.cfg.sources;
    const plugins = this.list().sources.filter((s) => !OWN_ROW.has(s.name));
    const fixed = (group: GroupId, key: string, ids: string[]): Row[] =>
      ids.map((id) => ({ id: `${key}:${id}`, group, label: id, rec: this.rec().has(id), on: this.has(key, id), toggle: () => this.toggle(key, id) }));
    const kind = (k: GroupId) => plugins.filter((s) => s.kind === k).map((s) => this.plugin(s));
    const all: Row[] = [
      ...fixed('sites', 'sources.jobspy', JOBSPY),
      { id: 'linkedin_posts', group: 'sites', label: this.i18n.t('setup.linkedin.title'), plain: true, description: this.i18n.t('src.linkedin.desc'), on: this.has('sources.enabled', 'linkedin_posts'), toggle: () => this.toggle('sources.enabled', 'linkedin_posts') },
      ...fixed('regional', 'sources.regional', REGIONAL),
      ...kind('aggregator'),
      ...kind('board'),
      ...kind('company'),
      ...c.companies.map((u): Row => ({ id: `url:${u}`, group: 'company', label: this.companyLabel(u), title: u, remove: () => this.drop('sources.companies', u) })),
      { id: 'telegram', group: 'telegram', label: this.i18n.t('setup.search.telegram'), plain: true, description: this.i18n.t('setup.search.telegramHint'), on: this.has('sources.enabled', 'telegram'), toggle: () => this.toggle('sources.enabled', 'telegram') },
      ...c.telegram_channels.map((ch): Row => ({ id: `tg:${ch}`, group: 'telegram', label: /^\w+$/.test(ch) ? `@${ch}` : ch, remove: () => this.drop('sources.telegram_channels', ch) })),
    ];
    const q = this.query().trim().toLowerCase();
    const f = this.flags();
    // your own pages and channels count as on: they are searched whenever they are listed
    const match = (r: Row) =>
      (!f.includes('rec') || !!r.rec) && (!f.includes('on') || !!r.on || !!r.remove)
      && (!q || `${r.id} ${r.label} ${r.region ?? ''} ${r.description ?? ''} ${this.i18n.source(r.label)}`.toLowerCase().includes(q));
    const found = all.filter(match);
    const g = this.group();
    const rows = g === 'all' ? found : found.filter((r) => r.group === g);
    const n = (id: GroupId) => found.filter((r) => r.group === id).length;
    const chips: ChipOption[] = [
      { value: 'all', label: `${this.i18n.t('src.filter.all')} (${found.length})` },
      ...GROUPS.filter((id) => n(id) || id === g).map((id) => ({ value: id, label: `${this.i18n.t(GROUP_LABEL[id])} (${n(id)})` })),
    ];
    return { chips, rows, on: rows.filter((r) => r.on).length, total: rows.filter((r) => r.toggle).length, sites: rows.some((r) => r.group === 'sites') };
  }

  protected groupLabel(g: GroupId): string {
    return GROUP_LABEL[g];
  }

  protected setGroup(v: string[]): void {
    this.group.set((v[0] as GroupId | undefined) ?? 'all');
  }

  protected flagChips(): ChipOption[] {
    return [{ value: 'rec', label: this.i18n.t('settings.src.recommended') }, { value: 'on', label: this.i18n.t('src.filter.on') }];
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
}
