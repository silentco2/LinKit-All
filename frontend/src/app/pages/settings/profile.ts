import { Component, inject, OnInit, signal } from '@angular/core';
import { Api } from '../../api';
import { I18n, TPipe } from '../../i18n';
import { lines, Profile, Segment, Status, unlines } from '../../types';
import { Field } from './saved';
import { SettingsStore } from './store';

type Upload = { cv_name: string; segments: Segment[]; cv_source_format: Profile['cv_source_format']; cv_approved: boolean; cv_renderer_ok: boolean };
type Input = { key: string; id: string; label: string; type?: string; dir?: 'ltr'; ac?: string; hint?: string; num?: boolean };

/** Settings > Profile & CV. The CV upload is an action (not autosave); everything else saves as you leave the field. */
@Component({
  selector: 'app-settings-profile',
  imports: [Field, TPipe],
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
            <bdi class="text-sm">{{ store.profile.cv_name }}</bdi>
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

      <section class="card space-y-4">
        <h2>{{ 'settings.profile.details' | t }}</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          @for (f of basics; track f.key) {
            <app-field [key]="f.key" [for]="f.id" [label]="f.label | t">
              <input [id]="f.id" class="input" [type]="f.type ?? 'text'" [attr.dir]="f.dir ?? 'auto'" [attr.autocomplete]="f.ac" [value]="store.get(f.key) ?? ''" (change)="store.update(f.key, val($event))">
            </app-field>
          }
        </div>
        <app-field key="profile.skills" for="skills" [label]="'setup.profile.skills' | t" [hint]="'setup.profile.skillsHint' | t">
          <textarea id="skills" dir="auto" class="input h-28" [value]="unlines(store.profile.skills)" (change)="store.update('profile.skills', lines(val($event)))"></textarea>
        </app-field>
        <app-field key="profile.locked_facts" for="facts" [label]="'settings.profile.facts' | t" [hint]="'setup.profile.factsHint' | t">
          <textarea id="facts" dir="auto" class="input h-28" [value]="unlines(store.profile.locked_facts)" (change)="store.update('profile.locked_facts', lines(val($event)))"
                    placeholder="Acme Corp&#10;Senior Software Engineer&#10;B.Sc. Computer Science"></textarea>
        </app-field>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.profile.forms' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'settings.profile.formsHint' | t }}</p>
        <div class="grid gap-4 sm:grid-cols-2">
          @for (f of about; track f.key) {
            <app-field [key]="f.key" [for]="f.id" [label]="f.label | t" [hint]="f.hint ? (f.hint | t) : ''">
              <input [id]="f.id" class="input" [type]="f.type ?? 'text'" [attr.dir]="f.dir ?? 'auto'" [attr.min]="f.num ? 0 : null" [attr.step]="f.num ? 1 : null" [value]="store.get(f.key) ?? ''"
                     (change)="store.update(f.key, f.num ? num(val($event)) : val($event))">
            </app-field>
          }
        </div>
      </section>
    </div>
  `,
})
export class ProfileSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly lines = lines;
  protected readonly unlines = unlines;
  protected readonly status = signal<Status | null>(null);
  protected readonly segments = signal<Segment[]>([]);
  protected readonly busy = signal(false);
  protected readonly note = signal<{ ok: boolean; text: string } | null>(null);

  protected readonly basics: Input[] = [
    { key: 'profile.full_name', id: 'p-name', label: 'setup.profile.fullName', ac: 'name' },
    { key: 'profile.email', id: 'p-email', label: 'setup.profile.email', type: 'email', dir: 'ltr', ac: 'email' },
    { key: 'profile.phone', id: 'p-phone', label: 'setup.profile.phone', dir: 'ltr', ac: 'tel' },
    { key: 'profile.location', id: 'p-loc', label: 'setup.profile.location' },
  ];
  protected readonly about: Input[] = [
    { key: 'answers.first_name', id: 'a-first', label: 'setup.answers.first', hint: 'setup.answers.firstHint' },
    { key: 'answers.last_name', id: 'a-last', label: 'setup.answers.last' },
    { key: 'answers.city', id: 'a-city', label: 'setup.answers.city' },
    { key: 'answers.country', id: 'a-country', label: 'setup.answers.country' },
    { key: 'answers.current_company', id: 'a-company', label: 'setup.answers.company' },
    { key: 'answers.current_title', id: 'a-title', label: 'setup.answers.jobTitle' },
    { key: 'answers.linkedin', id: 'a-linkedin', label: 'setup.answers.linkedin', type: 'url', dir: 'ltr' },
    { key: 'answers.github', id: 'a-github', label: 'setup.answers.github', type: 'url', dir: 'ltr' },
    { key: 'answers.portfolio', id: 'a-portfolio', label: 'setup.answers.portfolio', type: 'url', dir: 'ltr' },
    { key: 'answers.years_experience', id: 'a-years', label: 'setup.answers.years', type: 'number', num: true },
  ];

  async ngOnInit(): Promise<void> {
    this.api.get<Status>('/status').then((s) => this.status.set(s)).catch(() => {});
    if (this.store.profile.cv_name) this.api.get<Segment[]>('/profile/cv/segments').then((s) => this.segments.set(s)).catch(() => {});
  }

  protected val(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement).value;
  }

  /** An empty box means "not given" (null); anything else goes to the server as typed so it can say what is wrong. */
  protected num(v: string): number | null {
    return v.trim() === '' ? null : Number(v);
  }

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

  protected upload(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return Promise.resolve();
    return this.run(async () => {
      const r = await this.api.upload<Upload>('/profile/cv', file);
      input.value = ''; // the same file can be chosen again
      Object.assign(this.store.profile, { cv_name: r.cv_name, cv_renderer_ok: r.cv_renderer_ok, cv_source_format: r.cv_source_format, cv_approved: r.cv_approved });
      this.segments.set(r.segments);
      return this.i18n.t(r.cv_approved ? 'setup.cv.uploaded' : 'setup.cv.converted', { n: r.segments.length });
    });
  }

  protected approve(): Promise<void> {
    return this.run(async () => {
      const p = await this.api.post<Profile>('/profile/cv/approve', {});
      Object.assign(this.store.profile, { cv_approved: p.cv_approved, cv_name: p.cv_name, cv_renderer_ok: p.cv_renderer_ok, cv_source_format: p.cv_source_format });
      return this.i18n.t('setup.cv.approved');
    });
  }
}
