import { Component, computed, ElementRef, inject, OnInit, signal, viewChild, WritableSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, Lang, SourcePipe, TPipe } from '../i18n';
import { expandQueries, InferPayload, lines, Profile, Provider, SearchConfig, Segment, Status, unlines } from '../types';

type StepNo = 1 | 2 | 3 | 4;
type AiMode = Provider | 'local';
type LocalServer = 'ollama' | 'lmstudio';
type EeoKey = 'eeo_gender' | 'eeo_race' | 'eeo_hispanic' | 'eeo_veteran' | 'eeo_disability';
type Chip = { text: string; on: boolean };
type Field = { key: string; label: string; kind: 'text' | 'ltr' | 'num' };
type Upload = { cv_name: string; segments: Segment[]; cv_source_format: Profile['cv_source_format']; cv_approved: boolean; cv_renderer_ok: boolean };

// answers the user must say yes to on screen 3: their saved state is shown there and only sent when changed
const SENSITIVE = new Set(['answers.authorized_countries', 'answers.salary_expectation', 'answers.salary_currency', 'answers.eeo_gender', 'answers.eeo_race', 'answers.eeo_hispanic', 'answers.eeo_veteran', 'answers.eeo_disability']);
const STEPS: StepNo[] = [1, 2, 3, 4];
const FIELD_GROUPS: { id: string; title: string; fields: Field[] }[] = [
  {
    id: 'you',
    title: 'welcome.g.you',
    fields: [
      { key: 'profile.full_name', label: 'welcome.f.name', kind: 'text' },
      { key: 'profile.email', label: 'welcome.f.email', kind: 'ltr' },
      { key: 'profile.phone', label: 'welcome.f.phone', kind: 'ltr' },
      { key: 'profile.location', label: 'welcome.f.location', kind: 'text' },
    ],
  },
  {
    id: 'now',
    title: 'welcome.g.now',
    fields: [
      { key: 'answers.current_title', label: 'welcome.f.title', kind: 'text' },
      { key: 'answers.current_company', label: 'welcome.f.company', kind: 'text' },
      { key: 'answers.years_experience', label: 'welcome.f.years', kind: 'num' },
    ],
  },
  {
    id: 'links',
    title: 'welcome.g.links',
    fields: [
      { key: 'answers.linkedin', label: 'welcome.f.linkedin', kind: 'ltr' },
      { key: 'answers.github', label: 'welcome.f.github', kind: 'ltr' },
      { key: 'answers.portfolio', label: 'welcome.f.portfolio', kind: 'ltr' },
    ],
  },
];
const SRC_TEXT: Record<string, string> = {
  cv: 'welcome.src.cv',
  country: 'welcome.src.country',
  roles: 'welcome.src.roles',
  years: 'welcome.src.years',
  default: 'welcome.src.default',
};

