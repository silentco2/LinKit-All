import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { Api } from '../../api';
import { I18n, TPipe } from '../../i18n';
import { fmtNum, localeOf } from '../../locale';
import { AnswerEntry, AnswerValue, ApplicationAnswers, lines, unlines } from '../../types';
import { Field } from './saved';
import { SettingsStore } from './store';

const CHIP = 'inline-flex items-center gap-1 rounded-full border border-brand-500 bg-brand-50 py-0.5 ps-3 pe-1 text-sm font-medium text-brand-700 dark:bg-slate-800 dark:text-white';
type EeoKey = 'eeo_gender' | 'eeo_race' | 'eeo_hispanic' | 'eeo_veteran' | 'eeo_disability';
type EeoMode = 'ask' | 'decline' | 'now';
type Filter = 'all' | 'ai' | 'user';
type Choice = { v: boolean | null; label: string };

/** Settings > Answers: the sensitive and form answers, then the saved answers list. Everything saves as you edit. */
@Component({
  selector: 'app-settings-answers',
  imports: [Field, NgTemplateOutlet, TPipe],
  template: `
    <ng-template #choice let-k="k" let-opts="opts">
      <div class="flex flex-wrap gap-2" role="group">
        @for (o of opts; track o.label) {
          <button type="button" class="btn" [class.btn-primary]="pick(k) === o.v" [attr.aria-pressed]="pick(k) === o.v" (click)="store.update(k, o.v)">{{ o.label | t }}</button>
        }
      </div>
    </ng-template>

    <div class="space-y-6">
      <section class="card space-y-5">
        <h2>{{ 'setup.answers.sensitive' | t }}</h2>
        <p class="hint">{{ 'setup.answers.sensitiveHint' | t }}</p>

        <app-field key="answers.authorized_countries" for="auth-add" [label]="'setup.answers.auth' | t" [hint]="'setup.answers.authHint' | t">
          <div class="flex flex-wrap items-center gap-2" role="list">
            @for (c of store.answers.authorized_countries; track c) {
              <span role="listitem" [class]="chip">
                <bdi>{{ c }}</bdi>
                <button type="button" class="rounded-full px-1.5 hover:bg-brand-100 dark:hover:bg-slate-700" [attr.aria-label]="'settings.jobs.remove' | t: { name: c }" (click)="removeCountry(c)"><span aria-hidden="true">×</span></button>
              </span>
            }
          </div>
          <div class="mt-2 flex max-w-md gap-2">
            <input #countryIn id="auth-add" class="input" dir="auto" placeholder="Egypt" (keydown.enter)="addCountry(countryIn)" (change)="addCountry(countryIn)">
            <button type="button" class="btn" (click)="addCountry(countryIn)">{{ 'welcome.jobs.add' | t }}</button>
          </div>
        </app-field>

        <app-field key="answers.needs_sponsorship" [label]="'setup.answers.sponsor' | t" [hint]="'settings.ans.sponsorHint' | t">
          <ng-container [ngTemplateOutlet]="choice" [ngTemplateOutletContext]="{ k: 'answers.needs_sponsorship', opts: yesNo }" />
        </app-field>

        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="answers.salary_expectation" for="a-sal" [label]="'setup.answers.salary' | t" [hint]="'setup.answers.salaryHint' | t">
            <input id="a-sal" dir="ltr" class="input" placeholder="30000" [value]="store.answers.salary_expectation" (change)="store.update('answers.salary_expectation', val($event).trim())">
          </app-field>
          <app-field key="answers.salary_currency" for="a-cur" [label]="'setup.answers.currency' | t">
            <select id="a-cur" class="input" dir="ltr" (change)="store.update('answers.salary_currency', val($event))">
              <option value="" [selected]="!store.answers.salary_currency">—</option>
              @for (c of currencies(); track c) { <option [value]="c" [selected]="c === store.answers.salary_currency">{{ c }}</option> }
            </select>
          </app-field>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <app-field key="answers.notice_period" for="a-notice" [label]="'setup.answers.notice' | t">
            <select id="a-notice" class="input" (change)="store.update('answers.notice_period', val($event))">
              <option value="" [selected]="!store.answers.notice_period">{{ 'welcome.forms.ask' | t }}</option>
              @for (n of notices(); track n[0]) { <option [value]="n[0]" [selected]="n[0] === store.answers.notice_period">{{ n[1] | t }}</option> }
            </select>
          </app-field>
          <app-field key="answers.willing_to_relocate" [label]="'setup.answers.reloc' | t">
            <ng-container [ngTemplateOutlet]="choice" [ngTemplateOutletContext]="{ k: 'answers.willing_to_relocate', opts: yesNo }" />
          </app-field>
        </div>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.ans.demo' | t }}</h2>
        <app-field key="answers.eeo_gender" [label]="'welcome.forms.demo' | t" [hint]="'welcome.forms.demoHint' | t">
          <div class="flex flex-wrap gap-2" role="group">
            @for (m of eeoModes; track m.id) {
              <button type="button" class="btn" [class.btn-primary]="eeoMode() === m.id" [attr.aria-pressed]="eeoMode() === m.id" (click)="setEeo(m.id)">{{ m.label | t }}</button>
            }
          </div>
        </app-field>
        @if (eeoMode() === 'now') {
          <div class="grid gap-4 sm:grid-cols-2">
            @for (f of eeoFields; track f.key) {
              <app-field [key]="'answers.' + f.key" [for]="'e-' + f.key" [label]="f.label | t">
                <select [id]="'e-' + f.key" class="input" (change)="store.update('answers.' + f.key, val($event) || null)">
                  <option value="" [selected]="!store.answers[f.key]">{{ 'welcome.forms.ask' | t }}</option>
                  @for (o of f.options; track o[0]) { <option [value]="o[0]" [selected]="store.answers[f.key] === o[0]">{{ o[1] | t }}</option> }
                  <option value="decline" [selected]="store.answers[f.key] === 'decline'">{{ 'setup.eeo.decline' | t }}</option>
                </select>
              </app-field>
            }
          </div>
        }
      </section>

      <section class="card space-y-5">
        <h2>{{ 'setup.answers.ack' | t }}</h2>
        <app-field key="answers.acknowledge_privacy" [label]="'setup.answers.privacy' | t" [hint]="'setup.answers.privacyHint' | t">
          <ng-container [ngTemplateOutlet]="choice" [ngTemplateOutletContext]="{ k: 'answers.acknowledge_privacy', opts: agree }" />
        </app-field>
        <app-field key="answers.acknowledge_legal" [label]="'setup.answers.legal' | t" [hint]="'setup.answers.legalHint' | t">
          <ng-container [ngTemplateOutlet]="choice" [ngTemplateOutletContext]="{ k: 'answers.acknowledge_legal', opts: agree }" />
        </app-field>
      </section>

      <section class="card space-y-4">
        <h2>{{ 'settings.ans.saved' | t }}</h2>
        <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'answers.intro' | t }}</p>
        <div class="flex flex-wrap gap-2" role="group" [attr.aria-label]="'answers.filterLabel' | t">
          @for (f of filters; track f.id) {
            <button type="button" class="btn" [class.btn-primary]="filter() === f.id" [attr.aria-pressed]="filter() === f.id" (click)="filter.set(f.id)">{{ f.label | t }} ({{ num(count(f.id)) }})</button>
          }
        </div>
        @if (error(); as err) { <div class="alert alert-error" role="alert" dir="auto">{{ err }}</div> }

        <div class="space-y-3">
          @for (e of shownEntries(); track e.id) {
            <article class="rounded-lg border border-slate-200 p-4 dark:border-slate-700" [attr.aria-label]="e.question">
              @if (editing() === e.id) {
                <label class="label" [attr.for]="'q' + e.id">{{ 'answers.question' | t }}</label>
                <textarea class="input" rows="2" [id]="'q' + e.id" dir="auto" [value]="dq()" (input)="dq.set(val($event))"></textarea>
                <label class="label mt-3" [attr.for]="'a' + e.id">{{ 'answers.answer' | t }}</label>
                @if (isBool(e.answer)) {
                  <select class="input" [id]="'a' + e.id" (change)="dbool.set(val($event) === 'yes')">
                    <option value="yes" [selected]="dbool()">{{ 'common.yes' | t }}</option>
                    <option value="no" [selected]="!dbool()">{{ 'common.no' | t }}</option>
                  </select>
                } @else {
                  <textarea class="input" [rows]="isList(e.answer) ? 4 : 3" [id]="'a' + e.id" dir="auto" [value]="da()" (input)="da.set(val($event))"></textarea>
                  @if (isList(e.answer)) { <p class="hint">{{ 'answers.listHint' | t }}</p> }
                }
                <p class="hint">{{ 'answers.saveHint' | t }}</p>
                <div class="mt-3 flex gap-3">
                  <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="save(e)">{{ 'answers.save' | t }}</button>
                  <button type="button" class="btn" [disabled]="busy()" (click)="editing.set(null)">{{ 'answers.cancel' | t }}</button>
                </div>
              } @else {
                <header class="flex items-start justify-between gap-3">
                  <div class="min-w-0 font-semibold text-slate-900 dark:text-white" dir="auto">{{ e.question }}</div>
                  <div class="flex shrink-0 flex-wrap justify-end gap-1">
                    <span class="badge" [class]="e.source === 'user' ? 'tier-high' : 'alert-info'">{{ (e.source === 'user' ? 'answers.badge.you' : 'answers.badge.ai') | t }}</span>
                    @if (e.sensitive) { <span class="badge tier-mid">{{ 'answers.badge.sensitive' | t }}</span> }
                  </div>
                </header>
                <p class="mt-2 whitespace-pre-line break-words text-sm text-slate-700 dark:text-slate-300" dir="auto">{{ show(e.answer) }}</p>
                <footer class="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                  <span>{{ (e.uses === 1 ? 'answers.used.one' : 'answers.used.other') | t: { n: num(e.uses) } }}</span>
                  <span>{{ 'answers.updated' | t: { date: when(e.updated_at) } }}</span>
                  <span class="ms-auto flex gap-2">
                    <button type="button" class="btn" [disabled]="busy()" (click)="edit(e)">{{ 'answers.edit' | t }}</button>
                    <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="remove(e)">{{ 'answers.delete' | t }}</button>
                  </span>
                </footer>
              }
            </article>
          } @empty {
            <p class="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
              {{ (!loaded() ? 'common.loading' : entries().length ? 'answers.empty.filter' : 'answers.empty.none') | t }}
            </p>
          }
        </div>
      </section>
    </div>
  `,
})
export class AnswersSection implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  protected readonly chip = CHIP;
  protected readonly yesNo: Choice[] = [{ v: null, label: 'welcome.forms.ask' }, { v: true, label: 'common.yes' }, { v: false, label: 'common.no' }];
  protected readonly agree: Choice[] = [{ v: null, label: 'welcome.forms.askEach' }, { v: true, label: 'settings.ans.always' }];
  // the stored value is this English text (it is typed into English forms); the label is translated
  private readonly noticeOptions: [string, string][] = [
    ['Immediately', 'settings.ans.n.now'], ['2 weeks', 'settings.ans.n.2w'], ['1 month', 'settings.ans.n.1m'], ['2 months', 'settings.ans.n.2m'], ['3 months', 'settings.ans.n.3m'],
  ];
  private readonly allCurrencies = ['EGP', 'SAR', 'AED', 'QAR', 'KWD', 'BHD', 'OMR', 'JOD', 'USD', 'EUR', 'GBP'];
  protected readonly eeoModes: { id: EeoMode; label: string }[] = [
    { id: 'decline', label: 'welcome.forms.declineAll' },
    { id: 'ask', label: 'welcome.forms.askEach' },
    { id: 'now', label: 'welcome.forms.answerNow' },
  ];
  protected readonly eeoFields: { key: EeoKey; label: string; options: [string, string][] }[] = [
    { key: 'eeo_gender', label: 'setup.eeo.gender', options: [['male', 'setup.eeo.male'], ['female', 'setup.eeo.female'], ['non_binary', 'setup.eeo.nonBinary']] },
    {
      key: 'eeo_race',
      label: 'setup.eeo.race',
      options: [['asian', 'setup.eeo.asian'], ['black', 'setup.eeo.black'], ['hispanic', 'setup.eeo.hispanic'], ['white', 'setup.eeo.white'],
        ['middle_eastern', 'setup.eeo.middleEastern'], ['native', 'setup.eeo.native'], ['pacific', 'setup.eeo.pacific'], ['two_or_more', 'setup.eeo.twoOrMore']],
    },
    { key: 'eeo_hispanic', label: 'setup.eeo.hispanicQ', options: [['yes', 'common.yes'], ['no', 'common.no']] },
    { key: 'eeo_veteran', label: 'setup.eeo.veteran', options: [['not_veteran', 'setup.eeo.notVeteran'], ['veteran', 'setup.eeo.isVeteran']] },
    { key: 'eeo_disability', label: 'setup.eeo.disability', options: [['no', 'setup.eeo.noDisability'], ['yes', 'setup.eeo.yesDisability']] },
  ];
  protected readonly eeoMode = signal<EeoMode>('ask');

  // saved answers (the answer bank)
  protected readonly filters: { id: Filter; label: string }[] = [
    { id: 'all', label: 'answers.filter.all' },
    { id: 'ai', label: 'answers.filter.ai' },
    { id: 'user', label: 'answers.filter.user' },
  ];
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly entries = signal<AnswerEntry[]>([]);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly filter = signal<Filter>('all');
  protected readonly editing = signal<number | null>(null);
  protected readonly dq = signal('');
  protected readonly da = signal('');
  protected readonly dbool = signal(true);
  protected readonly shownEntries = computed(() => this.entries().filter((e) => this.filter() === 'all' || e.source === this.filter()));

  ngOnInit(): void {
    const v = this.eeoFields.map((f) => this.store.answers[f.key]);
    this.eeoMode.set(v.every((x) => x === 'decline') ? 'decline' : v.some((x) => x) ? 'now' : 'ask');
    void this.load();
  }

  protected val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  /** The value of a yes/no/ask setting; a missing one counts as "ask". */
  protected pick(key: string): boolean | null {
    return this.store.get(key) ?? null;
  }

  /** The labels for the notice-period select: the fixed options, plus an older free-text value if there is one. */
  protected notices(): [string, string][] {
    const cur = this.store.answers.notice_period;
    return !cur || this.noticeOptions.some((n) => n[0] === cur) ? this.noticeOptions : [[cur, cur], ...this.noticeOptions];
  }

  protected currencies(): string[] {
    const cur = this.store.answers.salary_currency;
    return !cur || this.allCurrencies.includes(cur) ? this.allCurrencies : [cur, ...this.allCurrencies];
  }

  // ---- authorized countries -----------------------------------------------------------------

  protected addCountry(box: HTMLInputElement): void {
    const v = box.value.trim();
    box.value = '';
    const cur = this.store.answers.authorized_countries;
    if (v && !cur.some((c) => c.toLowerCase() === v.toLowerCase())) this.store.update('answers.authorized_countries', [...cur, v]);
  }

  protected removeCountry(c: string): void {
    this.store.update('answers.authorized_countries', this.store.answers.authorized_countries.filter((x) => x !== c));
  }

  // ---- demographic questions: one row for all five -----------------------------------------------

  /** "Prefer not to say for all" writes five "decline"; "Ask me each time" clears them; "Answer now" only opens the selects. */
  protected setEeo(mode: EeoMode): void {
    this.eeoMode.set(mode);
    if (mode === 'now') return;
    const a = this.store.answers as ApplicationAnswers;
    for (const f of this.eeoFields) a[f.key] = mode === 'decline' ? 'decline' : null;
    const [first, ...rest] = this.eeoFields.map((f) => `answers.${f.key}`);
    this.store.touch(first, rest);
  }

  // ---- saved answers -----------------------------------------------------------------------------

  protected async load(): Promise<void> {
    try {
      this.entries.set(await this.api.get<AnswerEntry[]>('/answers'));
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.loaded.set(true);
    }
  }

  protected count = (f: Filter): number => this.entries().filter((e) => f === 'all' || e.source === f).length;
  protected num = (n: number): string => fmtNum(this.loc(), n);
  protected when = (iso: string): string => new Date(iso).toLocaleString(this.loc());
  protected isBool = (v: AnswerValue): boolean => typeof v === 'boolean';
  protected isList = (v: AnswerValue): boolean => Array.isArray(v);

  protected show(v: AnswerValue): string {
    if (typeof v === 'boolean') return this.i18n.t(v ? 'common.yes' : 'common.no');
    return Array.isArray(v) ? v.join(', ') : v;
  }

  protected edit(e: AnswerEntry): void {
    this.error.set('');
    this.dq.set(e.question);
    this.dbool.set(e.answer === true);
    this.da.set(Array.isArray(e.answer) ? unlines(e.answer) : typeof e.answer === 'string' ? e.answer : '');
    this.editing.set(e.id);
  }

  protected save(e: AnswerEntry): Promise<void> {
    const answer: AnswerValue = typeof e.answer === 'boolean' ? this.dbool() : Array.isArray(e.answer) ? lines(this.da()) : this.da();
    return this.run(async () => {
      await this.api.put(`/answers/${e.id}`, { question: this.dq(), answer });
      this.editing.set(null);
    });
  }

  protected async remove(e: AnswerEntry): Promise<void> {
    if (!confirm(this.i18n.t('answers.confirmDelete'))) return;
    await this.run(async () => {
      await this.api.delete(`/answers/${e.id}`);
      if (this.editing() === e.id) this.editing.set(null);
    });
  }

  private async run(fn: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await fn();
      await this.load();
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.busy.set(false);
    }
  }
}
