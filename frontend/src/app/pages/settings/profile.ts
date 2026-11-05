import { NgTemplateOutlet } from '@angular/common';
import { Component, effect, inject, OnInit, signal, untracked } from '@angular/core';
import { Api } from '../../api';
import { Countries } from '../../components/countries';
import { LibreOfficeCard } from '../../components/libreoffice-card';
import { PhoneInput } from '../../components/phone-input';
import { PlacePick, PlacePicker } from '../../components/place-picker';
import { TagInput } from '../../components/tag-input';
import { I18n, TPipe } from '../../i18n';
import { cvLabel } from '../../locale';
import { ApplicationAnswers, Profile, Segment, splitName, Status } from '../../types';
import { Field } from './saved';
import { SettingsStore } from './store';

type Upload = { cv_name: string; segments: Segment[]; filled: string[]; cv_source_format: Profile['cv_source_format']; cv_approved: boolean; cv_renderer_ok: boolean };
/** One text box. `view`: shows the value with an Edit button (a "From your CV" badge while it still is the CV's value). */
type Row = { key: string; id: string; label: string; type?: string; dir?: 'ltr'; ac?: string; num?: boolean; view?: boolean };

/** Settings > Profile & CV. The CV upload is an action (not autosave); everything else saves as you leave the field. */
@Component({
  selector: 'app-settings-profile',
  imports: [Field, LibreOfficeCard, NgTemplateOutlet, TPipe, TagInput, PlacePicker, PhoneInput],
  template: `
    <div class="space-y-6">
      <section class="card space-y-4">
        <h2>{{ 'setup.cv.title' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'setup.cv.intro' | t }}</p>
        <div class="flex flex-wrap items-center gap-3">
          <label class="btn cursor-pointer focus-within:ring-2 focus-within:ring-brand-500">
            {{ (store.profile.cv_name ? 'setup.cv.replace' : 'setup.cv.upload') | t }}
            <input type="file" accept=".docx,.odt,.pdf,.tex,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.oasis.opendocument.text,application/pdf,application/x-tex,text/x-tex" class="sr-only" (change)="upload($event)">
          </label>
          @if (store.profile.cv_name) {
            <bdi class="text-sm">{{ cvName() }}</bdi>
            @if (store.profile.cv_renderer_ok ?? status()?.libreoffice) {
              <a class="btn" href="/api/profile/cv/pdf" target="_blank" rel="noopener">{{ 'setup.cv.preview' | t }}</a>
            }
          }
        </div>
        <div aria-live="polite">
          @if (note(); as m) { <div class="alert" dir="auto" [class.alert-ok]="m.ok" [class.alert-error]="!m.ok" role="status">{{ m.text }}</div> }
        </div>
        @if (store.profile.cv_name && store.profile.cv_approved === false) {
          <div class="alert alert-error" role="alert">
            <p><strong>{{ 'setup.cv.checkTitle' | t }}</strong> {{ 'setup.cv.checkBody' | t }}</p>
            <button type="button" class="btn btn-primary mt-3" (click)="approve()" [disabled]="busy()">{{ 'setup.cv.approve' | t }}</button>
          </div>
        }
        @if (store.profile.cv_source_format === 'tex') {
          @if (store.profile.cv_renderer_ok === false) {
            <div class="alert alert-warn">{{ 'setup.cv.tectonicA' | t }}<a href="https://tectonic-typesetting.github.io" target="_blank" rel="noopener">Tectonic</a>{{ 'setup.cv.tectonicB' | t }}</div>
          }
        } @else if (status() && !status()!.libreoffice) {
          <app-libreoffice-card />
        }
        @if (segments().length) {
          <details class="text-sm">
            <summary class="cursor-pointer font-medium">{{ i18n.plural('setup.cv.reads', segments().length) }}</summary>
            <ol class="mt-2 max-h-72 space-y-1 overflow-auto rounded-lg bg-slate-50 p-3 dark:bg-slate-950">
              @for (s of segments(); track s.id) { <li class="whitespace-pre-wrap" dir="auto"><span class="text-slate-400">{{ s.id }}</span> {{ s.text }}</li> }
            </ol>
          </details>
        }
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.profile.details' | t }}</h2>
        <app-field key="profile.full_name" for="p-name" [label]="'setup.profile.fullName' | t">
          <input id="p-name" class="input" type="text" dir="auto" autocomplete="name" [value]="v('profile.full_name') ?? ''" (change)="setName(val($event))">
        </app-field>
        <details class="text-sm">
          <summary class="cursor-pointer font-medium text-brand-700 dark:text-brand-300">{{ 'settings.profile.nameSplit' | t }}</summary>
          <p class="hint">{{ 'settings.profile.nameSplitHint' | t }}</p>
          <div class="mt-3 grid gap-4 sm:grid-cols-2">
            @for (f of split; track f.key) { <ng-container [ngTemplateOutlet]="plain" [ngTemplateOutletContext]="{ $implicit: f }" /> }
          </div>
        </details>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="profile.email" for="p-email" [label]="'setup.profile.email' | t">
            <input id="p-email" class="input" type="email" dir="ltr" autocomplete="email" [value]="v('profile.email') ?? ''" (change)="store.update('profile.email', val($event))">
          </app-field>
          <app-field key="profile.phone" for="p-phone" [label]="'setup.profile.phone' | t">
            <app-phone-input inputId="p-phone" [value]="v('profile.phone') ?? ''" [defaultIso]="v('profile.home_country') ?? ''" (changed)="store.update('profile.phone', $event)" />
          </app-field>
        </div>

        <h3 class="pt-2 text-base font-semibold text-slate-900 dark:text-white">{{ 'settings.profile.home' | t }}</h3>
        <app-field key="profile.address" for="p-address" [label]="'settings.profile.address' | t">
          <input id="p-address" class="input" type="text" dir="auto" autocomplete="street-address" [value]="v('profile.address') ?? ''" (change)="store.update('profile.address', val($event))">
        </app-field>
        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="profile.home_city" for="p-city" [label]="'settings.profile.cityCountry' | t">
            <app-place-picker inputId="p-city" [value]="homeText()" [placeholder]="'settings.profile.cityPh' | t" (picked)="setHome($event)" />
          </app-field>
          <app-field key="profile.postal_code" for="p-postal" [label]="'settings.profile.postal' | t">
            <input id="p-postal" class="input" type="text" dir="ltr" autocomplete="postal-code" [value]="v('profile.postal_code') ?? ''" (change)="store.update('profile.postal_code', val($event))">
          </app-field>
        </div>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.profile.work' | t }}</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          @for (f of work; track f.key) { <ng-container [ngTemplateOutlet]="plain" [ngTemplateOutletContext]="{ $implicit: f }" /> }
        </div>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.profile.links' | t }}</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          @for (f of links; track f.key) { <ng-container [ngTemplateOutlet]="plain" [ngTemplateOutletContext]="{ $implicit: f }" /> }
        </div>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.profile.skills' | t }}</h2>
        <app-field key="profile.skills" for="skills" [label]="'settings.profile.skills' | t">
          <app-tag-input inputId="skills" [values]="store.profile.skills" [placeholder]="'settings.profile.skillsPh' | t" [recommended]="recSkills()" [caption]="'settings.profile.skillsRec' | t"
                         (changed)="store.update('profile.skills', $event)" />
        </app-field>
      </section>
    </div>

    <ng-template #plain let-f>
      <app-field [key]="f.key" [for]="f.id" [label]="f.label | t">
        @if (viewing(f)) {
          <div class="flex items-center gap-2">
            <span class="min-w-0 flex-1 break-words py-2 text-sm" [attr.dir]="f.dir ?? 'auto'">{{ shown(f) }}</span>
            @if (fromCv(f)) { <span class="badge tier-low shrink-0">{{ 'settings.profile.fromCv' | t }}</span> }
            <button type="button" class="btn shrink-0" (click)="edit(f)">{{ 'settings.profile.edit' | t }}</button>
          </div>
        } @else {
          <input [id]="f.id" class="input" [type]="f.type ?? 'text'" [attr.dir]="f.dir ?? 'auto'" [attr.autocomplete]="f.ac" [attr.min]="f.num ? 0 : null" [attr.step]="f.num ? 1 : null"
                 [value]="v(f.key) ?? ''" [placeholder]="cvText(f)" (change)="store.update(f.key, f.num ? num(val($event)) : val($event))" (blur)="done(f)">
          @if (suggestion(f); as s) {
            <p class="hint flex flex-wrap items-center gap-x-2" dir="auto">
              <span>{{ 'settings.profile.cvHas' | t: { value: s } }}</span>
              <button type="button" class="font-medium text-brand-700 underline dark:text-brand-300" (click)="useIt(f)">{{ 'settings.profile.useIt' | t }}</button>
            </p>
          }
        }
      </app-field>
    </ng-template>
  `,
})
export class ProfileSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  protected readonly i18n = inject(I18n);
  protected cvName = (): string => cvLabel(this.i18n, this.store.profile.cv_name, this.store.profile.cv_source_format);
  private readonly countries = inject(Countries);
  protected readonly status = signal<Status | null>(null);
  protected readonly segments = signal<Segment[]>([]);
  protected readonly busy = signal(false);
  protected readonly note = signal<{ ok: boolean; text: string } | null>(null);
  /** What `/api/infer` read from the CV, by store key. */
  private readonly cv = signal<Record<string, { value: unknown }>>({});
  protected readonly recSkills = signal<string[]>([]);
  private readonly arNames = signal<Record<string, string>>({});
  private readonly editing = signal<ReadonlySet<string>>(new Set());
  /** Bumped when the store's plain objects change behind the template's back (a CV upload filled fields). */
  private readonly rev = signal(0);

  protected readonly split: Row[] = [
    { key: 'answers.first_name', id: 'a-first', label: 'setup.answers.first' },
    { key: 'answers.last_name', id: 'a-last', label: 'setup.answers.last' },
  ];
  protected readonly work: Row[] = [
    { key: 'answers.current_title', id: 'a-title', label: 'setup.answers.jobTitle', view: true },
    { key: 'answers.current_company', id: 'a-company', label: 'setup.answers.company', view: true },
    { key: 'answers.years_experience', id: 'a-years', label: 'setup.answers.years', type: 'number', num: true, view: true },
  ];
  protected readonly links: Row[] = [
    { key: 'answers.linkedin', id: 'a-linkedin', label: 'setup.answers.linkedin', type: 'url', dir: 'ltr' },
    { key: 'answers.github', id: 'a-github', label: 'setup.answers.github', type: 'url', dir: 'ltr' },
    { key: 'answers.portfolio', id: 'a-portfolio', label: 'setup.answers.portfolio', type: 'url', dir: 'ltr' },
  ];

  constructor() {
    // the stored home city is English; in Arabic look up its Arabic name once per city
    effect(() => {
      const lang = this.i18n.lang();
      this.rev();
      const { home_city: city, home_country: iso } = this.store.profile;
      if (lang === 'ar' && city && iso) untracked(() => void this.loadAr(city, iso));
    });
  }

  private async loadAr(city: string, iso: string): Promise<void> {
    const key = `${city}|${iso}`;
    if (key in this.arNames()) return;
    const rows = await this.api.get<{ city: string; iso2: string; label_ar: string }[]>(`/suggest/places?q=${encodeURIComponent(city)}&lang=ar`).catch(() => []);
    const hit = rows.find((r) => r.city === city && r.iso2 === iso);
    this.arNames.update((m) => ({ ...m, [key]: hit?.label_ar ?? '' }));
  }

  ngOnInit(): void {
    void this.countries.load();
    this.api.get<Status>('/status').then((s) => this.status.set(s)).catch(() => {});
    if (this.store.profile.cv_name) this.api.get<Segment[]>('/profile/cv/segments').then((s) => this.segments.set(s)).catch(() => {});
    void this.loadHints();
  }

  /** The CV's values (for "Use it") and the skills worth adding. Both are best effort: the page works without them. */
  private async loadHints(): Promise<void> {
    const [infer, skills] = await Promise.all([
      this.api.get<{ values: Record<string, { value: unknown }> }>('/infer').catch(() => null),
      this.api.get<string[]>('/suggest/skills').catch(() => null),
    ]);
    if (infer) this.cv.set(infer.values);
    if (skills) this.recSkills.set(skills);
  }

  protected val(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement).value;
  }

  /** An empty box means "not given" (null); anything else goes to the server as typed so it can say what is wrong. */
  protected num(v: string): number | null {
    return v.trim() === '' ? null : Number(v);
  }

  /** The stored value of a store key; reads `rev` so the template follows changes made outside events. */
  protected v(key: string): any { // eslint-disable-line @typescript-eslint/no-explicit-any
    this.rev();
    return this.store.get(key);
  }

  // ---- name, home ------------------------------------------------------------------------

  /** Save the name; first and last follow it unless the user wrote their own. */
  protected setName(full: string): void {
    const old = splitName(this.store.profile.full_name);
    const now = splitName(full);
    this.store.update('profile.full_name', full);
    const a = this.store.answers;
    if (!a.first_name || a.first_name === old.first) this.derive('answers.first_name', now.first);
    if (!a.last_name || a.last_name === old.last) this.derive('answers.last_name', now.last);
  }

  private derive(key: string, value: string): void {
    if (this.store.get(key) !== value) this.store.update(key, value);
  }

  protected homeText(): string {
    this.rev();
    const p = this.store.profile;
    const ar = this.i18n.lang() === 'ar' && p.home_city ? this.arNames()[`${p.home_city}|${p.home_country}`] : '';
    if (ar) return ar;
    const c = p.home_country ? this.countries.byIso(p.home_country) : undefined;
    const country = c ? this.countries.name(c) : p.home_country;
    return [p.home_city, country].filter(Boolean).join(this.i18n.lang() === 'ar' ? '، ' : ', ');
  }

  /** A picked city sets city and country; a country sets country only; typed text keeps the country; cleared clears both. */
  protected setHome(p: PlacePick): void {
    this.store.profile.home_country = p.label ? p.country || this.store.profile.home_country : '';
    this.store.profile.home_city = p.city;
    if (p.city && p.country && this.i18n.lang() === 'ar') this.arNames.update((m) => ({ ...m, [`${p.city}|${p.country}`]: p.label }));
    this.store.update('profile.home_city', p.city, ['profile.home_country']);
  }

  // ---- text boxes that can show the CV's value --------------------------------------------

  protected cvText(f: Row): string {
    const x = this.cv()[f.key]?.value;
    return x == null || Array.isArray(x) ? '' : String(x);
  }

  private has(f: Row): boolean {
    const x = this.v(f.key);
    return x != null && String(x).trim() !== '';
  }

  protected viewing(f: Row): boolean {
    return !!f.view && this.has(f) && !this.editing().has(f.key);
  }

  protected shown(f: Row): string {
    const x = this.v(f.key);
    return f.num ? this.i18n.plural('settings.profile.years', Number(x)) : String(x);
  }

  /** The stored value is still what was read from the CV. */
  protected fromCv(f: Row): boolean {
    const same = (a: unknown) => String(a).trim().toLowerCase();
    return this.has(f) && !!this.cvText(f) && same(this.v(f.key)) === same(this.cvText(f));
  }

  /** The CV's value, only while the box is empty. */
  protected suggestion(f: Row): string {
    return this.has(f) ? '' : this.cvText(f);
  }

  protected useIt(f: Row): void {
    this.store.update(f.key, f.num ? this.num(this.cvText(f)) : this.cvText(f));
  }

  protected edit(f: Row): void {
    this.editing.update((s) => new Set(s).add(f.key));
    setTimeout(() => document.getElementById(f.id)?.focus());
  }

  protected done(f: Row): void {
    if (this.editing().has(f.key)) this.editing.update((s) => new Set([...s].filter((k) => k !== f.key)));
  }

  // ---- the CV card -------------------------------------------------------------------------

  /** Run a CV action; `action` returns the (already translated) text to show. */
  private async run(action: () => Promise<string>): Promise<void> {
    this.busy.set(true);
    this.note.set(null);
    try {
      this.note.set({ ok: true, text: await action() });
      this.status.set(await this.api.get<Status>('/status'));
    } catch (e) {
      this.note.set({ ok: false, text: (e as Error).message });
    } finally {
      this.busy.set(false);
    }
  }

  /** The server filled empty fields from the CV: bring them into the page. */
  private async refresh(filled: string[]): Promise<string> {
    const [p, a] = await Promise.all([this.api.get<Profile>('/profile'), this.api.get<ApplicationAnswers>('/profile/answers')]);
    Object.assign(this.store.profile, p);
    Object.assign(this.store.answers, a);
    this.rev.update((n) => n + 1);
    void this.loadHints();
    return filled.length ? this.i18n.plural('setup.cv.filled', filled.length) : '';
  }

  private join(text: string, extra: string): string {
    return extra ? `${text}${/[.!؟]$/.test(text) ? '' : '.'} ${extra}` : text;
  }

  protected upload(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return Promise.resolve();
    return this.run(async () => {
      const r = await this.api.upload<Upload>('/profile/cv', file);
      input.value = ''; // the same file can be chosen again
      Object.assign(this.store.profile, { cv_name: r.cv_name, cv_renderer_ok: r.cv_renderer_ok, cv_source_format: r.cv_source_format, cv_approved: r.cv_approved });
      this.segments.set(r.segments);
      const text = this.i18n.plural(r.cv_approved ? 'setup.cv.uploaded' : 'setup.cv.converted', r.segments.length);
      return this.join(text, await this.refresh(r.filled ?? []));
    });
  }

  protected approve(): Promise<void> {
    return this.run(async () => {
      const p = await this.api.post<Profile & { filled?: string[] }>('/profile/cv/approve', {});
      Object.assign(this.store.profile, { cv_approved: p.cv_approved, cv_name: p.cv_name, cv_renderer_ok: p.cv_renderer_ok, cv_source_format: p.cv_source_format });
      return this.join(this.i18n.t('setup.cv.approved'), await this.refresh(p.filled ?? []));
    });
  }
}
