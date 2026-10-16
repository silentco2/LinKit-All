import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { ApplicationAnswers, EmailState, expandQueries, lines, Profile, Provider, SearchConfig, Segment, Status, unlines, WorkMode } from '../types';

type LocalServer = 'ollama' | 'lmstudio';
type Step = 'profile' | 'ai' | 'search' | 'filters' | 'answers' | 'apply' | 'vault' | 'email' | 'finish';
type EeoKey = 'eeo_gender' | 'eeo_race' | 'eeo_hispanic' | 'eeo_veteran' | 'eeo_disability';

// Labels in the arrays below are i18n keys; the template runs them through the `t` pipe.
@Component({
  selector: 'app-setup',
  imports: [FormsModule, TPipe],
  template: `
    <h1>{{ 'setup.title' | t }}</h1>
    <p class="mt-1 text-sm text-slate-500">{{ 'setup.subtitle' | t }}</p>

    <ol class="mt-6 flex flex-wrap gap-2" [attr.aria-label]="'setup.stepsLabel' | t">
      @for (s of steps; track s.id; let i = $index) {
        <li>
          <button type="button" class="btn" [class.btn-primary]="step() === s.id" (click)="step.set(s.id)"
                  [attr.aria-current]="step() === s.id ? 'step' : null">
            {{ i + 1 }}. {{ s.label | t }} @if (done(s.id)) { <span [attr.aria-label]="'setup.done' | t">✓</span> }
          </button>
        </li>
      }
    </ol>

    @if (message(); as m) {
      <div class="alert mt-4" dir="auto" [class.alert-ok]="m.ok" [class.alert-error]="!m.ok" role="status">{{ m.text }}</div>
    }

    @if (profile && cfg) {
      <div class="mt-6 max-w-3xl space-y-6">
        @switch (step()) {
          @case ('profile') {
            <section class="card space-y-4">
              <h2>{{ 'setup.profile.title' | t }}</h2>
              <div class="grid gap-4 sm:grid-cols-2">
                <div><label class="label" for="name">{{ 'setup.profile.fullName' | t }}</label><input id="name" class="input" [(ngModel)]="profile.full_name" autocomplete="name"></div>
                <div><label class="label" for="email">{{ 'setup.profile.email' | t }}</label><input id="email" type="email" dir="ltr" class="input" [(ngModel)]="profile.email" autocomplete="email"></div>
                <div><label class="label" for="phone">{{ 'setup.profile.phone' | t }}</label><input id="phone" dir="ltr" class="input" [(ngModel)]="profile.phone" autocomplete="tel"></div>
                <div><label class="label" for="loc">{{ 'setup.profile.location' | t }}</label><input id="loc" class="input" [(ngModel)]="profile.location" placeholder="Cairo, Egypt"></div>
              </div>
              <div>
                <label class="label" for="skills">{{ 'setup.profile.skills' | t }}</label>
                <textarea id="skills" class="input h-28" [value]="unlines(profile.skills)" (change)="profile.skills = lines(val($event))"></textarea>
                <p class="hint">{{ 'setup.profile.skillsHint' | t }}</p>
              </div>
              <div>
                <label class="label" for="facts">{{ 'setup.profile.facts' | t }}</label>
                <textarea id="facts" class="input h-28" [value]="unlines(profile.locked_facts)" (change)="profile.locked_facts = lines(val($event))"
                          placeholder="Acme Corp&#10;Senior Software Engineer&#10;B.Sc. Computer Science"></textarea>
                <p class="hint">{{ 'setup.profile.factsHint' | t }}</p>
              </div>
              <button class="btn btn-primary" (click)="saveProfile()" [disabled]="busy()">{{ 'setup.profile.save' | t }}</button>
            </section>

            <section class="card space-y-4">
              <h2>{{ 'setup.cv.title' | t }}</h2>
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.cv.intro' | t }}</p>
              <div class="flex flex-wrap items-center gap-3">
                <label class="btn cursor-pointer">
                  {{ (profile.cv_name ? 'setup.cv.replace' : 'setup.cv.upload') | t }}
                  <input type="file" accept=".docx,.odt,.pdf,.tex,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.oasis.opendocument.text,application/pdf,application/x-tex,text/x-tex" class="sr-only" (change)="upload($event)">
                </label>
                @if (profile.cv_name) {
                  <bdi class="text-sm">{{ profile.cv_name }}</bdi>
                  @if (profile.cv_renderer_ok ?? status()?.libreoffice) {
                    <a class="btn" href="/api/profile/cv/pdf" target="_blank" rel="noopener">{{ 'setup.cv.preview' | t }}</a>
                  }
                }
              </div>
              @if (profile.cv_name && profile.cv_approved === false) {
                <div class="alert alert-error" role="alert">
                  <p><strong>{{ 'setup.cv.checkTitle' | t }}</strong> {{ 'setup.cv.checkBody' | t }}</p>
                  <button class="btn btn-primary mt-3" (click)="approveCv()" [disabled]="busy()">{{ 'setup.cv.approve' | t }}</button>
                </div>
              }
              @if (profile.cv_source_format === 'tex') {
                @if (profile.cv_renderer_ok === false) {
                  <div class="alert alert-error">{{ 'setup.cv.tectonicA' | t }}<a href="https://tectonic-typesetting.github.io" target="_blank" rel="noopener">Tectonic</a>{{ 'setup.cv.tectonicB' | t }}<code dir="ltr">linkit doctor</code>{{ 'setup.cv.tectonicC' | t }}</div>
                }
              } @else if (status() && !status()!.libreoffice) {
                <div class="alert alert-error">{{ 'setup.cv.noLibreA' | t }}<code dir="ltr">linkit doctor</code>{{ 'setup.cv.noLibreB' | t }}</div>
              }
              @if (segments().length) {
                <details class="text-sm">
                  <summary class="cursor-pointer font-medium">{{ 'setup.cv.reads' | t: { n: segments().length } }}</summary>
                  <ol class="mt-2 max-h-72 space-y-1 overflow-auto rounded-lg bg-slate-50 p-3 dark:bg-slate-950">
                    @for (s of segments(); track s.id) { <li class="whitespace-pre-wrap" dir="auto"><span class="text-slate-400">{{ s.id }}</span> {{ s.text }}</li> }
                  </ol>
                </details>
              }
            </section>
          }

          @case ('ai') {
            <section class="card space-y-4">
              <h2>{{ 'setup.ai.title' | t }}</h2>
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.ai.intro' | t }}</p>
              <fieldset class="space-y-2">
                <legend class="label">{{ 'setup.ai.provider' | t }}</legend>
                @for (p of providers; track p.id) {
                  <label class="flex items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                         [class.border-brand-500]="mode() === p.id">
                    <input type="radio" name="provider" class="mt-1" [value]="p.id" [ngModel]="mode()" (ngModelChange)="setMode($event)">
                    <span>
                      <span class="font-medium">{{ p.label | t }}</span>
                      @if (p.id !== 'local' && available()[p.id] === false) { <span class="badge tier-low ms-2">{{ 'setup.ai.notInstalled' | t }}</span> }
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
                        @if (local()![s.id].models.length === 0) {
                          <p class="hint">{{ 'setup.ai.noModels' | t }}</p>
                        }
                        <div class="mt-2 flex flex-wrap gap-2">
                          @for (m of local()![s.id].models; track m) {
                            <button type="button" class="btn" dir="ltr" [class.btn-primary]="cfg.ai.model === s.prefix + m" (click)="pickLocal(s.id, m)">{{ m }}</button>
                          }
                        </div>
                      }
                    </div>
                  }
                  <button type="button" class="btn" (click)="scanLocal()">{{ 'setup.ai.scan' | t }}</button>
                  <div>
                    <label class="label" for="api-base">{{ 'setup.ai.base' | t }}</label>
                    <input id="api-base" dir="ltr" class="input" [(ngModel)]="cfg.ai.api_base" placeholder="http://127.0.0.1:1234/v1">
                  </div>
                  <div>
                    <label class="label" for="model">{{ 'setup.ai.model' | t }}</label>
                    <input id="model" dir="ltr" class="input" [(ngModel)]="cfg.ai.model" [placeholder]="'setup.ai.modelPhLocal' | t">
                  </div>
                </div>
                <p class="hint">{{ 'setup.ai.localHint' | t }}</p>
              } @else {
                <div>
                  <label class="label" for="model">{{ 'setup.ai.modelOpt' | t }}</label>
                  <input id="model" dir="ltr" class="input" [(ngModel)]="cfg.ai.model" [placeholder]="(cfg.ai.provider === 'litellm' ? 'setup.ai.modelPhApi' : 'setup.ai.modelPhCli') | t">
                </div>
                @if (cfg.ai.provider !== 'litellm') {
                  <p class="hint">{{ 'setup.ai.cliHint' | t }}</p>
                } @else {
                  <p class="hint">{{ 'setup.ai.keyHintA' | t }}<code dir="ltr">LINKIT_API_KEY</code>{{ 'setup.ai.keyHintB' | t }}</p>
                }
              }
              <div class="flex gap-3">
                <button class="btn" (click)="testAI()" [disabled]="busy() || !cfg.ai.provider">{{ 'setup.ai.test' | t }}</button>
                <button class="btn btn-primary" (click)="saveSearch('setup.ai.saved')" [disabled]="busy() || !cfg.ai.provider">{{ 'setup.ai.save' | t }}</button>
              </div>
            </section>
          }

          @case ('search') {
            <section class="card space-y-4">
              <h2>{{ 'setup.search.title' | t }}</h2>
              <div class="grid gap-4 sm:grid-cols-2">
                <div>
                  <label class="label" for="queries">{{ 'setup.search.queries' | t }}</label>
                  <textarea id="queries" class="input h-28" [value]="unlines(cfg.search.queries)" (change)="setQueries($event)" placeholder="python developer&#10;backend engineer"></textarea>
                  <p class="hint">{{ 'setup.search.queriesHint' | t }}</p>
                </div>
                <div>
                  <label class="label" for="locations">{{ 'setup.search.locations' | t }}</label>
                  <textarea id="locations" class="input h-28" [value]="unlines(cfg.search.locations)" (change)="cfg.search.locations = lines(val($event))" placeholder="Cairo, Egypt&#10;Remote"></textarea>
                  <p class="hint">{{ 'setup.search.locationsHint' | t }}</p>
                </div>
                <div><label class="label" for="days">{{ 'setup.search.days' | t }}</label><input id="days" type="number" min="1" class="input" [(ngModel)]="cfg.search.posted_within_days"></div>
                <div><label class="label" for="max">{{ 'setup.search.max' | t }}</label><input id="max" type="number" min="1" max="1000" class="input" [(ngModel)]="cfg.search.max_results_per_query"></div>
              </div>
            </section>
            <section class="card space-y-4">
              <h2>{{ 'setup.search.where' | t }}</h2>
              <fieldset>
                <legend class="label">{{ 'setup.search.sites' | t }}</legend>
                <div class="flex flex-wrap gap-4">
                  @for (site of jobspySites; track site) {
                    <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.sources.jobspy.includes(site)" (change)="toggle(cfg.sources.jobspy, site)"><bdi>{{ site }}</bdi></label>
                  }
                  @for (site of regionalSites; track site.id) {
                    <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.sources.regional.includes(site.id)" (change)="toggle(cfg.sources.regional, site.id)"><bdi>{{ site.label }}</bdi></label>
                  }
                </div>
                <p class="hint">{{ 'setup.search.wuzzufHint' | t }}</p>
              </fieldset>
              <div class="max-w-xs">
                <label class="label" for="country">{{ 'setup.search.country' | t }}</label>
                <input id="country" class="input" [(ngModel)]="cfg.sources.jobspy_country" placeholder="egypt">
              </div>
              <div>
                <label class="label" for="companies">{{ 'setup.search.companies' | t }}</label>
                <textarea id="companies" dir="ltr" class="input h-32 font-mono text-xs" [value]="unlines(cfg.sources.companies)" (change)="cfg.sources.companies = lines(val($event))"
                          placeholder="https://boards.greenhouse.io/stripe&#10;https://jobs.lever.co/palantir&#10;https://www.notion.com/careers"></textarea>
                <p class="hint">{{ 'setup.search.companiesHint' | t }}</p>
              </div>
              <button class="btn btn-primary" (click)="saveSearch('setup.search.saved')" [disabled]="busy()">{{ 'setup.search.save' | t }}</button>
            </section>
          }

          @case ('filters') {
            <section class="card space-y-4">
              <h2>{{ 'setup.filters.title' | t }}</h2>
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.filters.intro' | t }}</p>
              <div class="grid gap-4 sm:grid-cols-2">
                <div>
                  <label class="label" for="inc">{{ 'setup.filters.include' | t }}</label>
                  <textarea id="inc" class="input h-24" [value]="unlines(cfg.filters.title_include)" (change)="cfg.filters.title_include = lines(val($event))" placeholder="engineer&#10;developer"></textarea>
                </div>
                <div>
                  <label class="label" for="exc">{{ 'setup.filters.exclude' | t }}</label>
                  <textarea id="exc" class="input h-24" [value]="unlines(cfg.filters.title_exclude)" (change)="cfg.filters.title_exclude = lines(val($event))" placeholder="intern&#10;director"></textarea>
                </div>
                <div>
                  <label class="label" for="floc">{{ 'setup.filters.location' | t }}</label>
                  <textarea id="floc" class="input h-24" [value]="unlines(cfg.filters.locations)" (change)="cfg.filters.locations = lines(val($event))" placeholder="egypt&#10;remote"></textarea>
                </div>
                <div>
                  <label class="label" for="black">{{ 'setup.filters.blacklist' | t }}</label>
                  <textarea id="black" class="input h-24" [value]="unlines(cfg.filters.company_blacklist)" (change)="cfg.filters.company_blacklist = lines(val($event))"></textarea>
                </div>
                <fieldset>
                  <legend class="label">{{ 'setup.filters.mode' | t }}</legend>
                  <div class="flex flex-wrap gap-4">
                    @for (m of workModes; track m) {
                      <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.filters.work_modes.includes(m)" (change)="toggleMode(m, $event)">{{ 'setup.filters.mode.' + m | t }}</label>
                    }
                  </div>
                  <p class="hint">{{ 'setup.filters.modeHint' | t }}</p>
                </fieldset>
                <div>
                  <label class="label" for="salary">{{ 'setup.filters.salary' | t }}</label>
                  <div class="flex gap-2">
                    <input id="salary" type="number" min="0" class="input" [(ngModel)]="cfg.filters.salary_floor_monthly">
                    <select class="input w-28" dir="ltr" [attr.aria-label]="'setup.filters.currency' | t" [(ngModel)]="cfg.filters.salary_currency">
                      @for (c of currencies; track c) { <option [value]="c">{{ c }}</option> }
                    </select>
                  </div>
                  <p class="hint">{{ 'setup.filters.salaryHint' | t }}</p>
                </div>
              </div>
              <fieldset>
                <legend class="label">{{ 'setup.filters.seniority' | t }}</legend>
                <div class="flex flex-wrap gap-4">
                  @for (level of seniorities; track level) {
                    <label class="flex items-center gap-2 text-sm"><input type="checkbox" [checked]="cfg.filters.seniority.includes(level)" (change)="toggle(cfg.filters.seniority, level)">{{ 'setup.seniority.' + level | t }}</label>
                  }
                </div>
              </fieldset>
              <label class="flex items-center gap-2 text-sm"><input type="checkbox" [(ngModel)]="cfg.filters.one_per_company">{{ 'setup.filters.onePer' | t }}</label>
            </section>
            <section class="card space-y-4">
              <h2>{{ 'setup.scoring.title' | t }}</h2>
              <div class="grid gap-4 sm:grid-cols-2">
                <div><label class="label" for="high">{{ 'setup.scoring.high' | t }}</label><input id="high" type="number" min="1" max="10" class="input" [(ngModel)]="cfg.matching.tier_high"><p class="hint">{{ 'setup.scoring.highHint' | t: { from: cfg.matching.tier_high } }}</p></div>
                <div><label class="label" for="mid">{{ 'setup.scoring.mid' | t }}</label><input id="mid" type="number" min="1" max="10" class="input" [(ngModel)]="cfg.matching.tier_mid"><p class="hint">{{ 'setup.scoring.midHint' | t: { from: cfg.matching.tier_mid, to: cfg.matching.tier_high - 1 } }}</p></div>
                <div><label class="label" for="aimax">{{ 'setup.scoring.aimax' | t }}</label><input id="aimax" type="number" min="0" class="input" [(ngModel)]="cfg.matching.ai_max_jobs"><p class="hint">{{ 'setup.scoring.aimaxHint' | t }}</p></div>
                <div><label class="label" for="batch">{{ 'setup.scoring.batch' | t }}</label><input id="batch" type="number" min="1" max="30" class="input" [(ngModel)]="cfg.matching.batch_size"></div>
              </div>
              <div>
                <label class="flex items-center gap-2 text-sm font-medium"><input type="checkbox" role="switch" [(ngModel)]="cfg.matching.auto_apply_low">{{ 'setup.scoring.low' | t }}</label>
                @if (cfg.matching.auto_apply_low) { <div class="alert alert-error mt-2" role="note">{{ 'setup.scoring.lowWarn' | t }}</div> }
              </div>
              <button class="btn btn-primary" (click)="saveSearch('setup.filters.saved')" [disabled]="busy()">{{ 'setup.filters.save' | t }}</button>
            </section>
          }

          @case ('answers') {
            @if (ans) {
              <section class="card space-y-4">
                <h2>{{ 'setup.answers.title' | t }}</h2>
                <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.answers.intro' | t }}</p>
                <h3 class="text-sm font-semibold">{{ 'setup.answers.basics' | t }}</h3>
                <div class="grid gap-4 sm:grid-cols-2">
                  <div><label class="label" for="a-first">{{ 'setup.answers.first' | t }}</label><input id="a-first" class="input" [(ngModel)]="ans.first_name"><p class="hint">{{ 'setup.answers.firstHint' | t }}</p></div>
                  <div><label class="label" for="a-last">{{ 'setup.answers.last' | t }}</label><input id="a-last" class="input" [(ngModel)]="ans.last_name"></div>
                  <div><label class="label" for="a-city">{{ 'setup.answers.city' | t }}</label><input id="a-city" class="input" [(ngModel)]="ans.city"></div>
                  <div><label class="label" for="a-country">{{ 'setup.answers.country' | t }}</label><input id="a-country" class="input" [(ngModel)]="ans.country"></div>
                  <div><label class="label" for="a-company">{{ 'setup.answers.company' | t }}</label><input id="a-company" class="input" [(ngModel)]="ans.current_company"></div>
                  <div><label class="label" for="a-title">{{ 'setup.answers.jobTitle' | t }}</label><input id="a-title" class="input" [(ngModel)]="ans.current_title"></div>
                  <div><label class="label" for="a-linkedin">{{ 'setup.answers.linkedin' | t }}</label><input id="a-linkedin" type="url" dir="ltr" class="input" [(ngModel)]="ans.linkedin"></div>
                  <div><label class="label" for="a-github">{{ 'setup.answers.github' | t }}</label><input id="a-github" type="url" dir="ltr" class="input" [(ngModel)]="ans.github"></div>
                  <div><label class="label" for="a-portfolio">{{ 'setup.answers.portfolio' | t }}</label><input id="a-portfolio" type="url" dir="ltr" class="input" [(ngModel)]="ans.portfolio"></div>
                  <div><label class="label" for="a-years">{{ 'setup.answers.years' | t }}</label><input id="a-years" type="number" min="0" step="1" class="input" [(ngModel)]="ans.years_experience"></div>
                  <div><label class="label" for="a-notice">{{ 'setup.answers.notice' | t }}</label><input id="a-notice" class="input" [(ngModel)]="ans.notice_period" [placeholder]="'setup.answers.noticePh' | t"></div>
                  <div><label class="label" for="a-heard">{{ 'setup.answers.heard' | t }}</label><input id="a-heard" class="input" [(ngModel)]="ans.heard_about" [placeholder]="'setup.answers.heardPh' | t"></div>
                  <div>
                    <label class="label" for="a-reloc">{{ 'setup.answers.reloc' | t }}</label>
                    <select id="a-reloc" class="input" [(ngModel)]="ans.willing_to_relocate">
                      <option [ngValue]="null">{{ 'setup.askMe' | t }}</option><option [ngValue]="true">{{ 'common.yes' | t }}</option><option [ngValue]="false">{{ 'common.no' | t }}</option>
                    </select>
                  </div>
                </div>

                <h3 class="pt-2 text-sm font-semibold">{{ 'setup.answers.sensitive' | t }}</h3>
                <p class="hint">{{ 'setup.answers.sensitiveHint' | t }}</p>
                <div class="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label class="label" for="a-auth">{{ 'setup.answers.auth' | t }}</label>
                    <textarea id="a-auth" class="input h-24" [value]="unlines(ans.authorized_countries)" (change)="ans.authorized_countries = lines(val($event))" placeholder="Egypt&#10;United Arab Emirates"></textarea>
                    <p class="hint">{{ 'setup.answers.authHint' | t }}</p>
                  </div>
                  <div>
                    <label class="label" for="a-spons">{{ 'setup.answers.sponsor' | t }}</label>
                    <select id="a-spons" class="input" [(ngModel)]="ans.needs_sponsorship">
                      <option [ngValue]="null">{{ 'setup.askMe' | t }}</option><option [ngValue]="true">{{ 'common.yes' | t }}</option><option [ngValue]="false">{{ 'common.no' | t }}</option>
                    </select>
                  </div>
                  <div><label class="label" for="a-sal">{{ 'setup.answers.salary' | t }}</label><input id="a-sal" class="input" [(ngModel)]="ans.salary_expectation" placeholder="30000"><p class="hint">{{ 'setup.answers.salaryHint' | t }}</p></div>
                  <div><label class="label" for="a-cur">{{ 'setup.answers.currency' | t }}</label><input id="a-cur" dir="ltr" class="input" [(ngModel)]="ans.salary_currency" placeholder="EGP"></div>
                </div>

                <h3 class="pt-2 text-sm font-semibold">{{ 'setup.answers.demo' | t }}</h3>
                <p class="hint">{{ 'setup.answers.demoHint' | t: { ask: ('setup.askMe' | t) } }}</p>
                <div class="grid gap-4 sm:grid-cols-2">
                  @for (f of eeoFields; track f.key) {
                    <div>
                      <label class="label" [for]="'a-' + f.key">{{ f.label | t }}</label>
                      <select [id]="'a-' + f.key" class="input" [(ngModel)]="ans[f.key]">
                        <option [ngValue]="null">{{ 'setup.askMe' | t }}</option>
                        @for (o of f.options; track o[0]) { <option [value]="o[0]">{{ o[1] | t }}</option> }
                        <option value="decline">{{ 'setup.eeo.decline' | t }}</option>
                      </select>
                    </div>
                  }
                </div>

                <h3 class="pt-2 text-sm font-semibold">{{ 'setup.answers.ack' | t }}</h3>
                <div class="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label class="label" for="a-priv">{{ 'setup.answers.privacy' | t }}</label>
                    <select id="a-priv" class="input" [(ngModel)]="ans.acknowledge_privacy">
                      <option [ngValue]="null">{{ 'setup.askMe' | t }}</option><option [ngValue]="true">{{ 'setup.answers.accept' | t }}</option>
                    </select>
                    <p class="hint">{{ 'setup.answers.privacyHint' | t }}</p>
                  </div>
                  <div>
                    <label class="label" for="a-legal">{{ 'setup.answers.legal' | t }}</label>
                    <select id="a-legal" class="input" [(ngModel)]="ans.acknowledge_legal">
                      <option [ngValue]="null">{{ 'setup.askMe' | t }}</option><option [ngValue]="true">{{ 'setup.answers.accept' | t }}</option>
                    </select>
                    <p class="hint">{{ 'setup.answers.legalHint' | t }}</p>
                  </div>
                </div>
                <button class="btn btn-primary" (click)="saveAnswers()" [disabled]="busy()">{{ 'setup.answers.save' | t }}</button>
              </section>
            }
          }

          @case ('apply') {
            <section class="card space-y-4">
              <h2>{{ 'setup.apply.title' | t }}</h2>
              <div class="alert alert-info">{{ 'setup.apply.dryInfo' | t }}</div>
              <label class="flex items-start gap-3 text-sm">
                <input type="checkbox" class="mt-1" [ngModel]="cfg.apply.live" (ngModelChange)="setLive($event)">
                <span><span class="font-medium">{{ 'setup.apply.live' | t }}</span>
                  <span class="block text-xs text-slate-500">{{ 'setup.apply.liveOff' | t }}</span></span>
              </label>
              @if (cfg.apply.live) {
                <div class="alert alert-error" role="alert"><strong>{{ 'setup.apply.liveWarnTitle' | t }}</strong> {{ 'setup.apply.liveWarnBody' | t }}</div>
              }
              <label class="flex items-start gap-3 text-sm" [class.opacity-50]="!cfg.apply.live">
                <input type="checkbox" class="mt-1" [(ngModel)]="cfg.apply.submit_without_asking" [disabled]="!cfg.apply.live">
                <span><span class="font-medium">{{ 'setup.apply.noAsk' | t }}</span>
                  <span class="block text-xs text-slate-500">{{ 'setup.apply.noAskHint' | t }}</span></span>
              </label>
              @if (cfg.apply.live && cfg.apply.submit_without_asking) {
                <div class="alert alert-error" role="alert"><strong>{{ 'setup.apply.noConfirmTitle' | t }}</strong> {{ 'setup.apply.noConfirmBody' | t }}</div>
              }
              <div class="grid gap-4 sm:grid-cols-2">
                <div><label class="label" for="p-run">{{ 'setup.apply.maxRun' | t }}</label><input id="p-run" type="number" min="1" max="100" class="input" [(ngModel)]="cfg.apply.max_per_run"></div>
                <div><label class="label" for="p-day">{{ 'setup.apply.daily' | t }}</label><input id="p-day" type="number" min="1" max="200" class="input" [(ngModel)]="cfg.apply.daily_cap_per_site"><p class="hint">{{ 'setup.apply.dailyHint' | t }}</p></div>
                <div><label class="label" for="p-min">{{ 'setup.apply.minPause' | t }}</label><input id="p-min" type="number" min="0" class="input" [(ngModel)]="cfg.apply.min_pause_s"></div>
                <div><label class="label" for="p-max">{{ 'setup.apply.maxPause' | t }}</label><input id="p-max" type="number" min="0" class="input" [(ngModel)]="cfg.apply.max_pause_s"><p class="hint">{{ 'setup.apply.pauseHint' | t }}</p></div>
                <div><label class="label" for="p-par">{{ 'setup.apply.parallel' | t }}</label><input id="p-par" type="number" min="1" max="3" class="input" [(ngModel)]="cfg.apply.parallel_sites"><p class="hint">{{ 'setup.apply.parallelHint' | t }}</p></div>
              </div>
              @if (pauseInvalid()) {
                <p class="text-sm text-rose-600" role="alert">{{ 'setup.apply.pauseInvalid' | t }}</p>
              }
              <label class="flex items-center gap-2 text-sm"><input type="checkbox" [(ngModel)]="cfg.apply.headless">{{ 'setup.apply.headless' | t }}</label>
              <label class="flex items-start gap-3 text-sm">
                <input type="checkbox" class="mt-1" [(ngModel)]="cfg.apply.generic_agent">
                <span><span class="font-medium">{{ 'setup.apply.agent' | t }}</span>
                  <span class="block text-xs text-slate-500">{{ 'setup.apply.agentHint' | t }}</span></span>
              </label>
              <button class="btn btn-primary" (click)="saveSearch('setup.apply.saved')" [disabled]="busy() || pauseInvalid()">{{ 'setup.apply.save' | t }}</button>
            </section>
          }

          @case ('vault') {
            <section class="card space-y-4">
              <h2>{{ 'setup.vault.title' | t }}</h2>
              <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.vault.intro' | t }}</p>
              <div class="alert alert-info"><strong>{{ 'setup.vault.warnTitle' | t }}</strong> {{ 'setup.vault.warnBody' | t }}</div>
              @if (status()?.vault?.unlocked) {
                <div class="alert alert-ok" role="status">{{ 'setup.vault.unlocked' | t }}</div>
              } @else {
                <form class="space-y-4" (ngSubmit)="vaultSubmit()">
                  @if (!status()?.vault?.initialized) {
                    <div class="grid gap-4 sm:grid-cols-2">
                      <div><label class="label" for="v-pass">{{ 'setup.vault.pass' | t }}</label><input id="v-pass" type="password" class="input" name="vpass" [(ngModel)]="vpass" autocomplete="new-password" minlength="8"><p class="hint">{{ 'setup.vault.passHint' | t }}</p></div>
                      <div><label class="label" for="v-conf">{{ 'setup.vault.repeat' | t }}</label><input id="v-conf" type="password" class="input" name="vconf" [(ngModel)]="vconfirm" autocomplete="new-password"></div>
                    </div>
                    @if (vconfirm && vpass !== vconfirm) { <p class="text-sm text-rose-600" role="alert">{{ 'setup.vault.mismatch' | t }}</p> }
                  } @else {
                    <div class="max-w-sm"><label class="label" for="v-pass">{{ 'setup.vault.pass' | t }}</label><input id="v-pass" type="password" class="input" name="vpass" [(ngModel)]="vpass" autocomplete="current-password"></div>
                  }
                  <label class="flex items-start gap-3 text-sm">
                    <input type="checkbox" class="mt-1" name="vremember" [(ngModel)]="vremember">
                    <span><span class="font-medium">{{ 'setup.vault.remember' | t }}</span>
                      <span class="block text-xs text-slate-500">{{ 'setup.vault.rememberHint' | t }}</span></span>
                  </label>
                  <button type="submit" class="btn btn-primary" [disabled]="busy() || vpass.length < 8 || (!status()?.vault?.initialized && vpass !== vconfirm)">
                    {{ (status()?.vault?.initialized ? 'setup.vault.unlock' : 'setup.vault.create') | t }}
                  </button>
                </form>
              }
            </section>
          }

          @case ('email') {
            <section class="card space-y-4">
              <h2>{{ 'setup.email.title' | t }} <span class="text-sm font-normal text-slate-500">({{ 'common.optional' | t }})</span></h2>
              <p class="text-sm text-slate-600 dark:text-slate-300">{{ 'setup.email.intro' | t }}</p>
              @if (!status()?.vault?.unlocked) {
                <div class="alert alert-info" role="status">{{ 'setup.email.needVault' | t }}</div>
              }
              @if (email()?.connected) {
                <div class="alert alert-ok" role="status">{{ 'setup.email.connectedAs' | t }} <bdi>{{ email()!.imap_user }}</bdi>.</div>
              }
              <form class="space-y-4" (ngSubmit)="emailSave()">
                <div class="grid gap-4 sm:grid-cols-2">
                  <div><label class="label" for="e-user">{{ 'setup.email.address' | t }}</label><input id="e-user" type="email" dir="ltr" class="input" name="euser" [(ngModel)]="eUser" autocomplete="email"></div>
                  <div><label class="label" for="e-pass">{{ 'setup.email.appPass' | t }}</label><input id="e-pass" type="password" dir="ltr" class="input" name="epass" [(ngModel)]="ePass" autocomplete="off" placeholder="abcd efgh ijkl mnop"></div>
                </div>
                <p class="hint">{{ 'setup.email.hint' | t }}</p>
                <details class="text-sm">
                  <summary class="cursor-pointer font-medium">{{ 'setup.email.advanced' | t }}</summary>
                  <div class="mt-2 max-w-sm"><label class="label" for="e-host">{{ 'setup.email.imap' | t }}</label><input id="e-host" dir="ltr" class="input" name="ehost" [(ngModel)]="eHost" autocomplete="off"></div>
                </details>
                <div class="flex flex-wrap gap-3">
                  <button type="submit" class="btn btn-primary" [disabled]="busy() || !status()?.vault?.unlocked || !ePass.trim()">{{ 'setup.email.save' | t }}</button>
                  @if (email()?.connected) {
                    <button type="button" class="btn" (click)="emailTest()" [disabled]="busy()">{{ 'setup.email.testAgain' | t }}</button>
                    <button type="button" class="btn" (click)="emailDisconnect()" [disabled]="busy()">{{ 'setup.email.disconnect' | t }}</button>
                  }
                </div>
              </form>
            </section>
          }

          @case ('finish') {
            <section class="card space-y-4">
              <h2>{{ 'setup.finish.title' | t }}</h2>
              <ul class="space-y-2 text-sm">
                @for (c of checklist(); track c.label) {
                  <li class="flex items-center gap-2">
                    <span [class]="c.ok ? 'text-emerald-600' : 'text-rose-600'">{{ c.ok ? '✓' : '✗' }}</span>{{ c.label | t }}
                  </li>
                }
              </ul>
              <button class="btn btn-primary" (click)="startRun()" [disabled]="busy() || !allReady()">{{ 'setup.finish.go' | t }}</button>
              <p class="hint">{{ 'setup.finish.hint' | t }}</p>
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
  private readonly i18n = inject(I18n);
  protected readonly lines = lines;
  protected readonly unlines = unlines;
  protected readonly step = signal<Step>('profile');
  protected readonly busy = signal(false);
  protected readonly message = signal<{ ok: boolean; text: string } | null>(null);
  protected readonly segments = signal<Segment[]>([]);
  protected readonly status = signal<Status | null>(null);
  protected readonly email = signal<EmailState | null>(null);
  protected readonly available = signal<Partial<Record<Provider, boolean>>>({});
  protected profile: Profile | null = null;
  protected cfg: SearchConfig | null = null;
  protected ans: ApplicationAnswers | null = null;
  protected readonly eeoFields: { key: EeoKey; label: string; options: [string, string][] }[] = [
    { key: 'eeo_gender', label: 'setup.eeo.gender', options: [['male', 'setup.eeo.male'], ['female', 'setup.eeo.female'], ['non_binary', 'setup.eeo.nonBinary']] },
    {
      key: 'eeo_race',
      label: 'setup.eeo.race',
      options: [['asian', 'setup.eeo.asian'], ['black', 'setup.eeo.black'], ['hispanic', 'setup.eeo.hispanic'], ['white', 'setup.eeo.white'],
        ['middle_eastern', 'setup.eeo.middleEastern'], ['native', 'setup.eeo.native'],
        ['pacific', 'setup.eeo.pacific'], ['two_or_more', 'setup.eeo.twoOrMore']],
    },
    { key: 'eeo_hispanic', label: 'setup.eeo.hispanicQ', options: [['yes', 'common.yes'], ['no', 'common.no']] },
    { key: 'eeo_veteran', label: 'setup.eeo.veteran', options: [['not_veteran', 'setup.eeo.notVeteran'], ['veteran', 'setup.eeo.isVeteran']] },
    { key: 'eeo_disability', label: 'setup.eeo.disability', options: [['no', 'setup.eeo.noDisability'], ['yes', 'setup.eeo.yesDisability']] },
  ];

  protected readonly steps: { id: Step; label: string }[] = [
    { id: 'profile', label: 'setup.step.profile' },
    { id: 'ai', label: 'setup.step.ai' },
    { id: 'search', label: 'setup.step.search' },
    { id: 'filters', label: 'setup.step.filters' },
    { id: 'answers', label: 'setup.step.answers' },
    { id: 'apply', label: 'setup.step.apply' },
    { id: 'vault', label: 'setup.step.vault' },
    { id: 'email', label: 'setup.step.email' },
    { id: 'finish', label: 'setup.step.finish' },
  ];
  protected readonly providers: { id: Provider | 'local'; label: string; hint: string }[] = [
    { id: 'codex_cli', label: 'setup.ai.p.codex_cli', hint: 'setup.ai.p.codex_cli.hint' },
    { id: 'claude_cli', label: 'setup.ai.p.claude_cli', hint: 'setup.ai.p.claude_cli.hint' },
    { id: 'litellm', label: 'setup.ai.p.litellm', hint: 'setup.ai.p.litellm.hint' },
    { id: 'local', label: 'setup.ai.p.local', hint: 'setup.ai.p.local.hint' },
  ];
  protected readonly localServers: { id: LocalServer; label: string; prefix: string; base: string }[] = [
    { id: 'ollama', label: 'Ollama', prefix: 'ollama/', base: 'http://127.0.0.1:11434' },
    { id: 'lmstudio', label: 'LM Studio', prefix: 'openai/', base: 'http://127.0.0.1:1234/v1' },
  ];
  protected readonly local = signal<Record<LocalServer, { running: boolean; models: string[] }> | null>(null);
  protected readonly mode = signal<Provider | 'local' | null>(null);
  protected readonly jobspySites = ['linkedin', 'indeed', 'glassdoor', 'google', 'zip_recruiter'];
  protected readonly regionalSites = [
    { id: 'wuzzuf', label: 'Wuzzuf' },
    { id: 'bayt', label: 'Bayt' },
    { id: 'forasna', label: 'Forasna' },
  ];
  protected readonly workModes: WorkMode[] = ['remote', 'hybrid', 'onsite'];
  protected readonly currencies = ['EGP', 'SAR', 'AED', 'QAR', 'KWD', 'BHD', 'OMR', 'JOD', 'USD', 'EUR', 'GBP'];
  protected readonly seniorities = ['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'executive'];

  async ngOnInit(): Promise<void> {
    const [profile, cfg, status, ai, ans, email] = await Promise.all([
      this.api.get<Profile>('/profile'),
      this.api.get<SearchConfig>('/search'),
      this.api.get<Status>('/status'),
      this.api.get<{ provider: Provider; available: Record<Provider, boolean> }>('/ai'),
      this.api.get<ApplicationAnswers>('/profile/answers'),
      this.api.get<EmailState>('/email'),
    ]);
    cfg.ai.provider ??= ai.provider;
    cfg.ai.api_base ??= null;
    this.mode.set(cfg.ai.provider === 'litellm' && cfg.ai.api_base ? 'local' : cfg.ai.provider);
    if (this.mode() === 'local') void this.scanLocal();
    this.profile = profile;
    this.cfg = cfg;
    this.ans = ans;
    this.setEmail(email);
    this.status.set(status);
    this.available.set(ai.available);
    if (profile.cv_name) this.api.get<Segment[]>('/profile/cv/segments').then((s) => this.segments.set(s)).catch(() => {});
  }

  val(event: Event): string {
    return (event.target as HTMLTextAreaElement).value;
  }

  setQueries(event: Event): void {
    const box = event.target as HTMLTextAreaElement;
    this.cfg!.search.queries = expandQueries(lines(box.value));
    box.value = unlines(this.cfg!.search.queries); // show the split right away
  }

  /** The last work mode cannot be unchecked: the server needs at least one. */
  toggleMode(mode: WorkMode, event: Event): void {
    const modes = this.cfg!.filters.work_modes;
    if (modes.length === 1 && modes[0] === mode) {
      (event.target as HTMLInputElement).checked = true;
      this.message.set({ ok: false, text: this.i18n.t('setup.filters.modeLast') });
      return;
    }
    this.toggle(modes, mode);
  }

  toggle(list: string[], item: string): void {
    const i = list.indexOf(item);
    if (i >= 0) list.splice(i, 1);
    else list.push(item);
  }

  done(step: Step): boolean {
    const s = this.status();
    if (!s) return false;
    return { profile: s.profile_ready && s.cv_ready, ai: s.ai_ready, search: s.search_ready, filters: s.search_ready, answers: false, apply: false, vault: s.vault.unlocked, email: !!this.email()?.connected, finish: false }[step];
  }

  setLive(live: boolean): void {
    this.cfg!.apply.live = live;
    if (!live) this.cfg!.apply.submit_without_asking = false; // only meaningful in live mode
  }

  pauseInvalid(): boolean {
    const a = this.cfg?.apply;
    return !!a && a.min_pause_s > a.max_pause_s;
  }

  checklist(): { label: string; ok: boolean }[] {
    const s = this.status();
    return [
      { label: 'setup.finish.profile', ok: !!s?.profile_ready },
      { label: 'setup.finish.cv', ok: !!s?.cv_ready },
      { label: 'setup.finish.ai', ok: !!s?.ai_ready },
      { label: 'setup.finish.search', ok: !!s?.search_ready },
      { label: 'setup.finish.libreoffice', ok: !!s?.libreoffice },
    ];
  }

  allReady(): boolean {
    const s = this.status();
    return !!s && s.profile_ready && s.cv_ready && s.ai_ready && s.search_ready;
  }

  /** `action` returns the (already translated) text to show; it stays in the language it was produced in. */
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
      return this.i18n.t('setup.profile.saved');
    });
  }

  upload(event: Event): Promise<void> {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return Promise.resolve();
    return this.run(async () => {
      const r = await this.api.upload<{ cv_name: string; segments: Segment[]; cv_source_format: Profile['cv_source_format']; cv_approved: boolean; cv_renderer_ok: boolean }>('/profile/cv', file);
      this.profile!.cv_name = r.cv_name;
      this.profile!.cv_renderer_ok = r.cv_renderer_ok;
      this.profile!.cv_source_format = r.cv_source_format;
      this.profile!.cv_approved = r.cv_approved;
      this.segments.set(r.segments);
      this.status.set(await this.api.get<Status>('/status'));
      return this.i18n.t(r.cv_approved ? 'setup.cv.uploaded' : 'setup.cv.converted', { n: r.segments.length });
    });
  }

  approveCv(): Promise<void> {
    return this.run(async () => {
      this.profile = { ...(await this.api.post<Profile>('/profile/cv/approve', {})) };
      this.status.set(await this.api.get<Status>('/status'));
      return this.i18n.t('setup.cv.approved');
    });
  }

  /** `okKey` is the i18n key of the success message. */
  saveSearch(okKey: string): Promise<void> {
    return this.run(async () => {
      this.cfg = await this.api.put<SearchConfig>('/search', this.cfg);
      return this.i18n.t(okKey);
    });
  }

  vpass = '';
  vconfirm = '';
  vremember = true;

  vaultSubmit(): Promise<void> {
    const create = !this.status()?.vault.initialized;
    return this.run(async () => {
      const pass = this.vpass;
      if (create) await this.api.post('/vault/create', { passphrase: pass });
      await this.api.post('/vault/unlock', { passphrase: pass, remember: this.vremember });
      this.vpass = this.vconfirm = '';
      return this.i18n.t(create ? 'setup.vault.created' : 'setup.vault.unlockedMsg');
    });
  }

  eUser = '';
  eHost = 'imap.gmail.com';
  ePass = '';

  private setEmail(e: EmailState): void {
    this.email.set(e);
    this.eUser = e.imap_user;
    this.eHost = e.imap_host;
  }

  emailSave(): Promise<void> {
    return this.run(async () => {
      const e = await this.api.post<EmailState>('/email', { imap_host: this.eHost, imap_user: this.eUser, app_password: this.ePass });
      this.ePass = '';
      this.setEmail(e);
      return this.i18n.t('setup.email.connectedMsg', { user: e.imap_user });
    });
  }

  emailTest(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/email/test');
      return this.i18n.t('setup.email.works');
    });
  }

  emailDisconnect(): Promise<void> {
    return this.run(async () => {
      await this.api.delete('/email');
      this.setEmail(await this.api.get<EmailState>('/email'));
      return this.i18n.t('setup.email.disconnected');
    });
  }

  saveAnswers(): Promise<void> {
    return this.run(async () => {
      this.ans = await this.api.put<ApplicationAnswers>('/profile/answers', this.ans);
      return this.i18n.t('setup.answers.saved');
    });
  }

  setMode(id: Provider | 'local'): void {
    this.mode.set(id);
    const ai = this.cfg!.ai;
    ai.provider = id === 'local' ? 'litellm' : id;
    if (id === 'local') {
      void this.scanLocal();
    } else {
      ai.api_base = null;
    }
  }

  async scanLocal(): Promise<void> {
    this.local.set(null);
    this.local.set(await this.api.get<Record<LocalServer, { running: boolean; models: string[] }>>('/ai/local'));
  }

  pickLocal(server: LocalServer, model: string): void {
    const s = this.localServers.find((x) => x.id === server)!;
    this.cfg!.ai.model = s.prefix + model;
    this.cfg!.ai.api_base = s.base;
  }

  testAI(): Promise<void> {
    return this.run(async () => {
      const r = await this.api.post<{ ok: boolean; message: string }>('/ai/check', this.cfg!.ai);
      if (!r.ok) throw new Error(this.i18n.t('setup.ai.failed', { msg: r.message }));
      return this.i18n.t('setup.ai.connected', { msg: r.message });
    });
  }

  startRun(): Promise<void> {
    return this.run(async () => {
      await this.api.post('/runs', { stages: ['discover', 'enrich', 'rank', 'score'] });
      await this.router.navigate(['/live']);
      return this.i18n.t('setup.finish.started');
    });
  }
}
