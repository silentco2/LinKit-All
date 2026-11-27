import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { dayOf, fmtDate, localeOf } from '../locale';
import { FreeKey, Provider, SearchConfig } from '../types';

type AiMode = Provider | 'local';
type LocalServer = 'ollama' | 'lmstudio';
export type AiBody = { provider: Provider; model: string | null; api_base: string | null; api_key?: string | null; free_keys?: FreeKey[] };
/** A free provider as `GET /ai/free` lists it (providers/free.py). */
type FreePreset = { id: string; label: string; key_url: string; terms_url: string; limits: string; trains_on_data: boolean; needs_account: boolean };
/** One row of the Free models list: what the user typed (`key`) and the saved key, masked (`saved`). */
type FreeRow = { p: FreePreset; key: string; saved: string; account_id: string; enabled: boolean };
export type AiState = {
  state: 'idle' | 'testing' | 'ok' | 'fail';
  msg: string;
  /** A failed test: `usage_limit` = the plan is used up for now (not a broken setup), `error` = anything else. */
  kind?: 'usage_limit' | 'error';
  provider?: string;
  until?: string | null;
  /** A passed test, in plain words: who it connected to, with which model (null = the default one) and the tool's version. */
  label?: string;
  model?: string | null;
  version?: string | null;
};
type CheckResult = {
  ok: boolean;
  message: string;
  kind?: 'usage_limit' | 'error';
  provider?: string;
  until?: string | null;
  provider_label?: string;
  model?: string | null;
  version?: string | null;
};

/** As the server shows a saved key: the last 4 characters. */
const mask = (key: string): string => (key.length > 8 ? '••••' + key.slice(-4) : '••••');

/** Saved providers first, in the saved order, then the other presets in their default order. */
function freeRows(presets: FreePreset[], saved: FreeKey[]): FreeRow[] {
  const byId = new Map(presets.map((p) => [p.id, p]));
  const rows: FreeRow[] = saved
    .filter((k) => byId.has(k.id))
    .map((k) => ({ p: byId.get(k.id)!, key: '', saved: k.key, account_id: k.account_id ?? '', enabled: k.enabled }));
  const seen = new Set(rows.map((r) => r.p.id));
  return [...rows, ...presets.filter((p) => !seen.has(p.id)).map((p) => ({ p, key: '', saved: '', account_id: '', enabled: true }))];
}

/** The server's message once, without vendor links. */
const clean = (msg: string): string => msg.replace(/https?:\/\/\S+/g, '').replace(/\s{2,}/g, ' ').trim();

/**
 * Provider cards, auto-test and save-on-success: used by the first-run welcome and by Settings > AI.
 * It starts (reads the saved choice, then tests it) the first time `active` is true, so a host that keeps it mounted
 * but hidden does not run a model call before the user gets there. Wording above it is the host's (`intro`).
 */
