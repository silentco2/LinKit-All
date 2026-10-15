import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '../api';
import { lines, Profile, Provider, SearchConfig, Segment, Status, unlines } from '../types';

type Step = 'profile' | 'ai' | 'search' | 'filters' | 'finish';

@Component({
  selector: 'app-setup',
  imports: [FormsModule],
  template: `
    <h1>Setup</h1>
    <p class="mt-1 text-sm text-slate-500">Everything stays on this computer. Only your chosen AI sees your CV and job text.</p>

    <ol class="mt-6 flex flex-wrap gap-2" aria-label="Setup steps">
      @for (s of steps; track s.id; let i = $index) {
        <li>
          <button type="button" class="btn" [class.btn-primary]="step() === s.id" (click)="step.set(s.id)"
                  [attr.aria-current]="step() === s.id ? 'step' : null">
            {{ i + 1 }}. {{ s.label }} @if (done(s.id)) { <span aria-label="done">✓</span> }
          </button>
        </li>
      }
    </ol>

    @if (message(); as m) {
      <div class="alert mt-4" [class.alert-ok]="m.ok" [class.alert-error]="!m.ok" role="status">{{ m.text }}</div>
    }

    @if (profile && cfg) {
      <div class="mt-6 max-w-3xl space-y-6">
        @switch (step()) {
          @case ('profile') {
            <section class="card space-y-4">
              <h2>Your profile</h2>
              <div class="grid gap-4 sm:grid-cols-2">
                <div><label class="label" for="name">Full name</label><input id="name" class="input" [(ngModel)]="profile.full_name" autocomplete="name"></div>
                <div><label class="label" for="email">Email</label><input id="email" type="email" class="input" [(ngModel)]="profile.email" autocomplete="email"></div>
                <div><label class="label" for="phone">Phone</label><input id="phone" class="input" [(ngModel)]="profile.phone" autocomplete="tel"></div>
                <div><label class="label" for="loc">Location</label><input id="loc" class="input" [(ngModel)]="profile.location" placeholder="Cairo, Egypt"></div>
              </div>
              <div>
                <label class="label" for="skills">Skills (one per line)</label>
                <textarea id="skills" class="input h-28" [value]="unlines(profile.skills)" (change)="profile.skills = lines(val($event))"></textarea>
                <p class="hint">Tailoring may only add skills from your CV or this list. Ranking also uses it.</p>
              </div>
              <div>
                <label class="label" for="facts">Locked facts (one per line)</label>
                <textarea id="facts" class="input h-28" [value]="unlines(profile.locked_facts)" (change)="profile.locked_facts = lines(val($event))"
                          placeholder="Acme Corp&#10;Senior Software Engineer&#10;B.Sc. Computer Science"></textarea>
                <p class="hint">Text the AI must never change: employers, titles, degrees. Numbers, dates and contact details are always locked.</p>
              </div>
              <button class="btn btn-primary" (click)="saveProfile()" [disabled]="busy()">Save profile</button>
            </section>

            <section class="card space-y-4">
              <h2>Your CV</h2>
              <p class="text-sm text-slate-600 dark:text-slate-400">Upload your CV as a Word file (.docx). Its layout and styling are never changed, only words.</p>
              <div class="flex flex-wrap items-center gap-3">
                <label class="btn cursor-pointer">
                  {{ profile.cv_name ? 'Replace CV' : 'Upload CV' }}
                  <input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" class="sr-only" (change)="upload($event)">
                </label>
                @if (profile.cv_name) {
                  <span class="text-sm">{{ profile.cv_name }}</span>
                  @if (status()?.libreoffice) {
                    <a class="btn" href="/api/profile/cv/pdf" target="_blank" rel="noopener">Preview PDF</a>
                  }
                }
              </div>
              @if (status() && !status()!.libreoffice) {
                <div class="alert alert-error">LibreOffice isn't installed, so PDF preview and tailoring won't work yet. Run <code>linkit doctor</code>.</div>
              }
              @if (segments().length) {
                <details class="text-sm">
                  <summary class="cursor-pointer font-medium">What LinKit reads from your CV ({{ segments().length }} parts)</summary>
                  <ol class="mt-2 max-h-72 space-y-1 overflow-auto rounded-lg bg-slate-50 p-3 dark:bg-slate-950">
                    @for (s of segments(); track s.id) { <li class="whitespace-pre-wrap"><span class="text-slate-400">{{ s.id }}</span> {{ s.text }}</li> }
                  </ol>
                </details>
              }
            </section>
          }

          @case ('ai') {
            <section class="card space-y-4">
              <h2>Your AI</h2>
              <p class="text-sm text-slate-600 dark:text-slate-400">LinKit uses your own AI subscription or API key to score jobs and tailor your CV.</p>
              <fieldset class="space-y-2">
                <legend class="label">Provider</legend>
                @for (p of providers; track p.id) {
                  <label class="flex items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                         [class.border-brand-500]="cfg.ai.provider === p.id">
                    <input type="radio" name="provider" class="mt-1" [value]="p.id" [(ngModel)]="cfg.ai.provider">
                    <span>
                      <span class="font-medium">{{ p.label }}</span>
                      @if (available()[p.id] === false) { <span class="badge tier-low ml-2">not installed</span> }
                      <span class="block text-xs text-slate-500">{{ p.hint }}</span>
                    </span>
                  </label>
                }
              </fieldset>
              <div>
                <label class="label" for="model">Model (optional)</label>
                <input id="model" class="input" [(ngModel)]="cfg.ai.model" [placeholder]="cfg.ai.provider === 'litellm' ? 'e.g. openai/gpt-5-mini' : 'leave empty for the CLI default'">
              </div>
              @if (cfg.ai.provider !== 'litellm') {
                <p class="hint">Usage counts against your own plan limits. If a limit is reached, the run pauses and continues later.</p>
              } @else {
                <p class="hint">Set your API key in the LINKIT_API_KEY environment variable for now (the encrypted vault comes later).</p>
              }
              <div class="flex gap-3">
                <button class="btn" (click)="testAI()" [disabled]="busy() || !cfg.ai.provider">Test connection</button>
                <button class="btn btn-primary" (click)="saveSearch('AI settings saved')" [disabled]="busy() || !cfg.ai.provider">Save</button>
              </div>
            </section>
          }

          @case ('search') {
            <section class="card space-y-4">
              <h2>What to search</h2>
              <div class="grid gap-4 sm:grid-cols-2">
                <div>
                  <label class="label" for="queries">Job searches (one per line)</label>
                  <textarea id="queries" class="input h-28" [value]="unlines(cfg.search.queries)" (change)="cfg.search.queries = lines(val($event))" placeholder="python developer&#10;backend engineer"></textarea>
                </div>
                <div>
                  <label class="label" for="locations">Locations (one per line)</label>
                  <textarea id="locations" class="input h-28" [value]="unlines(cfg.search.locations)" (change)="cfg.search.locations = lines(val($event))" placeholder="Cairo, Egypt&#10;Remote"></textarea>
                  <p class="hint">Leave empty for anywhere.</p>
                </div>
                <div><label class="label" for="days">Posted within (days)</label><input id="days" type="number" min="1" class="input" [(ngModel)]="cfg.search.posted_within_days"></div>
                <div><label class="label" for="max">Max results per search, per site</label><input id="max" type="number" min="1" max="1000" class="input" [(ngModel)]="cfg.search.max_results_per_query"></div>
              </div>
            </section>
            <section class="card space-y-4">
              <h2>Where to search</h2>
              <fieldset>
                <legend class="label">Job sites</legend>
                <div class="flex flex-wrap gap-4">
                  @for (site of jobspySites; track site) {
                    <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.sources.jobspy.includes(site)" (change)="toggle(cfg.sources.jobspy, site)">{{ site }}</label>
                  }
                  @for (site of regionalSites; track site) {
                    <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.sources.regional.includes(site)" (change)="toggle(cfg.sources.regional, site)">{{ site }}</label>
                  }
                </div>
                <p class="hint">Wuzzuf only fetches jobs whose title contains every word of one of your searches (it allows 1 page per 10 s).</p>
              </fieldset>
              <div class="max-w-xs">
                <label class="label" for="country">Country for Indeed / Glassdoor</label>
                <input id="country" class="input" [(ngModel)]="cfg.sources.jobspy_country" placeholder="egypt">
              </div>
              <div>
                <label class="label" for="companies">Company career pages (one per line)</label>
                <textarea id="companies" class="input h-32 font-mono text-xs" [value]="unlines(cfg.sources.companies)" (change)="cfg.sources.companies = lines(val($event))"
                          placeholder="https://boards.greenhouse.io/stripe&#10;https://jobs.lever.co/palantir&#10;https://www.notion.com/careers"></textarea>
                <p class="hint">Paste any careers page. Greenhouse, Lever and Ashby boards are detected automatically.</p>
              </div>
              <button class="btn btn-primary" (click)="saveSearch('Search saved')" [disabled]="busy()">Save search</button>
            </section>
          }

          @case ('filters') {
            <section class="card space-y-4">
              <h2>Filters</h2>
              <p class="text-sm text-slate-600 dark:text-slate-400">Free and instant: jobs that fail these are dropped before any AI is used.</p>
              <div class="grid gap-4 sm:grid-cols-2">
                <div>
                  <label class="label" for="inc">Title must contain one of</label>
                  <textarea id="inc" class="input h-24" [value]="unlines(cfg.filters.title_include)" (change)="cfg.filters.title_include = lines(val($event))" placeholder="engineer&#10;developer"></textarea>
                </div>
                <div>
                  <label class="label" for="exc">Title must not contain</label>
                  <textarea id="exc" class="input h-24" [value]="unlines(cfg.filters.title_exclude)" (change)="cfg.filters.title_exclude = lines(val($event))" placeholder="intern&#10;director"></textarea>
                </div>
                <div>
                  <label class="label" for="floc">Job location must contain one of</label>
                  <textarea id="floc" class="input h-24" [value]="unlines(cfg.filters.locations)" (change)="cfg.filters.locations = lines(val($event))" placeholder="egypt&#10;remote"></textarea>
                </div>
                <div>
                  <label class="label" for="black">Never apply to these companies</label>
                  <textarea id="black" class="input h-24" [value]="unlines(cfg.filters.company_blacklist)" (change)="cfg.filters.company_blacklist = lines(val($event))"></textarea>
                </div>
                <div>
                  <label class="label" for="remote">Work mode</label>
                  <select id="remote" class="input" [(ngModel)]="cfg.filters.remote">
                    <option value="any">Any</option><option value="remote">Remote only</option><option value="hybrid">Hybrid only</option><option value="onsite">On-site only</option>
                  </select>
                </div>
                <div><label class="label" for="salary">Minimum yearly salary</label><input id="salary" type="number" min="0" class="input" [(ngModel)]="cfg.filters.salary_floor"><p class="hint">Only checked when a posting states its salary.</p></div>
              </div>
              <fieldset>
                <legend class="label">Seniority (none = any)</legend>
                <div class="flex flex-wrap gap-4">
                  @for (level of seniorities; track level) {
                    <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.filters.seniority.includes(level)" (change)="toggle(cfg.filters.seniority, level)">{{ level }}</label>
                  }
                </div>
              </fieldset>
              <label class="flex items-center gap-2 text-sm"><input type="checkbox" [(ngModel)]="cfg.filters.one_per_company">Apply to at most one job per company</label>
            </section>
            <section class="card space-y-4">
              <h2>AI scoring</h2>
              <div class="grid gap-4 sm:grid-cols-2">
                <div><label class="label" for="high">Auto-apply from score</label><input id="high" type="number" min="1" max="10" class="input" [(ngModel)]="cfg.matching.tier_high"><p class="hint">Scores {{ cfg.matching.tier_high }}–10 are applied to automatically.</p></div>
                <div><label class="label" for="mid">Ask me from score</label><input id="mid" type="number" min="1" max="10" class="input" [(ngModel)]="cfg.matching.tier_mid"><p class="hint">Scores {{ cfg.matching.tier_mid }}–{{ cfg.matching.tier_high - 1 }} wait in your review queue. Lower ones are hidden.</p></div>
                <div><label class="label" for="aimax">Jobs sent to the AI per run</label><input id="aimax" type="number" min="0" class="input" [(ngModel)]="cfg.matching.ai_max_jobs"><p class="hint">The best matches after free local ranking. The rest count as low.</p></div>
                <div><label class="label" for="batch">Jobs per AI call</label><input id="batch" type="number" min="1" max="30" class="input" [(ngModel)]="cfg.matching.batch_size"></div>
              </div>
              <button class="btn btn-primary" (click)="saveSearch('Filters saved')" [disabled]="busy()">Save filters</button>
            </section>
          }

          @case ('finish') {
            <section class="card space-y-4">
              <h2>Ready?</h2>
              <ul class="space-y-2 text-sm">
                @for (c of checklist(); track c.label) {
                  <li class="flex items-center gap-2">
                    <span [class]="c.ok ? 'text-emerald-600' : 'text-rose-600'">{{ c.ok ? '✓' : '✗' }}</span>{{ c.label }}
                  </li>
                }
              </ul>
              <button class="btn btn-primary" (click)="startRun()" [disabled]="busy() || !allReady()">Find jobs now</button>
              <p class="hint">Finds jobs, filters and ranks them, then asks your AI to score the best. Nothing is applied to yet.</p>
            </section>
          }
        }
      </div>
    }
  `,
})
export class SetupPage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly lines = lines;
  protected readonly unlines = unlines;
  protected readonly step = signal<Step>('profile');
  protected readonly busy = signal(false);
  protected readonly message = signal<{ ok: boolean; text: string } | null>(null);
  protected readonly segments = signal<Segment[]>([]);
  protected readonly status = signal<Status | null>(null);
  protected readonly available = signal<Partial<Record<Provider, boolean>>>({});
  protected profile: Profile | null = null;
  protected cfg: SearchConfig | null = null;

  protected readonly steps: { id: Step; label: string }[] = [
    { id: 'profile', label: 'Profile & CV' },
    { id: 'ai', label: 'AI' },
    { id: 'search', label: 'Search' },
    { id: 'filters', label: 'Filters' },
    { id: 'finish', label: 'Finish' },
  ];
  protected readonly providers: { id: Provider; label: string; hint: string }[] = [
    { id: 'codex_cli', label: 'ChatGPT plan (Codex CLI)', hint: 'Uses your ChatGPT subscription through the codex command.' },
    { id: 'claude_cli', label: 'Claude plan (Claude Code CLI)', hint: 'Uses your Claude subscription through the claude command.' },
    { id: 'litellm', label: 'API key or local model', hint: 'OpenAI, Anthropic, Gemini… or Ollama / LM Studio on this computer.' },
  ];
  protected readonly jobspySites = ['linkedin', 'indeed', 'glassdoor', 'google', 'zip_recruiter'];
  protected readonly regionalSites = ['wuzzuf', 'bayt'];
  protected readonly seniorities = ['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'executive'];

  async ngOnInit(): Promise<void> {
    const [profile, cfg, status, ai] = await Promise.all([
      this.api.get<Profile>('/profile'),
      this.api.get<SearchConfig>('/search'),
      this.api.get<Status>('/status'),
      this.api.get<{ provider: Provider; available: Record<Provider, boolean> }>('/ai'),
    ]);
    cfg.ai.provider ??= ai.provider;
    this.profile = profile;
    this.cfg = cfg;
    this.status.set(status);
    this.available.set(ai.available);
    if (profile.cv_name) this.api.get<Segment[]>('/profile/cv/segments').then((s) => this.segments.set(s)).catch(() => {});
  }

  val(event: Event): string {
    return (event.target as HTMLTextAreaElement).value;
  }

  toggle(list: string[], item: string): void {
    const i = list.indexOf(item);
    if (i >= 0) list.splice(i, 1);
    else list.push(item);
  }

  done(step: Step): boolean {
    const s = this.status();
    if (!s) return false;
    return { profile: s.profile_ready && s.cv_ready, ai: s.ai_ready, search: s.search_ready, filters: s.search_ready, finish: false }[step];
  }

  checklist(): { label: string; ok: boolean }[] {
    const s = this.status();
    return [
      { label: 'Profile (name and email)', ok: !!s?.profile_ready },
      { label: 'CV uploaded', ok: !!s?.cv_ready },
      { label: 'AI provider chosen', ok: !!s?.ai_ready },
      { label: 'At least one search or company', ok: !!s?.search_ready },
      { label: 'LibreOffice installed (needed later for tailoring)', ok: !!s?.libreoffice },
    ];
  }

  allReady(): boolean {
    const s = this.status();
    return !!s && s.profile_ready && s.cv_ready && s.ai_ready && s.search_ready;
  }

  private async run(action: () => Promise<string>): Promise<void> {
    this.busy.set(true);
    this.message.set(null);
    try {
      this.message.set({ ok: true, text: await action() });
      this.status.set(await this.api.get<Status>('/status'));
    } catch (e) {
      this.message.set({ ok: false, text: (e as Error).message });
    } finally {
      this.busy.set(false);
    }
  }

  saveProfile(): Promise<void> {
    return this.run(async () => {
      this.profile = { ...(await this.api.put<Profile>('/profile', this.profile)) };
      return 'Profile saved';
    });
  }

  upload(event: Event): Promise<void> {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return Promise.resolve();
    return this.run(async () => {
      const r = await this.api.upload<{ cv_name: string; segments: Segment[] }>('/profile/cv', file);
      this.profile!.cv_name = r.cv_name;
      this.segments.set(r.segments);
      return `CV uploaded: ${r.segments.length} text parts found`;
    });
  }

  saveSearch(ok: string): Promise<void> {
    return this.run(async () => {
      this.cfg = await this.api.put<SearchConfig>('/search', this.cfg);
      return ok;
    });
  }

  testAI(): Promise<void> {
    return this.run(async () => {
      const r = await this.api.post<{ ok: boolean; message: string }>('/ai/check', this.cfg!.ai);
      if (!r.ok) throw new Error(`Connection failed: ${r.message}`);
      return `Connected: ${r.message}`;
    });
  }

  startRun(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/runs', { stages: ['discover', 'enrich', 'rank', 'score'] });
      await this.router.navigate(['/live']);
      return 'Run started';
    });
  }
}
