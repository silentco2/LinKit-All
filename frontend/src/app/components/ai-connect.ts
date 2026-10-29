import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../api';
import { TPipe } from '../i18n';
import { Provider, SearchConfig } from '../types';

type AiMode = Provider | 'local';
type LocalServer = 'ollama' | 'lmstudio';
export type AiBody = { provider: Provider; model: string | null; api_base: string | null };
export type AiState = { state: 'idle' | 'testing' | 'ok' | 'fail'; msg: string };

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
    <fieldset class="space-y-2">
      <legend class="sr-only">{{ 'setup.ai.provider' | t }}</legend>
      @for (p of providers; track p.id) {
        <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
               [class.border-brand-500]="mode() === p.id">
          <input type="radio" name="provider" class="mt-1" [checked]="mode() === p.id" (change)="pick(p.id)">
          <span>
            <span class="font-medium">{{ p.label | t }}</span>
            @if ((p.id === 'codex_cli' || p.id === 'claude_cli') && available()[p.id]) { <span class="badge tier-high ms-2">{{ 'welcome.ai.found' | t }}</span> }
            <span class="block text-xs text-slate-500">{{ p.hint | t }}</span>
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

    <div aria-live="polite">
      @switch (ai().state) {
        @case ('testing') { <p class="text-sm text-slate-500" role="status">{{ 'welcome.ai.testing' | t }}</p> }
        @case ('ok') {
          <div class="alert alert-ok" role="status">
            <p><strong>{{ 'welcome.ai.ok' | t }}</strong></p>
            @if (ai().msg) { <p class="mt-1" dir="auto">{{ ai().msg }}</p> }
          </div>
        }
        @case ('fail') {
          <div class="alert alert-error" role="alert">
            <p><strong>{{ 'welcome.ai.fail' | t }}</strong></p>
            <p class="mt-1" dir="auto">{{ ai().msg }}</p>
            @if (mode() === 'litellm') { <p class="mt-1 text-xs">{{ 'setup.ai.keyHintA' | t }}<code dir="ltr">LINKIT_API_KEY</code>{{ 'setup.ai.keyHintB' | t }}</p> }
            <button type="button" class="btn mt-3" (click)="test()">{{ 'welcome.retry' | t }}</button>
          </div>
        }
        @case ('idle') {
          @if (mode() && (mode() !== 'local' || (model && apiBase))) {
            <button type="button" class="btn" (click)="test()">{{ 'setup.ai.test' | t }}</button>
          }
        }
      }
    </div>
    @if (mode() && mode() !== 'local' && mode() !== 'litellm') { <p class="hint">{{ 'setup.ai.cliHint' | t }}</p> }

    @if (mode()) {
      <details class="text-sm" [attr.open]="mode() === 'litellm' && ai().state === 'fail' ? '' : null">
        <summary class="cursor-pointer font-medium">{{ 'welcome.ai.advanced' | t }}</summary>
        <div class="mt-3 space-y-3">
          @if (mode() === 'local') {
            <div>
              <label class="label" for="api-base">{{ 'setup.ai.base' | t }}</label>
              <input id="api-base" dir="ltr" class="input" [(ngModel)]="apiBase" (change)="retest()" placeholder="http://127.0.0.1:1234/v1">
            </div>
          }
          <div>
            <label class="label" for="model">{{ (mode() === 'local' ? 'setup.ai.model' : 'setup.ai.modelOpt') | t }}</label>
            <input id="model" dir="ltr" class="input" [(ngModel)]="model" (change)="retest()"
                   [placeholder]="(mode() === 'local' ? 'setup.ai.modelPhLocal' : mode() === 'litellm' ? 'setup.ai.modelPhApi' : 'setup.ai.modelPhCli') | t">
          </div>
        </div>
      </details>
    }
  `,
})
export class AiConnect {
  private readonly api = inject(Api);

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
  protected model = '';
  protected apiBase = '';
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
      const [r, cfg] = await Promise.all([
        this.api.get<{ provider: Provider | null; available: Record<Provider, boolean> }>('/ai'),
        this.api.get<SearchConfig>('/search'),
      ]);
      this.available.set(r.available);
      const saved = cfg.ai;
      let first: AiMode | null = null;
      if (saved?.provider) {
        first = saved.provider === 'litellm' && saved.api_base ? 'local' : saved.provider;
        this.model = saved.model ?? '';
        this.apiBase = saved.api_base ?? '';
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
      if (this.testOnLoad() || !saved?.provider) void this.test();
    } catch (e) {
      this.loaded.set(true);
      this.setAi({ state: 'fail', msg: (e as Error).message });
    }
  }

  protected pick(id: AiMode): void {
    this.mode.set(id);
    this.setAi({ state: 'idle', msg: '' });
    this.testId++; // an older test must not overwrite this choice
    this.apiBase = '';
    this.model = '';
    if (id === 'local') void this.scanLocal();
    else void this.test();
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
    if (this.mode() && (this.mode() !== 'local' || (this.model && this.apiBase))) void this.test();
  }

  /** Test the chosen connection; when it works, save it. */
  protected async test(): Promise<void> {
    const mode = this.mode();
    if (!mode) return;
    const id = ++this.testId;
    this.setAi({ state: 'testing', msg: '' });
    const body: AiBody = { provider: mode === 'local' ? 'litellm' : mode, model: this.model.trim() || null, api_base: mode === 'local' ? this.apiBase.trim() || null : null };
    try {
      const r = await this.api.post<{ ok: boolean; message: string }>('/ai/check', body);
      if (id !== this.testId) return;
      if (!r.ok) return this.setAi({ state: 'fail', msg: r.message });
      await (this.persist() ?? this.saveToSearch)(body);
      if (id !== this.testId) return;
      this.setAi({ state: 'ok', msg: r.message });
      this.connected.emit();
    } catch (e) {
      if (id === this.testId) this.setAi({ state: 'fail', msg: (e as Error).message });
    }
  }

  private readonly saveToSearch = async (ai: AiBody): Promise<void> => {
    const cfg = await this.api.get<SearchConfig>('/search'); // fresh copy: do not overwrite changes made elsewhere
    cfg.ai = ai;
    await this.api.put<SearchConfig>('/search', cfg);
  };
}