// The first-run flow: four screens that replace the ten-tab Setup. Labels in the arrays are i18n keys.
@Component({
  selector: 'app-welcome',
  imports: [FormsModule, RouterLink, SourcePipe, TPipe],
  template: `
    <div class="mx-auto max-w-3xl">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="text-lg font-bold text-slate-900 dark:text-white">LinKit <span class="text-brand-600">All</span></div>
        <div class="flex items-center gap-2">
          <div class="flex items-center gap-1" role="group" [attr.aria-label]="'shell.language' | t">
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="en" dir="ltr" [class.btn-primary]="i18n.lang() === 'en'" [attr.aria-pressed]="i18n.lang() === 'en'" (click)="setLang('en')">English</button>
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="ar" dir="rtl" [class.btn-primary]="i18n.lang() === 'ar'" [attr.aria-pressed]="i18n.lang() === 'ar'" (click)="setLang('ar')">العربية</button>
          </div>
        </div>
      </div>
      <p class="mt-4 text-sm text-slate-600 dark:text-slate-400">{{ 'welcome.promise' | t }}</p>

      @if (!status()) {
        <p class="mt-8 text-sm text-slate-500">{{ 'common.loading' | t }}</p>
      } @else {
        <div class="mt-6 flex items-center justify-between text-sm text-slate-500" role="group" [attr.aria-label]="'welcome.progress' | t">
          <span>{{ 'welcome.step' | t: { n: step() } }}</span>
          <ol class="flex gap-1" aria-hidden="true">
            @for (n of steps; track n) {
              <li class="h-1.5 w-10 rounded-full" [class]="n <= step() ? 'bg-brand-600' : 'bg-slate-200 dark:bg-slate-700'"></li>
            }
          </ol>
        </div>

        <section class="card mt-3 space-y-5">
          <h1 #heading tabindex="-1" class="!outline-none">{{ headings[step() - 1] | t }}</h1>

          @switch (step()) {
            @case (1) {
              <div class="rounded-xl border-2 border-dashed p-8 text-center transition-colors"
                   [class]="dragging() ? 'border-brand-500 bg-brand-50 dark:bg-slate-800' : 'border-slate-300 dark:border-slate-700'"
                   (dragover)="dragOver($event)" (dragleave)="dragging.set(false)" (drop)="dropped($event)">
                @if (cvBusy()) {
                  <p class="text-sm text-slate-500" role="status">{{ 'welcome.cv.reading' | t }}</p>
                } @else {
                  <p class="text-sm text-slate-600 dark:text-slate-400">{{ (dragging() ? 'welcome.cv.dropNow' : cv()?.approved ? 'welcome.cv.ready' : 'welcome.cv.drop') | t }}</p>
                  <label class="btn mt-3 cursor-pointer focus-within:ring-2 focus-within:ring-brand-500">
                    {{ (cv() ? 'welcome.cv.replace' : 'welcome.cv.choose') | t }}
                    <input type="file" accept=".docx,.odt,.pdf,.tex,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.oasis.opendocument.text,application/pdf,application/x-tex,text/x-tex" class="sr-only" (change)="picked($event)">
                  </label>
                }
                <p class="hint mt-3">{{ 'welcome.cv.formats' | t }}</p>
              </div>

              @if (cvError()) {
                <div class="alert alert-error" role="alert">
                  <p><strong>{{ 'welcome.cv.failed' | t }}</strong></p>
                  <p class="mt-1" dir="auto">{{ cvError() }}</p>
                  <p class="mt-2 text-xs">{{ 'welcome.retry' | t }}: {{ 'welcome.cv.choose' | t }}</p>
                </div>
              }

              @if (cv(); as c) {
                <div class="flex flex-wrap items-center gap-3 text-sm">
                  <bdi class="font-medium">{{ c.name }}</bdi>
                  @if (c.parts) { <span class="text-slate-500">{{ 'welcome.cv.parts' | t: { n: c.parts } }}</span> }
                  @if (c.rendererOk ?? status()!.libreoffice) {
                    <a class="btn" href="/api/profile/cv/pdf" target="_blank" rel="noopener">{{ 'setup.cv.preview' | t }}</a>
                  }
                </div>
                @if (!c.approved) {
                  <div class="alert alert-error" role="alert">
                    <p><strong>{{ 'setup.cv.checkTitle' | t }}</strong> {{ 'setup.cv.checkBody' | t }}</p>
                    <button type="button" class="btn btn-primary mt-3" (click)="approve()" [disabled]="cvBusy()">{{ 'setup.cv.approve' | t }}</button>
                  </div>
                }
                @if (c.format === 'tex') {
                  @if (c.rendererOk === false) {
                    <div class="alert alert-error">{{ 'setup.cv.tectonicA' | t }}<a href="https://tectonic-typesetting.github.io" target="_blank" rel="noopener">Tectonic</a>{{ 'setup.cv.tectonicB' | t }}<code dir="ltr">linkit doctor</code>{{ 'setup.cv.tectonicC' | t }}</div>
                  }
                } @else if (!status()!.libreoffice) {
                  <div class="alert alert-error">{{ 'setup.cv.noLibreA' | t }}<code dir="ltr">linkit doctor</code>{{ 'setup.cv.noLibreB' | t }}</div>
                }
              }
            }

            @case (2) {
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'welcome.ai.intro' | t }}</p>
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
                  @if (ai().state === 'idle') { <p class="hint">{{ 'welcome.ai.pickModel' | t }}</p> }
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
            }

            @case (3) {
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'welcome.found.intro' | t }}</p>
              @if (inferError()) {
                <div class="alert alert-error" role="alert">
                  <p><strong>{{ 'welcome.found.failed' | t }}</strong></p>
                  <p class="mt-1" dir="auto">{{ inferError() }}</p>
                  <button type="button" class="btn mt-3" (click)="loadInfer()">{{ 'welcome.retry' | t }}</button>
                </div>
              } @else if (!infer()) {
                <p class="text-sm text-slate-500" role="status">{{ 'welcome.found.loading' | t }}</p>
              } @else {
                @if (aiFilling()) { <p class="text-sm text-slate-500" role="status">{{ 'welcome.found.aiBusy' | t }}</p> }

                @for (g of groups; track g.id) {
                  <div class="space-y-3 border-t border-slate-100 pt-4 dark:border-slate-800">
                    <h2 class="!text-sm">{{ g.title | t }}</h2>
                    <div class="grid gap-4 sm:grid-cols-2">
                      @for (f of g.fields; track f.key) {
                        <div>
                          <label class="label" [for]="'f-' + f.key">{{ f.label | t }}</label>
                          <input [id]="'f-' + f.key" class="input" [attr.dir]="f.kind === 'text' ? 'auto' : 'ltr'" [type]="f.kind === 'num' ? 'number' : 'text'"
                                 [attr.min]="f.kind === 'num' ? 0 : null" [attr.max]="f.kind === 'num' ? 60 : null"
                                 [value]="text(f.key)" (input)="onField(f, $event)" [placeholder]="'welcome.found.missing' | t">
                          @if (badge(f.key); as b) { <span class="badge mt-1" [class]="b.warn ? 'tier-mid' : 'tier-low'">{{ b.text | t }}</span> }
                        </div>
                      }
                    </div>
                  </div>
                }

                <div class="space-y-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                  <h2 class="!text-sm">{{ 'welcome.g.skills' | t: { n: list('profile.skills').length } }}</h2>
                  <label class="sr-only" for="f-skills">{{ 'welcome.g.skills' | t: { n: list('profile.skills').length } }}</label>
                  <textarea id="f-skills" class="input h-24" dir="auto" [value]="unlines(list('profile.skills'))" (change)="onLines('profile.skills', $event)" [placeholder]="'welcome.found.missing' | t"></textarea>
                  <div class="flex items-center gap-2">
                    <span class="hint !mt-0">{{ 'welcome.found.linesHint' | t }}</span>
                    @if (badge('profile.skills'); as b) { <span class="badge" [class]="b.warn ? 'tier-mid' : 'tier-low'">{{ b.text | t }}</span> }
                  </div>
                </div>

                <div class="space-y-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                  <h2 class="!text-sm">{{ 'welcome.g.locked' | t }}</h2>
                  <p class="hint !mt-0">{{ 'welcome.g.lockedHint' | t }}</p>
                  <label class="sr-only" for="f-locked">{{ 'welcome.g.locked' | t }}</label>
                  <textarea id="f-locked" class="input h-24" dir="auto" [value]="unlines(list('profile.locked_facts'))" (change)="onLines('profile.locked_facts', $event)" [placeholder]="'welcome.found.missing' | t"></textarea>
                  @if (badge('profile.locked_facts'); as b) { <span class="badge" [class]="b.warn ? 'tier-mid' : 'tier-low'">{{ b.text | t }}</span> }
                </div>

                <div class="space-y-4 border-t border-slate-100 pt-4 dark:border-slate-800">
                  <div>
                    <h2 class="!text-sm">{{ 'welcome.forms.title' | t }}</h2>
                    <p class="hint">{{ 'welcome.forms.note' | t }}</p>
                  </div>

                  @if (countryName()) {
                    <div role="group" aria-labelledby="q-auth">
                      <p id="q-auth" class="label"><bdi>{{ 'welcome.forms.auth' | t: { country: countryName() } }}</bdi></p>
                      <div class="flex flex-wrap gap-2">
                        <button type="button" class="btn" [class.btn-primary]="authorized() === 'yes'" [attr.aria-pressed]="authorized() === 'yes'" (click)="authorized.set('yes')">{{ 'common.yes' | t }}</button>
                        <button type="button" class="btn" [class.btn-primary]="authorized() === 'no'" [attr.aria-pressed]="authorized() === 'no'" (click)="authorized.set('no')">{{ 'common.no' | t }}</button>
                        <button type="button" class="btn" [class.btn-primary]="authorized() === 'ask'" [attr.aria-pressed]="authorized() === 'ask'" (click)="authorized.set('ask')">{{ 'welcome.forms.ask' | t }}</button>
                      </div>
                    </div>
                  }

                  <div role="group" aria-labelledby="q-demo">
                    <p id="q-demo" class="label">{{ 'welcome.forms.demo' | t }}</p>
                    <div class="flex flex-wrap gap-2">
                      <button type="button" class="btn" [class.btn-primary]="eeoMode() === 'decline'" [attr.aria-pressed]="eeoMode() === 'decline'" (click)="eeoMode.set('decline')">{{ 'welcome.forms.declineAll' | t }}</button>
                      <button type="button" class="btn" [class.btn-primary]="eeoMode() === 'ask'" [attr.aria-pressed]="eeoMode() === 'ask'" (click)="eeoMode.set('ask')">{{ 'welcome.forms.askEach' | t }}</button>
                      <button type="button" class="btn" [class.btn-primary]="eeoMode() === 'now'" [attr.aria-pressed]="eeoMode() === 'now'" (click)="eeoMode.set('now')">{{ 'welcome.forms.answerNow' | t }}</button>
                    </div>
                    <p class="hint">{{ 'welcome.forms.demoHint' | t }}</p>
                    @if (eeoMode() === 'now') {
                      <div class="mt-3 grid gap-4 sm:grid-cols-2">
                        @for (f of eeoFields; track f.key) {
                          <div>
                            <label class="label" [for]="'e-' + f.key">{{ f.label | t }}</label>
                            <select [id]="'e-' + f.key" class="input" [ngModel]="eeo[f.key]" (ngModelChange)="eeo[f.key] = $event">
                              <option value="">{{ 'welcome.forms.ask' | t }}</option>
                              @for (o of f.options; track o[0]) { <option [value]="o[0]">{{ o[1] | t }}</option> }
                              <option value="decline">{{ 'setup.eeo.decline' | t }}</option>
                            </select>
                          </div>
                        }
                      </div>
                    }
                  </div>

                  <div class="max-w-xs">
                    <label class="label" for="salary">{{ (infer()!.country.currency ? 'welcome.forms.salary' : 'welcome.forms.salaryPlain') | t: { cur: infer()!.country.currency } }}</label>
                    <input id="salary" dir="ltr" inputmode="numeric" class="input" [(ngModel)]="salary" placeholder="30000">
                    <p class="hint">{{ 'welcome.forms.salaryHint' | t }}</p>
                  </div>
                </div>
              }
            }

            @case (4) {
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'welcome.jobs.intro' | t }}</p>

              <div>
                <p class="label" id="l-roles">{{ 'welcome.jobs.roles' | t }}</p>
                <div class="flex flex-wrap gap-2" role="group" aria-labelledby="l-roles">
                  @for (c of roles(); track c.text) {
                    <button type="button" [class]="chipClass(c.on)" [attr.aria-pressed]="c.on" (click)="toggleChip(roles, c.text, 'roles')"><bdi>{{ c.text }}</bdi></button>
                  }
                </div>
                <div class="mt-2 flex max-w-md gap-2">
                  <input class="input" dir="auto" [(ngModel)]="newRole" (keydown.enter)="addRole()" [attr.aria-label]="'welcome.jobs.addRole' | t" [placeholder]="'welcome.jobs.addRole' | t">
                  <button type="button" class="btn" (click)="addRole()" [disabled]="!newRole.trim()">{{ 'welcome.jobs.add' | t }}</button>
                </div>
              </div>

              <div>
                <p class="label" id="l-level">{{ 'welcome.jobs.level' | t }}</p>
                <div class="flex flex-wrap items-center gap-2" role="group" aria-labelledby="l-level">
                  @for (s of seniorities; track s) {
                    <button type="button" [class]="chipClass(level().includes(s))" [attr.aria-pressed]="level().includes(s)" (click)="toggleLevel(s)">{{ 'setup.seniority.' + s | t }}</button>
                  }
                </div>
                @if (years() !== null && !touched.has('filters.seniority')) { <p class="hint">{{ 'welcome.jobs.levelYears' | t: { n: years()! } }}</p> }
              </div>

              <div>
                <p class="label" id="l-where">{{ 'welcome.jobs.where' | t }}</p>
                <div class="flex flex-wrap items-center gap-2" role="group" aria-labelledby="l-where">
                  @for (c of where(); track c.text) {
                    <button type="button" [class]="chipClass(c.on)" [attr.aria-pressed]="c.on" (click)="toggleChip(where, c.text, 'where')"><bdi>{{ c.text }}</bdi></button>
                  }
                </div>
                <div class="mt-2 flex max-w-md gap-2">
                  <input class="input" dir="auto" [(ngModel)]="newPlace" (keydown.enter)="addPlace()" [attr.aria-label]="'welcome.jobs.addPlace' | t" [placeholder]="'welcome.jobs.addPlace' | t">
                  <button type="button" class="btn" (click)="addPlace()" [disabled]="!newPlace.trim()">{{ 'welcome.jobs.add' | t }}</button>
                </div>
                <label class="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" [checked]="remote()" (change)="remote.set(!remote())"> {{ 'welcome.jobs.remote' | t }}</label>
              </div>

              <div>
                <p class="label" id="l-kind">{{ 'welcome.jobs.kind' | t }}</p>
                <div class="flex flex-wrap gap-2" role="group" aria-labelledby="l-kind">
                  <button type="button" [class]="chipClass(track() === 'tech')" [attr.aria-pressed]="track() === 'tech'" (click)="setTrack('tech')">{{ 'welcome.jobs.tech' | t }}</button>
                  <button type="button" [class]="chipClass(track() === 'general')" [attr.aria-pressed]="track() === 'general'" (click)="setTrack('general')">{{ 'welcome.jobs.general' | t }}</button>
                </div>
                <p class="hint">{{ 'welcome.jobs.kindHint' | t }}</p>
              </div>

              @if (infer(); as inf) {
                <div>
                  <p class="label">{{ 'welcome.jobs.sources' | t }}</p>
                  <p class="text-sm">
                    @for (s of sourceNames(); track s; let last = $last) { <bdi>{{ s | src }}</bdi>@if (!last) {<span>, </span>} }
                    @if (inf.sources.enabled.length) { <span class="text-slate-500"> {{ 'welcome.jobs.sourcesMore' | t: { n: inf.sources.enabled.length } }}</span> }
                  </p>
                </div>
              }

              @if (startError()) {
                <div class="alert alert-error" role="alert">
                  <p><strong>{{ 'welcome.jobs.failed' | t }}</strong></p>
                  <p class="mt-1" dir="auto">{{ startError() }}</p>
                </div>
              }
              <p class="hint">{{ 'welcome.jobs.note' | t }}</p>
            }
          }

          <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
            @if (step() > 1) {
              <button type="button" class="btn" (click)="go(prev())">{{ 'welcome.back' | t }}</button>
            } @else { <span></span> }
            @if (step() < 4) {
              <button type="button" class="btn btn-primary" (click)="go(next())" [disabled]="!canNext()">{{ 'welcome.next' | t }}</button>
            } @else {
              <div class="flex flex-col items-end gap-1">
                <button type="button" class="btn btn-primary" (click)="start()" [disabled]="!canNext() || starting()">{{ (starting() ? 'welcome.jobs.starting' : startError() ? 'welcome.retry' : 'welcome.jobs.find') | t }}</button>
                @if (!canNext()) { <span class="hint !mt-0">{{ 'welcome.jobs.need' | t }}</span> }
              </div>
            }
          </div>
        </section>

        <p class="mt-4 text-center text-xs"><a routerLink="/setup">{{ 'welcome.skip' | t }}</a></p>
      }
    </div>
  `,
})
export class WelcomePage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly i18n = inject(I18n);
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  protected readonly steps = STEPS;
  protected readonly groups = FIELD_GROUPS;
  protected readonly headings = ['welcome.cv.title', 'welcome.ai.title', 'welcome.found.title', 'welcome.jobs.title'];
  protected readonly unlines = unlines;
  protected readonly status = signal<Status | null>(null);
  protected readonly step = signal<StepNo>(1);

  // screen 1
  protected readonly cv = signal<{ name: string; parts: number; approved: boolean; rendererOk?: boolean; format?: Profile['cv_source_format'] } | null>(null);
  protected readonly cvBusy = signal(false);
  protected readonly cvError = signal('');
  protected readonly dragging = signal(false);

  // screen 2
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
  protected readonly ai = signal<{ state: 'idle' | 'testing' | 'ok' | 'fail'; msg: string }>({ state: 'idle', msg: '' });
  protected readonly local = signal<Record<LocalServer, { running: boolean; models: string[] }> | null>(null);
  protected model = '';
  protected apiBase = '';
  private cfg: SearchConfig | null = null;
  private testId = 0;
  private aiEntered = false;

  // screen 3
  protected readonly infer = signal<InferPayload | null>(null);
  protected readonly inferError = signal('');
  protected readonly aiFilling = signal(false);
  protected readonly vals = signal<Record<string, unknown>>({});
  protected readonly touched = new Set<string>();
  protected readonly authorized = signal<'yes' | 'no' | 'ask' | null>(null);
  protected readonly eeoMode = signal<'ask' | 'decline' | 'now'>('ask');
  protected eeo: Record<EeoKey, string> = { eeo_gender: '', eeo_race: '', eeo_hispanic: '', eeo_veteran: '', eeo_disability: '' };
  protected salary = '';
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
  protected readonly countryName = computed(() => String(this.vals()['answers.country'] ?? this.infer()?.country.name ?? ''));

  // screen 4
  protected readonly roles = signal<Chip[]>([]);
  protected readonly where = signal<Chip[]>([]);
  protected readonly remote = signal(true);
  protected readonly track = signal<'tech' | 'general'>('general');
  protected readonly seniorities = ['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'executive'];
  protected readonly level = computed(() => this.list('filters.seniority'));
  protected readonly years = computed(() => {
    const y = this.vals()['answers.years_experience'];
    return typeof y === 'number' ? y : null;
  });
  protected readonly sourceNames = computed(() => {
    const s = this.infer()?.sources;
    return s ? [...s.regional, ...s.jobspy] : [];
  });
  protected newRole = '';
  protected newPlace = '';
  protected readonly starting = signal(false);
  protected readonly startError = signal('');
  // once the user (or a saved config) has set a list, a later CV re-read must not overwrite it
  /** What is already stored (non-empty only), when setup was done before; wins over CV guesses and is only re-sent when changed. */
  private saved: Record<string, unknown> = {};
  private rolesSet = false;
  private whereSet = false;
  private trackSet = false;

  protected readonly canNext = computed(() => {
    switch (this.step()) {
      case 1: {
        const c = this.cv();
        return !!c && c.approved && !this.cvBusy();
      }
      case 2:
        return this.ai().state === 'ok';
      case 3:
        return !!(this.text('profile.full_name').trim() && this.text('profile.email').trim()) && !!this.infer();
      default:
        return this.roles().some((c) => c.on) && this.where().some((c) => c.on);
    }
  });

  async ngOnInit(): Promise<void> {
    try {
      const [status, profile, cfg] = await Promise.all([
        this.api.get<Status>('/status'),
        this.api.get<Profile>('/profile'),
        this.api.get<SearchConfig>('/search'),
      ]);
      this.cfg = cfg;
      if (status.setup.profile) await this.loadSaved(profile);
      if (profile.cv_name) {
        this.cv.set({ name: profile.cv_name, parts: 0, approved: profile.cv_approved !== false, rendererOk: profile.cv_renderer_ok, format: profile.cv_source_format });
      }
      // coming back to edit: the saved roles and places are the starting point, not the CV guess
      if (status.setup.roles && cfg.search.queries.length) {
        this.roles.set(cfg.search.queries.map((text) => ({ text, on: true })));
        this.rolesSet = true;
      }
      if (status.setup.where) {
        const places = cfg.search.locations.filter((p) => p.toLowerCase() !== 'remote');
        this.where.set(places.map((text) => ({ text, on: true })));
        this.remote.set(cfg.search.locations.length > places.length);
        this.whereSet = true;
      }
      this.status.set(status);
      const next = status.setup.next_step;
      this.go(next === 'cv' ? 1 : next === 'ai' ? 2 : next === 'profile' ? 3 : 4);
    } catch (e) {
      // the server may be starting: show the first screen so the user can still upload a CV
      this.cvError.set((e as Error).message);
      this.status.set({ setup: { cv: false, ai: false, profile: false, roles: false, where: false, required_done: false, next_step: 'cv' }, libreoffice: true } as Status);
    }
  }

  /** Seed screen 3 from the stored profile and answers, and show the saved state of the sensitive questions. */
  private async loadSaved(profile: Profile): Promise<void> {
    const ans = await this.api.get<Record<string, unknown>>('/profile/answers');
    const all: Record<string, unknown> = {};
    for (const k of ['full_name', 'email', 'phone', 'location', 'skills', 'locked_facts'] as const) all[`profile.${k}`] = profile[k];
    for (const [k, v] of Object.entries(ans)) all[`answers.${k}`] = v;
    all['filters.seniority'] = this.cfg?.filters.seniority;
    all['filters.title_exclude'] = this.cfg?.filters.title_exclude;
    this.saved = Object.fromEntries(Object.entries(all).filter(([, v]) => v !== '' && v !== null && v !== undefined && !(Array.isArray(v) && !v.length)));
    this.vals.set(Object.fromEntries(Object.entries(this.saved).filter(([k]) => !SENSITIVE.has(k))));
    const country = String(this.saved['answers.country'] ?? '');
    if (country && asList(this.saved['answers.authorized_countries']).includes(country)) this.authorized.set('yes');
    const eeo = this.eeoFields.map((f) => this.saved[`answers.${f.key}`]);
    if (eeo.every((v) => v === 'decline')) this.eeoMode.set('decline');
    else if (eeo.some((v) => v)) {
      this.eeoMode.set('now');
      for (const f of this.eeoFields) this.eeo[f.key] = String(this.saved[`answers.${f.key}`] ?? '');
    }
    this.salary = String(this.saved['answers.salary_expectation'] ?? '');
  }

  protected setLang(lang: Lang): void {
    this.i18n.set(lang);
  }

  protected prev(): StepNo {
    return Math.max(1, this.step() - 1) as StepNo;
  }

  protected next(): StepNo {
    return Math.min(4, this.step() + 1) as StepNo;
  }

  protected go(n: StepNo): void {
    this.step.set(n);
    setTimeout(() => this.heading()?.nativeElement.focus());
    if (n === 2) void this.enterAi();
    if (n >= 3 && !this.infer()) void this.loadInfer();
  }

  // ---- screen 1: CV ------------------------------------------------------------------

  protected dragOver(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(true);
  }

  protected dropped(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) void this.upload(file);
  }

  protected picked(e: Event): void {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // the same file can be chosen again after a failure
    if (file) void this.upload(file);
  }

  private async upload(file: File): Promise<void> {
    this.cvBusy.set(true);
    this.cvError.set('');
    try {
      const r = await this.api.upload<Upload>('/profile/cv', file);
      this.cv.set({ name: r.cv_name, parts: r.segments.length, approved: r.cv_approved, rendererOk: r.cv_renderer_ok, format: r.cv_source_format });
      this.status.set(await this.api.get<Status>('/status'));
      this.resetEdits(); // a different CV means different guesses
      this.infer.set(null);
      if (this.ai().state === 'ok') void this.fillAi();
    } catch (e) {
      this.cvError.set((e as Error).message);
    } finally {
      this.cvBusy.set(false);
    }
  }

  protected async approve(): Promise<void> {
    this.cvBusy.set(true);
    this.cvError.set('');
    try {
      await this.api.post<Profile>('/profile/cv/approve', {});
      this.cv.update((c) => (c ? { ...c, approved: true } : c));
      this.status.set(await this.api.get<Status>('/status'));
    } catch (e) {
      this.cvError.set((e as Error).message);
    } finally {
      this.cvBusy.set(false);
    }
  }

  // ---- screen 2: AI ------------------------------------------------------------------

  private async enterAi(): Promise<void> {
    if (this.aiEntered) return;
    this.aiEntered = true;
    try {
      const r = await this.api.get<{ provider: Provider | null; available: Record<Provider, boolean> }>('/ai');
      this.available.set(r.available);
      const saved = this.cfg?.ai;
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
      void this.test();
    } catch (e) {
      this.loaded.set(true);
      this.ai.set({ state: 'fail', msg: (e as Error).message });
    }
  }

  protected pick(id: AiMode): void {
    this.mode.set(id);
    this.ai.set({ state: 'idle', msg: '' });
    this.testId++; // an older test must not overwrite this choice
    if (id === 'local') {
      this.apiBase = '';
      this.model = '';
      void this.scanLocal();
    } else {
      this.apiBase = '';
      this.model = '';
      void this.test();
    }
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

  /** Test the chosen connection; when it works, save it (`PUT /search`, like Setup) and let the AI fill the CV gaps. */
  protected async test(): Promise<void> {
    const mode = this.mode();
    if (!mode) return;
    const id = ++this.testId;
    this.ai.set({ state: 'testing', msg: '' });
    const body = { provider: mode === 'local' ? 'litellm' : mode, model: this.model.trim() || null, api_base: mode === 'local' ? this.apiBase.trim() || null : null };
    try {
      const r = await this.api.post<{ ok: boolean; message: string }>('/ai/check', body);
      if (id !== this.testId) return;
      if (!r.ok) return this.ai.set({ state: 'fail', msg: r.message });
      const cfg = await this.api.get<SearchConfig>('/search'); // fresh copy: do not overwrite changes made elsewhere
      cfg.ai = body;
      this.cfg = await this.api.put<SearchConfig>('/search', cfg);
      if (id !== this.testId) return;
      this.ai.set({ state: 'ok', msg: r.message });
      this.status.set(await this.api.get<Status>('/status'));
      void this.fillAi();
    } catch (e) {
      if (id === this.testId) this.ai.set({ state: 'fail', msg: (e as Error).message });
    }
  }

  /** One background model call for what the rules missed. Errors are ignored: the rule-based values are enough. */
  private async fillAi(): Promise<void> {
    if (this.aiFilling()) return;
    this.aiFilling.set(true);
    try {
      this.applyInfer(await this.api.post<InferPayload>('/infer/ai-fill'));
    } catch {
      // no AI, no CV or a provider error: nothing to show
    } finally {
      this.aiFilling.set(false);
    }
  }

  // ---- screen 3: what we found -------------------------------------------------------

  protected async loadInfer(): Promise<void> {
    this.inferError.set('');
    try {
      this.applyInfer(await this.api.get<InferPayload>('/infer'));
    } catch (e) {
      this.inferError.set((e as Error).message);
    }
  }

  /** Take the server's guesses for everything the user has not touched. Seeds the screen 4 lists the same way. */
  private applyInfer(p: InferPayload): void {
    this.infer.set(p);
    const next = { ...this.vals() };
    // a stored value wins over the CV's guess; the guess only fills what is empty
    for (const [k, v] of Object.entries(p.values)) if (!this.touched.has(k) && !(k in this.saved)) next[k] = v.value;
    this.derive(next);
    this.vals.set(next);
    if (!this.rolesSet) this.roles.set(asList(next['search.queries']).map((text) => ({ text, on: true })));
    if (!this.whereSet) {
      const place = String(next['answers.country'] || next['profile.location'] || '').trim();
      this.where.set(place ? [{ text: place, on: true }] : []);
    }
    if (!this.trackSet) this.track.set(next['track'] === 'tech' ? 'tech' : 'general');
  }

  /** First/last name and city follow the full name and location unless the CV gave them. */
  private derive(v: Record<string, unknown>, force = false): void {
    const name = String(v['profile.full_name'] ?? '').trim();
    if (name && (force || !v['answers.first_name'])) {
      const [first, ...rest] = name.split(/\s+/);
      v['answers.first_name'] = first;
      v['answers.last_name'] = rest.join(' ');
    }
    const city = String(v['profile.location'] ?? '').split(/[,،]/)[0].trim();
    if (city && (force || !v['answers.city'])) v['answers.city'] = city;
  }

  private resetEdits(): void {
    this.vals.set({});
    this.touched.clear();
    this.rolesSet = this.whereSet = this.trackSet = false;
    this.roles.set([]);
    this.where.set([]);
  }

  protected text(key: string): string {
    const v = this.vals()[key];
    return v === undefined || v === null ? '' : String(v);
  }

  protected list(key: string): string[] {
    return asList(this.vals()[key]);
  }

  private set(key: string, value: unknown): void {
    this.touched.add(key);
    const next = { ...this.vals(), [key]: value };
    if (key === 'profile.full_name' || key === 'profile.location') this.derive(next, true);
    this.vals.set(next);
  }

  protected onField(f: Field, e: Event): void {
    const raw = (e.target as HTMLInputElement).value;
    this.set(f.key, f.kind === 'num' ? (raw.trim() === '' ? null : Math.max(0, Math.round(Number(raw)))) : raw);
  }

  protected onLines(key: string, e: Event): void {
    this.set(key, lines((e.target as HTMLTextAreaElement).value));
  }

  /** The small source label under a value; null when the CV said nothing about it. */
  protected badge(key: string): { text: string; warn: boolean } | null {
    if (this.touched.has(key)) return { text: 'welcome.src.you', warn: false };
    if (key in this.saved) return { text: 'welcome.src.saved', warn: false };
    const v = this.infer()?.values[key];
    if (!v) return null;
    if (v.source === 'ai') return { text: 'welcome.src.ai', warn: true };
    if (v.check) return { text: 'welcome.src.cvCheck', warn: true };
    return { text: SRC_TEXT[v.source] ?? 'welcome.src.cv', warn: false };
  }

  // ---- screen 4: what jobs -----------------------------------------------------------

  protected chipClass(on: boolean): string {
    return `rounded-full border px-3 py-1 text-sm ${on ? 'border-brand-500 bg-brand-50 font-medium text-brand-700 dark:bg-slate-800 dark:text-white' : 'border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400'}`;
  }

  protected toggleChip(list: WritableSignal<Chip[]>, text: string, which: 'roles' | 'where'): void {
    list.update((cs) => cs.map((c) => (c.text === text ? { ...c, on: !c.on } : c)));
    this.markSet(which);
  }

  private markSet(which: 'roles' | 'where'): void {
    if (which === 'roles') this.rolesSet = true;
    else this.whereSet = true;
  }

  private add(list: WritableSignal<Chip[]>, texts: string[]): void {
    list.update((cs) => {
      const have = new Set(cs.map((c) => c.text.toLowerCase()));
      return [...cs.map((c) => (texts.some((t) => t.toLowerCase() === c.text.toLowerCase()) ? { ...c, on: true } : c)), ...texts.filter((t) => !have.has(t.toLowerCase())).map((text) => ({ text, on: true }))];
    });
  }

  protected addRole(): void {
    const t = this.newRole.trim();
    if (!t) return;
    this.add(this.roles, expandQueries([t])); // "React/Next.JS Developer" becomes two searches
    this.newRole = '';
    this.rolesSet = true;
  }

  protected addPlace(): void {
    const t = this.newPlace.trim();
    if (!t) return;
    this.add(this.where, [t]);
    this.newPlace = '';
    this.whereSet = true;
  }

  protected toggleLevel(s: string): void {
    const cur = this.level();
    this.set('filters.seniority', cur.includes(s) ? cur.filter((x) => x !== s) : this.seniorities.filter((x) => x === s || cur.includes(x)));
  }

  protected setTrack(t: 'tech' | 'general'): void {
    this.track.set(t);
    this.trackSet = true;
  }

  /** Apply everything the user confirmed, then start the search (discover to score). Applying nothing is submitted. */
  protected async start(): Promise<void> {
    this.starting.set(true);
    this.startError.set('');
    try {
      const values: Record<string, unknown> = {};
      const changed = (k: string, v: unknown) => JSON.stringify(v) !== JSON.stringify(this.saved[k] ?? (Array.isArray(v) ? [] : typeof v === 'string' ? '' : null));
      for (const [k, v] of Object.entries(this.vals())) {
        // track is sent on its own; sensitive answers are only sent when the user answers them below
        if (k === 'track' || k === 'search.queries' || SENSITIVE.has(k) || v === undefined) continue;
        if (v === null && !(k in this.saved)) continue;
        if (changed(k, v)) values[k] = v;
      }
      const queries = this.roles().filter((c) => c.on).map((c) => c.text);
      if (JSON.stringify(queries) !== JSON.stringify(this.cfg?.search.queries ?? [])) values['search.queries'] = queries;
      const country = this.countryName();
      const savedAuth = asList(this.saved['answers.authorized_countries']);
      if (this.authorized() === 'yes' && country && !savedAuth.includes(country)) values['answers.authorized_countries'] = [country];
      else if ((this.authorized() === 'no' || this.authorized() === 'ask') && savedAuth.length) values['answers.authorized_countries'] = [];
      for (const f of this.eeoFields) {
        const mode = this.eeoMode();
        const target = mode === 'decline' ? 'decline' : mode === 'now' ? this.eeo[f.key] || null : null;
        if (target !== ((this.saved[`answers.${f.key}`] as string | undefined) ?? null)) values[`answers.${f.key}`] = target;
      }
      if (this.salary.trim() !== String(this.saved['answers.salary_expectation'] ?? '')) values['answers.salary_expectation'] = this.salary.trim();
      await this.api.post('/infer/apply', { values, where: this.where().filter((c) => c.on).map((c) => c.text), remote: this.remote(), track: this.track() });
      await this.api.post('/runs', { stages: ['discover', 'enrich', 'rank', 'score'] });
      await this.router.navigate(['/live']);
    } catch (e) {
      this.startError.set((e as Error).message);
    } finally {
      this.starting.set(false);
    }
  }
}

function asList(v: unknown): string[] {
  return Array.isArray(v) ? v.map(String) : [];
}
