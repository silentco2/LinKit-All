import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { Api } from '../../api';
import { KeyForm } from '../../components/key-form';
import { VaultGate } from '../../components/vault-gate';
import { I18n, SourcePipe, TPipe } from '../../i18n';
import { ApiKeyProvider, InferPayload, JobSource, lines, SourceList, unlines } from '../../types';
import { Field, Saved } from './saved';
import { SettingsStore } from './store';

// The risk acknowledgement is per browser (a per-viewer convenience), so localStorage is enough.
const LI_ACK = 'linkit.linkedinAck';
function readAck(): boolean {
  try {
    return localStorage.getItem(LI_ACK) === '1';
  } catch {
    return false;
  }
}

type Group = JobSource['kind'] | 'recommended';
type Note = { kind: 'ok' | 'info' | 'error'; text: string };
/** These two have their own blocks on this page, so they never appear as rows in the list. */
const OWN_BLOCK = new Set(['telegram', 'linkedin_posts']);

/** Settings > Sources: where to search, the opt-in source list (with inline API keys) and LinkedIn hiring posts. */
@Component({
  selector: 'app-settings-sources',
  imports: [Field, Saved, KeyForm, VaultGate, SourcePipe, TPipe],
  template: `
    <div class="space-y-6">
      <section class="card space-y-5">
        <h2>{{ 'setup.search.where' | t }}</h2>

        <app-field key="sources.jobspy" [label]="'setup.search.sites' | t">
          <div class="flex flex-wrap gap-4" role="group" [attr.aria-label]="'setup.search.sites' | t">
            @for (site of jobspySites; track site) {
              <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="has('sources.jobspy', site)" (change)="toggle('sources.jobspy', site)"><bdi>{{ site | src }}</bdi></label>
            }
          </div>
        </app-field>

        <app-field key="sources.regional" [label]="'settings.src.regional' | t">
          <div class="flex flex-wrap gap-4" role="group" [attr.aria-label]="'settings.src.regional' | t">
            @for (site of regionalSites; track site.id) {
              <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="has('sources.regional', site.id)" (change)="toggle('sources.regional', site.id)"><bdi>{{ site.label }}</bdi></label>
            }
          </div>
        </app-field>

        <div class="max-w-xs">
          <app-field key="sources.jobspy_country" for="country" [label]="'settings.src.country' | t">
            <input id="country" dir="ltr" class="input" placeholder="egypt" [value]="store.cfg.sources.jobspy_country" (change)="store.update('sources.jobspy_country', val($event).trim())">
          </app-field>
        </div>

        <app-field key="sources.companies" for="companies" [label]="'setup.search.companies' | t" [hint]="'setup.search.companiesHint' | t">
          <textarea id="companies" dir="ltr" class="input h-32 font-mono text-xs" [value]="unlines(store.cfg.sources.companies)" (change)="store.update('sources.companies', lines(val($event)))"
                    placeholder="https://boards.greenhouse.io/stripe&#10;https://jobs.lever.co/palantir&#10;https://www.notion.com/careers"></textarea>
        </app-field>

        <div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-2 text-sm font-medium"><input type="checkbox" role="switch" [checked]="has('sources.enabled', 'telegram')" (change)="toggle('sources.enabled', 'telegram')">{{ 'setup.search.telegram' | t }}</label>
            <app-saved class="ms-auto" field="sources.enabled" />
          </div>
          <div class="mt-3">
            <app-field key="sources.telegram_channels" for="telegram" [label]="'setup.search.telegramChannels' | t" [hint]="'setup.search.telegramHint' | t">
              <textarea id="telegram" dir="ltr" class="input h-32 font-mono text-xs" [disabled]="!has('sources.enabled', 'telegram')" [value]="unlines(store.cfg.sources.telegram_channels)"
                        (change)="store.update('sources.telegram_channels', lines(val($event)))" placeholder="@channel_name&#10;https://t.me/another_channel"></textarea>
            </app-field>
          </div>
        </div>

        <div>
          <app-field key="sources.use_discovered_boards" for="discovered" [check]="true" [label]="'setup.sources.discovered' | t" [hint]="'setup.sources.discoveredHint' | t">
            <input id="discovered" type="checkbox" class="mt-1" [checked]="store.cfg.sources.use_discovered_boards" (change)="store.update('sources.use_discovered_boards', checked($event))">
          </app-field>
          <div class="mt-3 max-w-xs">
            <app-field key="sources.boards_per_run" for="boards" [label]="'setup.sources.perRun' | t">
              <input id="boards" type="number" min="0" max="20000" class="input" [disabled]="!store.cfg.sources.use_discovered_boards" [value]="store.cfg.sources.boards_per_run" (change)="store.update('sources.boards_per_run', num($event))">
            </app-field>
          </div>
        </div>
      </section>

      <section class="card space-y-3">
        <h2>{{ 'setup.sources.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.sources.intro' | t }}</p>
        @if (list().ats_count) { <p class="hint">{{ 'setup.sources.ats' | t: { n: list().ats_count } }}</p> }
        @if (loadFailed()) { <div class="alert alert-error" role="alert">{{ 'setup.sources.loadFailed' | t }}</div> }
        <div class="flex flex-wrap gap-2" role="group" [attr.aria-label]="'setup.sources.title' | t">
          @for (g of groups; track g) {
            <button type="button" class="btn" [class.btn-primary]="group() === g" [attr.aria-pressed]="group() === g" (click)="group.set(g)">
              {{ (g === 'recommended' ? 'settings.src.recommended' : 'setup.sources.group.' + g) | t }} ({{ groupCount(g) }})
            </button>
          }
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <input type="search" class="input max-w-xs" [value]="query()" (input)="query.set(val($event))" [attr.aria-label]="'setup.sources.search' | t" [placeholder]="'setup.sources.search' | t">
          <button type="button" class="btn" (click)="setShown(true)">{{ 'setup.sources.enableAll' | t }}</button>
          <button type="button" class="btn" (click)="setShown(false)">{{ 'setup.sources.disableAll' | t }}</button>
          <span class="text-xs text-slate-500">{{ 'setup.sources.count' | t: { on: shownOn(), n: shown().length } }}</span>
          <app-saved class="ms-auto" field="sources.enabled" />
        </div>
        <ul class="max-h-[32rem] divide-y divide-slate-200 overflow-y-auto rounded border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
          @for (s of shown(); track s.name) {
            <li class="px-3 py-2">
              <label class="flex items-start gap-2 text-sm">
                <input type="checkbox" class="mt-1" [checked]="has('sources.enabled', s.name)" (change)="toggleSource(s)">
                <span class="min-w-0 flex-1">
                  <span class="font-medium"><bdi>{{ s.label }}</bdi></span>
                  @if (s.region) { <span class="text-xs text-slate-500"> · <bdi>{{ s.region }}</bdi></span> }
                  @if (rec().has(s.name)) { <span class="badge alert-info ms-2">{{ 'settings.src.badge' | t }}</span> }
                  <span class="block text-xs text-slate-500 dark:text-slate-400" dir="auto">{{ s.description }}</span>
                </span>
              </label>
              @if (s.needs_key; as key) {
                <button type="button" class="badge ms-6 mt-1 underline" [class]="keyOk(s) ? 'tier-high' : 'tier-mid'" [attr.aria-expanded]="openKey() === s.name" (click)="openKey.set(openKey() === s.name ? null : s.name)">
                  {{ (keyOk(s) ? 'setup.sources.keyReady' : 'setup.sources.needsKey') | t }}
                </button>
                @if (openKey() === s.name && provider(key); as p) {
                  <div class="ms-6 mt-2 space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                    <p class="hint" dir="auto">{{ p.note }}</p>
                    <app-vault-gate reason="settings.src.keyVault" (ready)="loadKeys()">
                      <app-key-form [provider]="p" (changed)="keys.set($event)" />
                    </app-vault-gate>
                  </div>
                }
              }
            </li>
          } @empty {
            <li class="px-3 py-2 text-sm text-slate-500">{{ (loading() ? 'common.loading' : 'setup.sources.empty') | t }}</li>
          }
        </ul>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'setup.linkedin.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.linkedin.intro' | t }}</p>
        <div class="alert alert-error" role="alert">{{ 'setup.linkedin.warn' | t }}</div>
        @if (!liOn()) {
          <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="liAck()" (change)="setLiAck($event)">{{ 'setup.linkedin.ack' | t }}</label>
        }
        <div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-2 text-sm font-medium" [class.opacity-50]="!liOn() && !liAck()">
              <input type="checkbox" role="switch" [checked]="liOn()" [disabled]="!liOn() && !liAck()" (change)="toggle('sources.enabled', 'linkedin_posts')">{{ 'setup.linkedin.enable' | t }}
            </label>
            <app-saved class="ms-auto" field="sources.enabled" />
          </div>
          @if (!liOn() && !liAck()) { <p class="hint">{{ 'setup.linkedin.needAck' | t }}</p> }
        </div>
        <div class="flex flex-wrap gap-3">
          <button type="button" class="btn" (click)="liSignin()" [disabled]="liBusy()">{{ 'setup.linkedin.signin' | t }}</button>
          <button type="button" class="btn" (click)="liCheck()" [disabled]="liBusy()">{{ 'setup.linkedin.check' | t }}</button>
        </div>
        <p class="hint">{{ 'setup.linkedin.checkHint' | t }}</p>
        @if (liNote(); as n) { <div class="alert" [class.alert-ok]="n.kind === 'ok'" [class.alert-info]="n.kind === 'info'" [class.alert-error]="n.kind === 'error'" role="status" dir="auto">{{ n.text }}</div> }
        <app-field key="sources.linkedin_keywords" for="li-keywords" [label]="'setup.linkedin.keywords' | t" [hint]="'setup.linkedin.keywordsHint' | t">
          <textarea id="li-keywords" dir="auto" class="input h-28" [value]="unlines(store.cfg.sources.linkedin_keywords)" (change)="store.update('sources.linkedin_keywords', lines(val($event)))"
                    placeholder="python developer hiring&#10;مطلوب مهندس برمجيات"></textarea>
        </app-field>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="sources.linkedin_window" for="li-window" [label]="'setup.linkedin.window' | t">
            <select id="li-window" class="input" (change)="store.update('sources.linkedin_window', val($event))">
              <option value="day" [selected]="store.cfg.sources.linkedin_window === 'day'">{{ 'setup.linkedin.window.day' | t }}</option>
              <option value="week" [selected]="store.cfg.sources.linkedin_window === 'week'">{{ 'setup.linkedin.window.week' | t }}</option>
            </select>
          </app-field>
          <app-field key="sources.linkedin_max_posts" for="li-max" [label]="'setup.linkedin.maxPosts' | t">
            <input id="li-max" type="number" min="1" max="200" class="input" [value]="store.cfg.sources.linkedin_max_posts" (change)="store.update('sources.linkedin_max_posts', num($event))">
          </app-field>
        </div>
        <app-field key="sources.linkedin_headless" for="li-headless" [check]="true" [label]="'setup.linkedin.headless' | t" [hint]="'setup.linkedin.headlessHint' | t">
          <input id="li-headless" type="checkbox" role="switch" class="mt-1" [checked]="store.cfg.sources.linkedin_headless" (change)="store.update('sources.linkedin_headless', checked($event))">
        </app-field>
      </section>

      <details class="card text-sm">
        <summary class="cursor-pointer font-medium">{{ 'settings.src.how' | t }}</summary>
        <ul class="mt-3 list-disc space-y-2 ps-5 text-slate-600 dark:text-slate-300">
          <li>{{ 'setup.search.wuzzufHint' | t }}</li>
          <li>{{ 'settings.src.glassdoor' | t }}</li>
        </ul>
      </details>
    </div>
  `,
})
export class SourcesSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly lines = lines;
  protected readonly unlines = unlines;
  protected readonly jobspySites = ['linkedin', 'indeed', 'glassdoor', 'google', 'zip_recruiter'];
  protected readonly regionalSites = [
    { id: 'wuzzuf', label: 'Wuzzuf' },
    { id: 'bayt', label: 'Bayt' },
    { id: 'forasna', label: 'Forasna' },
  ];
  protected readonly groups: Group[] = ['aggregator', 'board', 'company', 'recommended'];
  protected readonly list = signal<SourceList>({ ats_count: 0, sources: [] });
  protected readonly keys = signal<ApiKeyProvider[]>([]);
  /** Plugin names the country/track presets recommend (empty when LinKit has nothing to go on). */
  protected readonly rec = signal<Set<string>>(new Set());
  protected readonly loading = signal(true);
  protected readonly loadFailed = signal(false);
  protected readonly group = signal<Group>('aggregator');
  protected readonly query = signal('');
  protected readonly openKey = signal<string | null>(null);
  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    const g = this.group();
    return this.list().sources.filter(
      (s) => !OWN_BLOCK.has(s.name) && (g === 'recommended' ? this.rec().has(s.name) : s.kind === g) && (!q || `${s.name} ${s.label} ${s.region} ${s.description}`.toLowerCase().includes(q)),
    );
  });

  protected readonly liAck = signal(readAck());
  protected readonly liBusy = signal(false);
  protected readonly liNote = signal<Note | null>(null);

  ngOnInit(): void {
    this.api.get<SourceList>('/sources').then((l) => this.list.set(l)).catch(() => this.loadFailed.set(true)).finally(() => this.loading.set(false));
    void this.loadKeys();
    // no CV or country yet: nothing is recommended, which is fine
    this.api.get<InferPayload>('/infer').then((p) => this.rec.set(new Set(p.sources.enabled))).catch(() => undefined);
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  protected checked(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  /** The number in the box; an empty box is NaN, which the server rejects with a message for this field. */
  protected num(e: Event): number {
    const box = e.target as HTMLInputElement;
    return box.value.trim() === '' ? NaN : box.valueAsNumber;
  }

  protected has(key: string, item: string): boolean {
    return (this.store.get(key) as string[]).includes(item);
  }

  /** Add or remove one item of a list setting and save. */
  protected toggle(key: string, item: string): void {
    const cur = this.store.get(key) as string[];
    this.store.update(key, cur.includes(item) ? cur.filter((x) => x !== item) : [...cur, item]);
  }

  // ---- the plugin list -------------------------------------------------------------------

  protected groupCount(g: Group): number {
    return this.list().sources.filter((s) => !OWN_BLOCK.has(s.name) && (g === 'recommended' ? this.rec().has(s.name) : s.kind === g)).length;
  }

  protected shownOn(): number {
    return this.shown().filter((s) => this.has('sources.enabled', s.name)).length;
  }

  /** Tick or untick every row now shown (the open group, after the search box). */
  protected setShown(on: boolean): void {
    const enabled = this.store.cfg.sources.enabled;
    const names = new Set(this.shown().map((s) => s.name));
    this.store.update('sources.enabled', on ? [...new Set([...enabled, ...names])] : enabled.filter((n) => !names.has(n)));
  }

  /** Turning on a source that needs a key and has none opens its key form right there. */
  protected toggleSource(s: JobSource): void {
    this.toggle('sources.enabled', s.name);
    if (this.has('sources.enabled', s.name) && s.needs_key && !this.keyOk(s)) this.openKey.set(s.name);
  }

  protected provider(name: string): ApiKeyProvider | undefined {
    return this.keys().find((k) => k.name === name);
  }

  protected keyOk(s: JobSource): boolean {
    return !!this.provider(s.needs_key ?? '')?.configured;
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

  protected setLiAck(e: Event): void {
    const on = this.checked(e);
    this.liAck.set(on);
    try {
      if (on) localStorage.setItem(LI_ACK, '1');
      else localStorage.removeItem(LI_ACK);
    } catch {
      // storage blocked: the box still works for this visit
    }
  }

  protected async liSignin(): Promise<void> {
    await this.li(async () => {
      await this.api.post('/linkedin/signin');
      return { kind: 'info', text: this.i18n.t('setup.linkedin.signinHint') };
    });
  }

  protected async liCheck(): Promise<void> {
    await this.li(async () => {
      const r = await this.api.get<{ state: 'ok' | 'logged_out' | 'challenge' }>('/linkedin/session');
      return { kind: r.state === 'ok' ? 'ok' : 'error', text: this.i18n.t('setup.linkedin.session.' + r.state) };
    });
  }

  private async li(action: () => Promise<Note>): Promise<void> {
    this.liBusy.set(true);
    this.liNote.set(null);
    try {
      this.liNote.set(await action());
    } catch (e) {
      this.liNote.set({ kind: 'error', text: (e as Error).message });
    } finally {
      this.liBusy.set(false);
    }
  }
}
