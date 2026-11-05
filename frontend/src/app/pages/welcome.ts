import { Component, computed, effect, ElementRef, inject, OnInit, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api } from '../api';
import { AiConnect, AiState } from '../components/ai-connect';
import { ChipOption, ChipSelect } from '../components/chip-select';
import { Countries } from '../components/countries';
import { LibreOfficeCard } from '../components/libreoffice-card';
import { Privacy } from '../components/privacy';
import { PhoneInput } from '../components/phone-input';
import { PlacePick, PlacePicker } from '../components/place-picker';
import { PlacesList } from '../components/places-list';
import { TagInput } from '../components/tag-input';
import { I18n, Lang, SourcePipe, TPipe } from '../i18n';
import { currencyLabel, cvLabel, levelTip } from '../locale';
import { expandQueries, InferPayload, Place, Profile, SearchConfig, Segment, Status, WorkMode } from '../types';

type StepNo = 1 | 2 | 3 | 4;
type EeoKey = 'eeo_gender' | 'eeo_race' | 'eeo_hispanic' | 'eeo_veteran' | 'eeo_disability';
type Field = { key: string; label: string; kind: 'text' | 'ltr' | 'num' };
type Upload = { cv_name: string; segments: Segment[]; cv_source_format: Profile['cv_source_format']; cv_approved: boolean; cv_renderer_ok: boolean };