@Component({
  selector: 'app-ai-connect',
  imports: [FormsModule, TPipe],
  host: { class: 'block space-y-5' },
  template: `
    @if (intro()) { <p class="text-sm text-slate-600 dark:text-slate-400">{{ intro() | t }}</p> }
    @if (loaded() && !hasCli()) { <p class="text-sm text-slate-500">{{ 'welcome.ai.none' | t }}</p> }
    @if (notice()) { <p class="alert alert-warn" role="status">{{ notice() }}</p> }
    <fieldset class="space-y-2">
      <legend class="sr-only">{{ 'setup.ai.provider' | t }}</legend>
      @for (p of providers; track p.id) {
        <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
               [class.border-brand-500]="mode() === p.id" [class.ring-2]="other(p.id)" [class.ring-amber-400]="other(p.id)">
          <input type="radio" name="provider" class="mt-1" [checked]="mode() === p.id" (change)="pick(p.id)">
          <span>
            <span class="font-medium">{{ p.label | t }}</span>
            @if ((p.id === 'codex_cli' || p.id === 'claude_cli') && available()[p.id]) { <span class="badge tier-high ms-2">{{ 'welcome.ai.found' | t }}</span> }
            <span class="block text-xs text-slate-500">{{ p.hint | t }}</span>
            @if (other(p.id)) { <span class="mt-1 block text-xs font-medium text-amber-800 dark:text-amber-300">{{ 'ai.limit.try' | t }}</span> }
          </span>
        </label>
      }
    </fieldset>

    @if (mode() === 'local') {
      <div class="space-y-3">
        @for (s of localServers; track s.id) {
          <div class="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <div class="flex items-center gap-2">
              <span class="font-medium">{{ s.label }}</span>
              @if (!local()) { <span class="badge">{{ 'setup.ai.checking' | t }}</span> }
              @else if (local()![s.id].running) { <span class="badge tier-high">{{ 'setup.ai.running' | t }}</span> }
              @else { <span class="badge tier-low">{{ 'setup.ai.notRunning' | t }}</span> }
            </div>
            @if (local()?.[s.id]?.running) {
              @if (local()![s.id].models.length === 0) { <p class="hint">{{ 'setup.ai.noModels' | t }}</p> }
              <div class="mt-2 flex flex-wrap gap-2">
                @for (m of local()![s.id].models; track m) {
                  <button type="button" class="btn" dir="ltr" [class.btn-primary]="model === s.prefix + m" (click)="pickLocal(s, m)">{{ m }}</button>
                }
              </div>
            }
          </div>
        }
        <button type="button" class="btn" (click)="scanLocal()">{{ 'setup.ai.scan' | t }}</button>
        @if (ai().state === 'idle' && !(model && apiBase)) { <p class="hint">{{ 'welcome.ai.pickModel' | t }}</p> }
      </div>
    }

    @if (mode() === 'litellm') {
      <div class="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <div>
          <label class="label" for="api-key">{{ 'setup.ai.apiKey' | t }}</label>
          <input id="api-key" type="password" dir="ltr" class="input" [(ngModel)]="apiKey" (change)="retest()"
                 [placeholder]="savedApiKey() ? ('setup.keys.keepHint' | t) : ('setup.ai.apiKeyPh' | t)" autocomplete="new-password" data-1p-ignore data-lpignore="true">
          @if (savedApiKey() && !apiKey) {
            <p class="hint">{{ 'setup.keys.keepHint' | t }}</p>
          } @else {
            <p class="hint">{{ 'setup.ai.apiKeyHint' | t }}</p>
          }
        </div>
        <div>
          <label class="label" for="api-model">{{ 'setup.ai.model' | t }}</label>
          <input id="api-model" dir="ltr" class="input" [(ngModel)]="model" (change)="retest()"
                 [placeholder]="'setup.ai.modelPhApi' | t">
        </div>
      </div>
    }

    @if (mode() === 'free') {
      <div class="space-y-3">
        <p class="alert alert-warn">{{ 'free.consent' | t }}</p>
        <p class="hint">{{ 'free.order' | t }}</p>
        <ol class="space-y-2">
          @for (r of freeRows(); track r.p.id; let i = $index, last = $last) {
            <li class="rounded-lg border border-slate-200 p-3 dark:border-slate-700" [class.opacity-60]="!r.enabled">
              <div class="flex flex-wrap items-center gap-2">
                <label class="flex items-center gap-2 font-medium">
                  <input type="checkbox" [checked]="r.enabled" (change)="toggleFree(i)">
                  <span class="sr-only">{{ 'free.use' | t }}</span>
                  <bdi dir="ltr">{{ r.p.label }}</bdi>
                </label>
                <span class="badge" [class.tier-low]="r.p.trains_on_data" [class.tier-high]="!r.p.trains_on_data">
                  {{ (r.p.trains_on_data ? 'free.trains' : 'free.noTrain') | t }}
                </span>
                <span class="ms-auto flex gap-1">
                  <button type="button" class="btn" [disabled]="i === 0" (click)="moveFree(i, -1)" [attr.aria-label]="'free.up' | t">↑</button>
                  <button type="button" class="btn" [disabled]="last" (click)="moveFree(i, 1)" [attr.aria-label]="'free.down' | t">↓</button>
                </span>
              </div>
              <p class="hint" dir="ltr">{{ r.p.limits }}</p>
              <p class="mt-1 flex gap-3 text-sm">
                <a class="link" [href]="r.p.key_url" target="_blank" rel="noopener noreferrer">{{ 'free.getKey' | t }}</a>
                <a class="link" [href]="r.p.terms_url" target="_blank" rel="noopener noreferrer">{{ 'free.terms' | t }}</a>
              </p>
              <details class="mt-2 text-sm">
                <summary class="btn cursor-pointer px-2 py-1 text-xs">{{ 'free.how' | t }}</summary>
                <ol class="mt-2 list-decimal space-y-1 ps-5">
                  @for (step of howTo(r.p.id); track $index) { <li dir="auto">{{ step }}</li> }
                </ol>
              </details>
              <div class="mt-2 grid gap-2 sm:grid-cols-2">
                <div>
                  <label class="label" [for]="'free-key-' + r.p.id">{{ 'free.key' | t }}</label>
                  <input [id]="'free-key-' + r.p.id" type="password" dir="ltr" class="input" autocomplete="new-password" data-1p-ignore data-lpignore="true"
                         [(ngModel)]="r.key" (change)="retest()" [placeholder]="r.saved || ('setup.ai.apiKeyPh' | t)">
                </div>
                @if (r.p.needs_account) {
                  <div>
                    <label class="label" [for]="'free-acc-' + r.p.id">{{ 'free.account' | t }}</label>
                    <input [id]="'free-acc-' + r.p.id" dir="ltr" class="input" autocomplete="off" [(ngModel)]="r.account_id" (change)="retest()">
                  </div>
                }
              </div>
            </li>
          }
        </ol>
        @if (ai().state === 'idle' && !freeKeys().length) { <p class="hint">{{ 'free.needKey' | t }}</p> }
      </div>
    }

    <div aria-live="polite">
      @switch (ai().state) {
        @case ('testing') { <p class="text-sm text-slate-500" role="status">{{ 'welcome.ai.testing' | t }}</p> }
        @case ('ok') {
          <div class="alert alert-ok" role="status">
            <p><strong>{{ 'welcome.ai.ok' | t }}</strong></p>
            <p class="mt-1" dir="auto" [attr.title]="ai().version ? ('ai.version' | t: { v: ai().version ?? '' }) : null">
              {{ 'ai.connected' | t: { provider: ai().label ?? '' } }}@if (ai().model) { <span class="gap-dot"></span><bdi dir="ltr">{{ ai().model }}</bdi> }
            </p>
          </div>
        }
        @case ('fail') {
          <div class="alert" [class]="ai().kind === 'usage_limit' ? 'alert-warn' : 'alert-error'" role="alert">
            @if (ai().kind === 'usage_limit') {
              <p><strong>{{ limitText() }}</strong></p>
              <p class="mt-1">{{ 'ai.limit.other' | t }}</p>
            } @else {
              <p dir="auto">{{ ai().msg }}</p>
            }
            <button type="button" class="btn mt-3" (click)="test()">{{ 'welcome.retry' | t }}</button>
          </div>
        }
        @case ('idle') {
          @if (mode() === 'litellm' && !apiReady()) {
            <p class="hint">{{ 'setup.ai.needKeyModel' | t }}</p>
          } @else if (mode() && (mode() !== 'local' || (model && apiBase)) && (mode() !== 'free' || freeKeys().length)) {
            <button type="button" class="btn" (click)="test()">{{ 'setup.ai.test' | t }}</button>
          }
        }
      }
    </div>
    @if (mode() && mode() !== 'local' && mode() !== 'litellm') { <p class="hint">{{ 'setup.ai.cliHint' | t }}</p> }

    @if (mode() && mode() !== 'free') {
      <details class="text-sm">
        <summary class="cursor-pointer font-medium">{{ 'welcome.ai.advanced' | t }}</summary>
        <div class="mt-3 space-y-3">
          @if (mode() === 'local' || mode() === 'litellm') {
            <div>
              <label class="label" for="api-base">{{ 'setup.ai.base' | t }}</label>
              <input id="api-base" dir="ltr" class="input" [(ngModel)]="apiBase" (change)="retest()" placeholder="http://127.0.0.1:1234/v1">
            </div>
          }
          @if (mode() !== 'litellm') {
            <div>
              <label class="label" for="model">{{ (mode() === 'local' ? 'setup.ai.model' : 'setup.ai.modelOpt') | t }}</label>
              <input id="model" dir="ltr" class="input" [(ngModel)]="model" (change)="retest()"
                     [placeholder]="(mode() === 'local' ? 'setup.ai.modelPhLocal' : 'setup.ai.modelPhCli') | t">
            </div>
          }
        </div>
      </details>
    }
  `,
})
export class AiConnect {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);

  /** i18n key of a short paragraph above the cards (the host's wording); empty for none. */
  readonly intro = input('');
  /** Start (load the saved choice and, unless `testOnLoad` is off, test it) the first time this is true. */
  readonly active = input(true);
  /** Settings turns this off: opening the page should not spend a model call; the saved choice shows a Test button. */
  readonly testOnLoad = input(true);
  /** How to save a connection that tested fine. Default: read `/search`, set `ai`, write it back. */
  readonly persist = input<((ai: AiBody) => Promise<void>) | null>(null);
  readonly stateChange = output<AiState>();
  /** After a test passed and the choice was saved. */
  readonly connected = output<void>();

  protected readonly providers: { id: AiMode; label: string; hint: string }[] = [
    { id: 'codex_cli', label: 'setup.ai.p.codex_cli', hint: 'setup.ai.p.codex_cli.hint' },
    { id: 'claude_cli', label: 'setup.ai.p.claude_cli', hint: 'setup.ai.p.claude_cli.hint' },
    { id: 'free', label: 'setup.ai.p.free', hint: 'setup.ai.p.free.hint' },
    { id: 'litellm', label: 'setup.ai.p.litellm', hint: 'setup.ai.p.litellm.hint' },
    { id: 'local', label: 'setup.ai.p.local', hint: 'setup.ai.p.local.hint' },
  ];
  protected readonly localServers: { id: LocalServer; label: string; prefix: string; base: string }[] = [
    { id: 'ollama', label: 'Ollama', prefix: 'ollama/', base: 'http://127.0.0.1:11434' },
    { id: 'lmstudio', label: 'LM Studio', prefix: 'openai/', base: 'http://127.0.0.1:1234/v1' },
  ];
  protected readonly available = signal<Partial<Record<Provider, boolean>>>({});
  protected readonly loaded = signal(false);
  protected readonly hasCli = computed(() => !!(this.available().codex_cli || this.available().claude_cli));
  protected readonly mode = signal<AiMode | null>(null);
  protected readonly ai = signal<AiState>({ state: 'idle', msg: '' });
  protected readonly local = signal<Record<LocalServer, { running: boolean; models: string[] }> | null>(null);
  protected readonly savedApiKey = signal<string | null>(null);
  protected readonly freeRows = signal<FreeRow[]>([]);
  /** Said when the first choice was out of uses and another detected AI was tried instead. */
  protected readonly notice = signal('');
  private readonly limited = new Set<AiMode>();
  protected model = '';
  protected apiBase = '';
  protected apiKey = '';
  /** The saved choice: picking its card again brings back its model and address instead of blank boxes. */
  private savedChoice: { mode: AiMode; model: string; apiBase: string } | null = null;
  private testId = 0;
  private entered = false;

  constructor() {
    effect(() => {
      if (this.active() && !this.entered) {
        this.entered = true;
        untracked(() => void this.enter());
      }
    });
  }

  private setAi(s: AiState): void {
    this.ai.set(s);
    this.stateChange.emit(s);
  }

  private async enter(): Promise<void> {
    try {
      const [r, cfg, presets] = await Promise.all([
        this.api.get<{ provider: Provider | null; available: Record<Provider, boolean> }>('/ai'),
        this.api.get<SearchConfig>('/search'),
        this.api.get<FreePreset[]>('/ai/free'),
      ]);
      this.freeRows.set(freeRows(presets, cfg.ai?.free_keys ?? []));
      this.available.set(r.available);
      const saved = cfg.ai;
      this.savedApiKey.set(saved?.api_key ?? null);
      let first: AiMode | null = null;
      if (saved?.provider) {
        first = saved.provider === 'litellm' && saved.api_base ? 'local' : saved.provider;
        this.model = saved.model ?? '';
        this.apiBase = saved.api_base ?? '';
        this.savedChoice = { mode: first, model: this.model, apiBase: this.apiBase };
      } else {
        first = r.available.codex_cli ? 'codex_cli' : r.available.claude_cli ? 'claude_cli' : null;
      }
      this.loaded.set(true);
      if (!first) return;
      this.mode.set(first);
      if (first === 'local') {
        await this.scanLocal();
        if (!this.model || !this.apiBase) return; // nothing to test until a model is picked
      }
      if (first === 'litellm' && !this.apiReady()) return;
      if (first === 'free' && !this.freeKeys().length) return;
      if (this.testOnLoad() || !saved?.provider) void this.test(true);
    } catch (e) {
      this.loaded.set(true);
      this.setAi({ state: 'fail', msg: (e as Error).message });
    }
  }

  protected pick(id: AiMode): void {
    this.mode.set(id);
    this.notice.set('');
    this.setAi({ state: 'idle', msg: '' });
    this.testId++; // an older test must not overwrite this choice
    const back = this.savedChoice?.mode === id ? this.savedChoice : null;
    this.apiBase = back?.apiBase ?? '';
    this.model = back?.model ?? '';
    this.apiKey = '';
    if (id === 'local') void this.scanLocal();
    else if (id === 'litellm') {
      if (this.apiReady()) void this.test();
    } else if (id === 'free') {
      if (this.freeKeys().length) void this.test();
    } else void this.test();
  }

  protected pickLocal(s: { prefix: string; base: string }, model: string): void {
    this.model = s.prefix + model;
    this.apiBase = s.base;
    void this.test();
  }

  protected async scanLocal(): Promise<void> {
    this.local.set(null);
    try {
      this.local.set(await this.api.get<Record<LocalServer, { running: boolean; models: string[] }>>('/ai/local'));
    } catch {
      this.local.set({ ollama: { running: false, models: [] }, lmstudio: { running: false, models: [] } });
    }
  }

  /** The model or address box changed: test again when there is enough to test. */
  protected retest(): void {
    if (!this.mode()) return;
    if (this.mode() === 'local') {
      if (this.model && this.apiBase) void this.test();
    } else if (this.mode() === 'litellm') {
      if (this.apiReady()) void this.test();
    } else if (this.mode() === 'free') {
      if (this.freeKeys().length) void this.test();
    } else {
      void this.test();
    }
  }

  /** After a usage-limit failure: the other cards worth trying (a detected CLI, or any API / local option). */
  protected other(id: AiMode): boolean {
    return this.ai().kind === 'usage_limit' && id !== this.mode() && (id === 'litellm' || id === 'local' || id === 'free' || !!this.available()[id]);
  }

  /** API key card: a key (typed or saved) and a model are both needed before a test can pass. */
  protected apiReady(): boolean {
    return !!((this.apiKey.trim() || this.savedApiKey()) && this.model.trim());
  }

  /** The steps of one provider's "how to get a key" text, one per line. */
  protected howTo(id: string): string[] {
    return this.i18n.t('free.how.' + id).split('\n');
  }

  /** The rows with a key (typed, or saved and sent back masked), in the user's order. */
  protected freeKeys(): FreeKey[] {
    return this.freeRows()
      .filter((r) => r.key.trim() || r.saved)
      .map((r) => ({ id: r.p.id, key: r.key.trim() || r.saved, account_id: r.account_id.trim(), enabled: r.enabled }));
  }

  protected moveFree(i: number, d: -1 | 1): void {
    const rows = [...this.freeRows()];
    [rows[i], rows[i + d]] = [rows[i + d], rows[i]];
    this.freeRows.set(rows);
    this.retest();
  }

  protected toggleFree(i: number): void {
    this.freeRows.update((rows) => rows.map((r, j) => (j === i ? { ...r, enabled: !r.enabled } : r)));
    this.retest();
  }

  protected limitText(): string {
    const a = this.ai();
    const until = dayOf(a.until);
    const provider = this.i18n.provider(a.provider ?? this.mode());
    return until ? this.i18n.t('ai.limit.until', { provider, until: fmtDate(localeOf(this.i18n.lang()), until, 'date') }) : this.i18n.t('ai.limit.now', { provider });
  }

  /**
   * Test the chosen connection; when it works, save it. `auto` (the first, unasked test): a detected AI that is out of
   * uses is not kept; the next detected one is tried instead, and the user is told.
   */
  protected async test(auto = false): Promise<void> {
    const mode = this.mode();
    if (!mode) return;
    const id = ++this.testId;
    this.setAi({ state: 'testing', msg: '' });
    const body: AiBody = {
      provider: mode === 'local' ? 'litellm' : mode,
      model: this.model.trim() || null,
      api_base: mode === 'local' ? this.apiBase.trim() || null : (this.apiBase.trim() || null),
      api_key: mode === 'litellm' ? (this.apiKey.trim() || null) : null,
      free_keys: this.freeKeys(), // always sent: switching to another AI keeps the free keys
    };
    try {
      const r = await this.api.post<CheckResult>('/ai/check', body);
      if (id !== this.testId) return;
      if (!r.ok) {
        if (r.kind === 'usage_limit') {
          this.limited.add(mode);
          const next = auto ? (['codex_cli', 'claude_cli'] as const).find((p) => this.available()[p] && !this.limited.has(p)) : undefined;
          if (next) {
            this.notice.set(this.i18n.t('ai.switched', { from: this.i18n.provider(mode), to: this.i18n.provider(next) }));
            this.mode.set(next);
            return this.test(true);
          }
          return this.setAi({ state: 'fail', msg: clean(r.message), kind: 'usage_limit', provider: r.provider ?? mode, until: r.until ?? null });
        }
        return this.setAi({ state: 'fail', msg: clean(r.message), kind: 'error' });
      }
      await (this.persist() ?? this.saveToSearch)(body);
      if (id !== this.testId) return;
      if (body.api_key) {
        this.savedApiKey.set(mask(body.api_key));
        this.apiKey = '';
      }
      this.savedChoice = { mode, model: this.model, apiBase: this.apiBase };
      this.freeRows.update((rows) => rows.map((r) => (r.key.trim() ? { ...r, saved: mask(r.key.trim()), key: '' } : r)));
      // never the raw server text ("claude_cli (default model) ok, 2.1.305"): the name, the model and (as a tooltip) the version
      const model = 'model' in r ? (r.model ?? null) : body.model;
      this.setAi({ state: 'ok', msg: '', label: r.provider_label || this.i18n.provider(mode === 'local' ? 'local' : mode), model, version: r.version ?? null });
      this.connected.emit();
    } catch (e) {
      if (id === this.testId) this.setAi({ state: 'fail', msg: clean((e as Error).message), kind: 'error' });
    }
  }

  private readonly saveToSearch = async (ai: AiBody): Promise<void> => {
    const cfg = await this.api.get<SearchConfig>('/search'); // fresh copy: do not overwrite changes made elsewhere
    cfg.ai = {
      provider: ai.provider,
      model: ai.model,
      api_base: ai.api_base,
      api_key: ai.api_key ?? cfg.ai.api_key ?? null,
      free_keys: ai.free_keys ?? cfg.ai.free_keys ?? [],
    };
    await this.api.put<SearchConfig>('/search', cfg);
  };
}
