import { Component, computed, effect, inject, signal } from '@angular/core';
import { Api } from '../api';
import { Live } from '../live';
import { AnswerEntry, AnswerValue, lines, unlines } from '../types';

type Filter = 'all' | 'ai' | 'user';

@Component({
  selector: 'app-answers',
  template: `
    <h1>Answer bank</h1>
    <p class="mt-1 max-w-3xl text-sm text-slate-500">
      Answers to screening questions, reused on later applications. AI drafts are used automatically for
      non-sensitive questions; sensitive questions only ever use answers you wrote.
    </p>

    <div class="mt-4 flex flex-wrap gap-2" role="group" aria-label="Filter answers">
      @for (f of filters; track f.id) {
        <button type="button" class="btn" [class.btn-primary]="filter() === f.id" [attr.aria-pressed]="filter() === f.id"
                (click)="filter.set(f.id)">{{ f.label }} ({{ count(f.id) }})</button>
      }
    </div>

    @if (error(); as err) { <div class="alert alert-error mt-4 max-w-4xl" role="alert">{{ err }}</div> }

    <div class="mt-5 max-w-4xl space-y-4">
      @for (e of shown(); track e.id) {
        <section class="card" [attr.aria-label]="e.question">
          @if (editing() === e.id) {
            <label class="label" [attr.for]="'q' + e.id">Question</label>
            <textarea class="input" rows="2" [id]="'q' + e.id" dir="auto" [value]="dq()" (input)="dq.set(val($event))"></textarea>

            <label class="label mt-3" [attr.for]="'a' + e.id">Answer</label>
            @if (isBool(e.answer)) {
              <select class="input" [id]="'a' + e.id" (change)="dbool.set(val($event) === 'yes')">
                <option value="yes" [selected]="dbool()">Yes</option>
                <option value="no" [selected]="!dbool()">No</option>
              </select>
            } @else {
              <textarea class="input" [rows]="isList(e.answer) ? 4 : 3" [id]="'a' + e.id" dir="auto" [value]="da()"
                        (input)="da.set(val($event))"></textarea>
              @if (isList(e.answer)) { <p class="hint">One answer per line.</p> }
            }
            <p class="hint">Saving makes this your answer, even if the AI drafted it.</p>
            <div class="mt-3 flex gap-3">
              <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="save(e)">Save</button>
              <button type="button" class="btn" [disabled]="busy()" (click)="editing.set(null)">Cancel</button>
            </div>
          } @else {
            <header class="flex items-start justify-between gap-3">
              <div class="min-w-0 font-semibold text-slate-900 dark:text-white" dir="auto">{{ e.question }}</div>
              <div class="flex shrink-0 flex-wrap justify-end gap-1">
                <span class="badge" [class]="e.source === 'user' ? 'tier-high' : 'alert-info'">{{ e.source === 'user' ? 'You' : 'AI draft' }}</span>
                @if (e.sensitive) { <span class="badge tier-mid">Sensitive</span> }
              </div>
            </header>
            <p class="mt-2 whitespace-pre-line break-words text-sm text-slate-700 dark:text-slate-300" dir="auto">{{ show(e.answer) }}</p>
            <footer class="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span>Used {{ e.uses }} {{ e.uses === 1 ? 'time' : 'times' }}</span>
              <span>Updated {{ when(e.updated_at) }}</span>
              <span class="ml-auto flex gap-2">
                <button type="button" class="btn" [disabled]="busy()" (click)="edit(e)">Edit</button>
                <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="remove(e)">Delete</button>
              </span>
            </footer>
          }
        </section>
      } @empty {
        <div class="card text-center text-sm text-slate-500">
          {{ !loaded() ? 'Loading…' : entries().length ? 'No answers match this filter.' : 'No saved answers yet. They appear here as applications ask screening questions.' }}
        </div>
      }
    </div>
  `,
})
export class AnswersPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  protected readonly filters: { id: Filter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'ai', label: 'AI drafts' },
    { id: 'user', label: 'Yours' },
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
  val = (e: Event): string => (e.target as HTMLInputElement).value;
  when = (iso: string): string => new Date(iso).toLocaleString();
  isBool = (v: AnswerValue): boolean => typeof v === 'boolean';
  isList = (v: AnswerValue): boolean => Array.isArray(v);

  show(v: AnswerValue): string {
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
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
    if (!confirm('Delete this saved answer? It will be asked again next time.')) return;
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