// answers the user must say yes to on screen 3: their saved state is shown there and only sent when changed
// (work rights come from the places on screen 4, so the suggested authorized_countries is never sent)
const SENSITIVE = new Set(['answers.authorized_countries', 'answers.salary_expectation', 'answers.salary_currency', 'answers.eeo_gender', 'answers.eeo_race', 'answers.eeo_hispanic', 'answers.eeo_veteran', 'answers.eeo_disability']);
const STEPS: StepNo[] = [1, 2, 3, 4];
const FIELD_GROUPS: { id: string; title: string; fields: Field[] }[] = [
  {
    id: 'you',
    title: 'welcome.g.you',
    fields: [
      { key: 'profile.full_name', label: 'welcome.f.name', kind: 'text' },
      { key: 'profile.email', label: 'welcome.f.email', kind: 'ltr' },
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
  imports: [FormsModule, RouterLink, AiConnect, ChipSelect, LibreOfficeCard, PhoneInput, PlacePicker, PlacesList, Privacy, SourcePipe, TagInput, TPipe],
  template: `
    <div class="mx-auto max-w-3xl">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <div class="text-lg font-bold text-slate-900 dark:text-white">LinKit <span class="text-brand-600">All</span></div>
          @if (status(); as st) {
            <span class="badge" [class]="st.apply_live ? 'tier-mid' : 'tier-low'" [title]="(st.apply_live ? 'shell.liveTitle' : 'shell.dryTitle') | t">{{ (st.apply_live ? 'shell.live' : 'welcome.practicePill') | t }}</span>
          }
        </div>
        <div class="flex items-center gap-2">
          <div class="flex items-center gap-1" role="group" [attr.aria-label]="'shell.language' | t">
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="en" dir="ltr" [class.btn-primary]="i18n.lang() === 'en'" [attr.aria-pressed]="i18n.lang() === 'en'" (click)="setLang('en')">English</button>
            <button type="button" class="btn !px-2 !py-1 text-xs" lang="ar" dir="rtl" [class.btn-primary]="i18n.lang() === 'ar'" [attr.aria-pressed]="i18n.lang() === 'ar'" (click)="setLang('ar')">العربية</button>
          </div>
        </div>
      </div>
      <p class="mt-4 text-sm text-slate-600 dark:text-slate-400">{{ 'welcome.promise' | t }}</p>
      <app-privacy class="mt-1 block" />

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
                  <bdi class="font-medium">{{ cvName(c) }}</bdi>
                  @if (c.parts) { <span class="text-slate-500">{{ i18n.plural('welcome.cv.parts', c.parts) }}</span> }
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
                    <div class="alert alert-warn">{{ 'setup.cv.tectonicA' | t }}<a href="https://tectonic-typesetting.github.io" target="_blank" rel="noopener">Tectonic</a>{{ 'setup.cv.tectonicB' | t }}</div>
                  }
                } @else if (!status()!.libreoffice) {
                  <app-libreoffice-card />
                }
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
                      @if (g.id === 'you') {
                        <div>
                          <label class="label" for="f-phone">{{ 'welcome.f.phone' | t }}</label>
                          <app-phone-input inputId="f-phone" [value]="text('profile.phone')" [defaultIso]="text('profile.home_country')" (changed)="set('profile.phone', $event)" />
                          @if (badge('profile.phone'); as b) { <span class="badge mt-1" [class]="b.warn ? 'tier-mid' : 'tier-low'">{{ b.text | t }}</span> }
                        </div>
                        <div>
                          <label class="label" for="f-home">{{ 'welcome.f.location' | t }}</label>
                          <app-place-picker inputId="f-home" [value]="homeText()" [placeholder]="'settings.profile.cityPh' | t" (picked)="setHome($event)" />
                          @if (badge('profile.home_city'); as b) { <span class="badge mt-1" [class]="b.warn ? 'tier-mid' : 'tier-low'">{{ b.text | t }}</span> }
                        </div>
                      }
                    </div>
                  </div>
                }

                <div class="space-y-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                  <h2 class="!text-sm"><label for="f-skills">{{ 'welcome.g.skills' | t: { n: list('profile.skills').length } }}</label></h2>
                  <app-tag-input inputId="f-skills" [values]="list('profile.skills')" [placeholder]="'settings.profile.skillsPh' | t" [recommended]="recSkills()" [caption]="'settings.profile.skillsRec' | t"
                                 (changed)="set('profile.skills', $event)" />
                  @if (badge('profile.skills'); as b) { <span class="badge" [class]="b.warn ? 'tier-mid' : 'tier-low'">{{ b.text | t }}</span> }
                </div>

                <div class="space-y-4 border-t border-slate-100 pt-4 dark:border-slate-800">
                  <div>
                    <h2 class="!text-sm">{{ 'welcome.forms.title' | t }}</h2>
                    <p class="hint">{{ 'welcome.forms.note' | t }}</p>
                  </div>

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
                    <label class="label" for="salary">{{ (currency() ? 'welcome.forms.salary' : 'welcome.forms.salaryPlain') | t: { cur: curName() } }}</label>
                    <input id="salary" dir="ltr" inputmode="numeric" class="input placeholder:italic" [(ngModel)]="salary" [placeholder]="'welcome.forms.salaryPh' | t">
                    <p class="hint">{{ 'welcome.forms.salaryHint' | t }}</p>
                  </div>
                </div>
              }
            }

            @case (4) {
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'welcome.jobs.intro' | t }}</p>

              <div>
                <label class="label" for="w-roles">{{ 'welcome.jobs.roles' | t }}</label>
                <app-tag-input inputId="w-roles" [values]="roles()" [suggest]="titles" [split]="expand" [placeholder]="'welcome.jobs.addRole' | t" (changed)="setRoles($event)" />
              </div>

              <div>
                <label class="label" for="w-place">{{ 'welcome.jobs.where' | t }}</label>
                <app-places-list inputId="w-place" [places]="placesShown()" (changed)="placesEdited.set($event)" />
              </div>

              <div>
                <p class="label">{{ 'welcome.jobs.modes' | t }}</p>
                <app-chip-select [options]="modeOptions()" [selected]="modes()" [label]="'welcome.jobs.modes' | t" (changed)="setModes($event)" />
              </div>

              <div>
                <p class="label">{{ 'welcome.jobs.level' | t }}</p>
                <app-chip-select [options]="levelOptions()" [selected]="level()" [label]="'welcome.jobs.level' | t" (changed)="set('filters.seniority', $event)" />
                @if (years() !== null && !touched.has('filters.seniority')) { <p class="hint">{{ (underYear() ? 'welcome.jobs.levelUnderYear' : 'welcome.jobs.levelYears') | t: { n: years()! } }}</p> }
              </div>

              <div>
                <p class="label">{{ 'welcome.jobs.kind' | t }}</p>
                <app-chip-select [options]="trackOptions()" [selected]="trackSel()" [single]="true" [label]="'welcome.jobs.kind' | t" (changed)="setTrack($event[0])" />
                <p class="hint">{{ 'welcome.jobs.kindHint' | t }}</p>
                <ul class="hint list-disc ps-5">
                  <li>{{ 'welcome.jobs.techHint' | t }}</li>
                  <li>{{ 'welcome.jobs.generalHint' | t }}</li>
                </ul>
              </div>

              @if (infer(); as inf) {
                <div>
                  <p class="label">{{ 'welcome.jobs.sources' | t }}</p>
                  <p class="text-sm">
                    @for (s of sourceNames(); track s; let last = $last) { <bdi>{{ s | src }}</bdi>@if (!last) {<span>, </span>} }
                    @if (inf.sources.enabled.length) { <span class="text-slate-500"> {{ more(inf.sources.enabled.length) }}</span> }
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

          <app-ai-connect [hidden]="step() !== 2" [active]="step() === 2" intro="welcome.ai.intro" (stateChange)="ai.set($event)" (connected)="aiConnected()" />
          @if (step() === 2) { <app-privacy [lead]="false" /> }

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

        <p class="mt-4 text-center text-xs"><a routerLink="/settings">{{ 'welcome.skip' | t }}</a></p>
      }
    </div>
  `,
})
export class WelcomePage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly countries = inject(Countries);
  protected readonly i18n = inject(I18n);
  protected cvName = (c: { name: string; format?: string }): string => cvLabel(this.i18n, c.name, c.format);
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  protected readonly steps = STEPS;
  protected readonly groups = FIELD_GROUPS;
  protected readonly headings = ['welcome.cv.title', 'welcome.ai.title', 'welcome.found.title', 'welcome.jobs.title'];
  protected readonly expand = expandQueries;
  protected readonly titles = (q: string) => this.api.get<string[]>(`/suggest/titles?q=${encodeURIComponent(q)}`);
  protected readonly recSkills = signal<string[]>([]);
  protected readonly status = signal<Status | null>(null);
  protected readonly step = signal<StepNo>(1);

  // screen 1
  protected readonly cv = signal<{ name: string; parts: number; approved: boolean; rendererOk?: boolean; format?: Profile['cv_source_format'] } | null>(null);
  protected readonly cvBusy = signal(false);
  protected readonly cvError = signal('');
  protected readonly dragging = signal(false);

  // screen 2: the connection UI is <app-ai-connect>; only its latest state matters here
  protected readonly ai = signal<AiState>({ state: 'idle', msg: '' });
  private cfg: SearchConfig | null = null;

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
      options: [['asian', 'setup.eeo.asian'], ['black', 'setup.eeo.black'], ['white', 'setup.eeo.white'],
        ['middle_eastern', 'setup.eeo.middleEastern'], ['native', 'setup.eeo.native'],
        ['pacific', 'setup.eeo.pacific'], ['two_or_more', 'setup.eeo.twoOrMore']],
    },
    { key: 'eeo_hispanic', label: 'setup.eeo.hispanicQ', options: [['yes', 'common.yes'], ['no', 'common.no']] },
    { key: 'eeo_veteran', label: 'setup.eeo.veteran', options: [['not_veteran', 'setup.eeo.notVeteran'], ['veteran', 'setup.eeo.isVeteran']] },
    { key: 'eeo_disability', label: 'setup.eeo.disability', options: [['no', 'setup.eeo.noDisability'], ['yes', 'setup.eeo.yesDisability']] },
  ];
  /** The salary currency: the home country's, else the one the CV's country implies. */
  protected currency(): string {
    return this.countries.byIso(this.text('profile.home_country'))?.currency || this.infer()?.country.currency || '';
  }
  /** The currency as the label shows it: the code, plus its name ("EGP · الجنيه المصري") so a code alone is never the whole story. */
  protected curName(): string {
    return currencyLabel(this.i18n.lang(), this.currency());
  }

  // screen 4
  protected readonly roles = signal<string[]>([]);
  /** Places the user edited; null = still the saved ones, else the home country. */
  protected readonly placesEdited = signal<Place[] | null>(null);
  private readonly savedPlaces = signal<Place[]>([]);
  protected readonly modes = signal<WorkMode[]>(['remote', 'hybrid', 'onsite']);
  protected readonly track = signal<'tech' | 'general'>('general');
  protected readonly seniorities = ['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'executive'];
  protected readonly level = computed(() => this.list('filters.seniority'));
  protected readonly years = computed(() => {
    const y = this.vals()['answers.years_experience'];
    return typeof y === 'number' ? y : null;
  });
  /** The CV shows less than a year of experience (an internship, say): the level hint says so instead of "0 years". */
  protected readonly underYear = computed(() => this.infer()?.values['answers.years_experience']?.note === 'under_one_year');
  private readonly homePlace = computed<Place[]>(() => {
    const c = this.countries.byIso(String(this.vals()['profile.home_country'] ?? ''));
    return c ? [{ label: c.name, city: '', country: c.iso2, work: 'ask' }] : [];
  });
  protected readonly placesShown = computed(() => this.placesEdited() ?? (this.savedPlaces().length ? this.savedPlaces() : this.homePlace()));
  // computed: a new array on every check would make Angular think an input keeps changing
  protected readonly modeOptions = computed<ChipOption[]>(() => (['remote', 'hybrid', 'onsite'] as const).map((m) => ({ value: m, label: this.i18n.t(`mode.${m}`) })));
  protected readonly levelOptions = computed<ChipOption[]>(() => this.seniorities.map((s) => ({ value: s, label: this.i18n.t(`setup.seniority.${s}`), tip: levelTip(this.i18n, s) })));
  protected readonly trackOptions = computed<ChipOption[]>(() => [{ value: 'tech', label: this.i18n.t('welcome.jobs.tech') }, { value: 'general', label: this.i18n.t('welcome.jobs.general') }]);
  protected readonly trackSel = computed(() => [this.track()]);
  protected readonly sourceNames = computed(() => {
    const s = this.infer()?.sources;
    return s ? [...s.regional, ...s.jobspy] : [];
  });
  protected readonly starting = signal(false);
  protected readonly startError = signal('');
  // once the user (or a saved config) has set a list, a later CV re-read must not overwrite it
  /** What is already stored (non-empty only), when setup was done before; wins over CV guesses and is only re-sent when changed. */
  private saved: Record<string, unknown> = {};
  private rolesSet = false;
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
        return this.roles().length > 0 && this.placesShown().length > 0 && this.modes().length > 0;
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
        this.roles.set(cfg.search.queries);
        this.rolesSet = true;
      }
      if (status.setup.where) this.savedPlaces.set(cfg.search.places);
      this.modes.set(cfg.filters.work_modes);
      void this.countries.load();
      this.api.get<string[]>('/suggest/skills').then((l) => this.recSkills.set(l)).catch(() => {});
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
    for (const k of ['full_name', 'email', 'phone', 'home_city', 'home_country', 'skills'] as const) all[`profile.${k}`] = profile[k];
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

  /** The connection tested fine and was saved: the AI can now fill the CV gaps. */
  protected async aiConnected(): Promise<void> {
    this.status.set(await this.api.get<Status>('/status'));
    void this.fillAi();
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
    if (!this.rolesSet) this.roles.set(asList(next['search.queries']));
    if (!this.trackSet) this.track.set(next['track'] === 'tech' ? 'tech' : 'general');
  }

  /** First/last name and city follow the full name and home city unless the CV gave them. */
  private derive(v: Record<string, unknown>, force = false): void {
    const name = String(v['profile.full_name'] ?? '').trim();
    if (name && (force || !v['answers.first_name'])) {
      const [first, ...rest] = name.split(/\s+/);
      v['answers.first_name'] = first;
      v['answers.last_name'] = rest.join(' ');
    }
    const city = String(v['profile.home_city'] ?? '').trim();
    if (city && (force || !v['answers.city'])) v['answers.city'] = city;
  }

  private resetEdits(): void {
    this.vals.set({});
    this.touched.clear();
    this.rolesSet = this.trackSet = false;
    this.roles.set([]);
    this.placesEdited.set(null);
  }

  protected text(key: string): string {
    const v = this.vals()[key];
    return v === undefined || v === null ? '' : String(v);
  }

  protected list(key: string): string[] {
    return asList(this.vals()[key]);
  }

  protected set(key: string, value: unknown): void {
    this.touched.add(key);
    const next = { ...this.vals(), [key]: value };
    if (key === 'profile.full_name' || key === 'profile.home_city') this.derive(next, true);
    this.vals.set(next);
  }

  protected onField(f: Field, e: Event): void {
    const raw = (e.target as HTMLInputElement).value;
    this.set(f.key, f.kind === 'num' ? (raw.trim() === '' ? null : Math.max(0, Math.round(Number(raw)))) : raw);
  }

  /** A picked city sets city and country; a country sets country only; typed text keeps the country; cleared clears both. */
  protected setHome(p: PlacePick): void {
    const iso = p.label ? p.country || this.text('profile.home_country') : '';
    this.set('profile.home_country', iso);
    this.set('profile.home_city', p.city);
    const c = this.countries.byIso(iso);
    if (c) this.set('answers.country', c.name);
  }

  /** "City, Country" in the UI language: the country by its Arabic name and an Arabic comma when the UI is Arabic. */
  protected more = (n: number): string => this.i18n.plural('welcome.jobs.sourcesMore', n);

  protected homeText(): string {
    const iso = this.text('profile.home_country');
    const c = this.countries.byIso(iso);
    const city = this.text('profile.home_city');
    const ar = this.i18n.lang() === 'ar';
    return [(ar && this.arCity()[`${city}|${iso}`]) || city, c ? this.countries.name(c) : iso].filter(Boolean).join(ar ? '، ' : ', ');
  }

  /** The Arabic name of an English city ("Alexandria" -> "الإسكندرية"), looked up once; a city already written in Arabic needs none. */
  private readonly arCity = signal<Record<string, string>>({});
  private async loadArCity(city: string, iso: string): Promise<void> {
    const key = `${city}|${iso}`;
    if (key in this.arCity() || /[؀-ۿ]/.test(city)) return;
    this.arCity.update((m) => ({ ...m, [key]: '' }));
    const rows = await this.api.get<{ city: string; iso2: string; label_ar: string }[]>(`/suggest/places?q=${encodeURIComponent(city)}&lang=ar`).catch(() => []);
    const name = rows.find((r) => r.city === city && r.iso2 === iso)?.label_ar ?? '';
    this.arCity.update((m) => ({ ...m, [key]: name.split('،')[0].split(',')[0].trim() }));
  }

  constructor() {
    effect(() => {
      const city = this.text('profile.home_city');
      const iso = this.text('profile.home_country');
      if (this.i18n.lang() === 'ar' && city && iso) untracked(() => void this.loadArCity(city, iso));
    });
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

  protected setRoles(list: string[]): void {
    this.roles.set(list);
    this.rolesSet = true;
  }

  protected setModes(list: string[]): void {
    this.modes.set(list as WorkMode[]);
  }

  protected setTrack(t: string): void {
    this.track.set(t === 'tech' ? 'tech' : 'general');
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
        // profile and answers only: track, the search lists and the places are saved below; sensitive answers only when answered here;
        // location is derived from the home city and country, locked facts are protected by the server
        if (k === 'track' || k.startsWith('search.') || k.startsWith('filters.') || k === 'profile.location' || k === 'profile.locked_facts' || SENSITIVE.has(k) || v === undefined) continue;
        if (v === null && !(k in this.saved)) continue;
        if (changed(k, v)) values[k] = v;
      }
      for (const f of this.eeoFields) {
        const mode = this.eeoMode();
        const target = mode === 'decline' ? 'decline' : mode === 'now' ? this.eeo[f.key] || null : null;
        if (target !== ((this.saved[`answers.${f.key}`] as string | undefined) ?? null)) values[`answers.${f.key}`] = target;
      }
      const salary = this.salary.trim();
      if (salary !== String(this.saved['answers.salary_expectation'] ?? '')) values['answers.salary_expectation'] = salary;
      if (salary && !this.saved['answers.salary_currency'] && this.currency()) values['answers.salary_currency'] = this.currency();
      // the profile (home country) first: the places derive the work-permit answers from it
      await this.api.post('/infer/apply', { values, track: this.track() });
      const cfg = await this.api.get<SearchConfig>('/search');
      cfg.search.queries = this.roles();
      cfg.search.places = this.placesShown();
      cfg.filters.work_modes = this.modes();
      cfg.filters.seniority = this.level();
      const exclude = this.vals()['filters.title_exclude'];
      if (Array.isArray(exclude)) cfg.filters.title_exclude = asList(exclude);
      await this.api.put('/search', cfg);
      await this.api.post('/runs', { stages: ['discover', 'enrich', 'rank', 'score'] });
      await this.router.navigate(['/home']);
    } catch (e) {
      this.startError.set((e as Error).message);
    } finally {
      this.starting.set(false);
    }
  }
}

function asList(v: unknown): string[] {
  return Array.isArray(v) ? (v.every((x) => typeof x === 'string') ? (v as string[]) : v.map(String)) : [];
}
