import { Component, computed, effect, inject, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, localeOf } from '../locale';
import { AnswerEntry, AnswerValue, lines, unlines } from '../types';

type Filter = 'all' | 'ai' | 'user';

@Component({
  selector: 'app-answers',
  imports: [TPipe],
  template: `
    <h1>{{ 'answers.title' | t }}</h1>
    <p class="mt-1 max-w-3xl text-sm text-slate-500">{{ 'answers.intro' | t }}</p>

    <div class="mt-4 flex flex-wrap gap-2" role="group" [attr.aria-label]="'answers.filterLabel' | t">
      @for (f of filters; track f.id) {
        <button type="button" class="btn" [class.btn-primary]="filter() === f.id" [attr.aria-pressed]="filter() === f.id"
                (click)="filter.set(f.id)">{{ f.label | t }} ({{ num(count(f.id)) }})</button>
      }
    </div>

    @if (error(); as err) { <div class="alert alert-error mt-4 max-w-4xl" role="alert" dir="auto">{{ err }}</div> }

    <div class="mt-5 max-w-4xl space-y-4">
      @for (e of shown(); track e.id) {
        <section class="card" [attr.aria-label]="e.question">
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
              <textarea class="input" [rows]="isList(e.answer) ? 4 : 3" [id]="'a' + e.id" dir="auto" [value]="da()"
                        (input)="da.set(val($event))"></textarea>
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
        </section>
      } @empty {
        <div class="card text-center text-sm text-slate-500">
          {{ (!loaded() ? 'common.loading' : entries().length ? 'answers.empty.filter' : 'answers.empty.none') | t }}
        </div>
      }
    </div>
  `,
})
export class AnswersPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  private readonly i18n = inject(I18n);
  private readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly filters: { id: Filter; label: string }[] = [
    { id: 'all', label: 'answers.filter.all' },
    { id: 'ai', label: 'answers.filter.ai' },
    { id: 'user', label: 'answers.filter.user' },
  ];
  protected readonly entries = signal<AnswerEntry[]>([]);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly filter = signal<Filter>('all');
  protected readonly editing = signal<number | null>(null);
  protected readonly dq = signal('');
  protected readonly da = signal('');
  protected readonly dbool = signal(true);
  protected readonly shown = computed(() => this.entries().filter((e) => this.filter() === 'all' || e.source === this.filter()));

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
  }

  async load(): Promise<void> {
    try {
      this.entries.set(await this.api.get<AnswerEntry[]>('/answers'));
    } catch (e) {
      // keep what we have; the live socket triggers another load on reconnect
      console.error(e);
    } finally {
      this.loaded.set(true);
    }
  }

  count = (f: Filter): number => this.entries().filter((e) => f === 'all' || e.source === f).length;
  num = (n: number): string => fmtNum(this.loc(), n);
  val = (e: Event): string => (e.target as HTMLInputElement).value;
  when = (iso: string): string => new Date(iso).toLocaleString(this.loc());
  isBool = (v: AnswerValue): boolean => typeof v === 'boolean';
  isList = (v: AnswerValue): boolean => Array.isArray(v);

  show(v: AnswerValue): string {
    if (typeof v === 'boolean') return this.i18n.t(v ? 'common.yes' : 'common.no');
    return Array.isArray(v) ? v.join(', ') : v;
  }

  edit(e: AnswerEntry): void {
    this.error.set('');
    this.dq.set(e.question);
    this.dbool.set(e.answer === true);
    this.da.set(Array.isArray(e.answer) ? unlines(e.answer) : typeof e.answer === 'string' ? e.answer : '');
    this.editing.set(e.id);
  }

  async save(e: AnswerEntry): Promise<void> {
    const answer: AnswerValue = typeof e.answer === 'boolean' ? this.dbool() : Array.isArray(e.answer) ? lines(this.da()) : this.da();
    await this.run(async () => {
      await this.api.put(`/answers/${e.id}`, { question: this.dq(), answer });
      this.editing.set(null);
    });
  }

  async remove(e: AnswerEntry): Promise<void> {
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
