import { Component, effect, inject, signal } from '@angular/core';
import { Api } from '../api';
import { Live } from '../live';
import { ActionDecision, ActionItem, ActionKind, ActionQuestion, AnswerValue } from '../types';

const TITLES: Record<ActionKind, string> = {
  unknown_question: 'Needs your answer',
  confirm_submit: 'Confirm before submitting',
  captcha: 'CAPTCHA',
  validation_error: 'Form rejected the answers',
  login_issue: 'Sign-in problem',
  two_factor: 'Verification code needed',
};

const HELP: Partial<Record<ActionKind, string>> = {
  captcha: 'Solve the CAPTCHA yourself in the Chrome window that is still open, then press Retry.',
  validation_error: 'The site rejected the form. Fix it in the open Chrome window or apply by hand, then press Retry.',
  login_issue: 'Sign in to the site in the open Chrome window, then press Retry.',
  two_factor: 'Enter the verification code in the open Chrome window, then press Retry.',
};

const SOURCES: Record<string, string> = {
  profile: 'tier-high',
  sensitive: 'tier-mid',
  bank: 'tier-low',
  ai: 'alert-info',
  file: 'tier-low',
};

@Component({
  selector: 'app-actions',
  template: `
    <h1>Action Center</h1>
    <p class="mt-1 text-sm text-slate-500">Applications that stopped and need you. Resolve one in a single sitting and the job continues.</p>

    <div class="mt-5 max-w-4xl space-y-5">
      @for (a of items(); track a.id) {
        <section class="card" [attr.aria-label]="a.job.title">
          <header class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-lg font-semibold text-slate-900 dark:text-white" dir="auto">{{ a.job.title }}</div>
              <div class="truncate text-sm text-slate-500" dir="auto">{{ a.job.company }} · {{ a.job.location }}</div>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-1">
              <span class="badge tier-mid">{{ title(a.kind) }}</span>
              @if (a.job.score) { <span class="text-xs text-slate-500">Score {{ a.job.score }}/10</span> }
              <span class="text-xs text-slate-400">{{ when(a.created_at) }}</span>
            </div>
          </header>

          @if (a.message) { <p class="mt-3 text-sm text-slate-700 dark:text-slate-300">{{ a.message }}</p> }
          @if (help(a.kind); as h) { <div class="alert alert-info mt-3">{{ h }}</div> }

          @if (a.screenshots) {
            <div class="mt-4 flex flex-wrap gap-3">
              @for (n of range(a.screenshots); track n) {
                <a [href]="shot(a.id, n)" target="_blank" rel="noopener">
                  <img [src]="shot(a.id, n)" alt="Screenshot {{ n + 1 }} of the application form"
                       class="max-h-64 rounded-lg border border-slate-200 dark:border-slate-700">
                </a>
              }
            </div>
          }

          @if (a.kind === 'unknown_question') {
            <div class="alert alert-info mt-4">
              The form asked something we could not answer for you. Your answers are saved to the answer bank as
              yours, then the job is retried.
            </div>
            <div class="mt-4 space-y-5">
              @for (q of a.questions; track q.label; let i = $index) {
                <div>
                  <label class="label" [attr.for]="'q' + a.id + '-' + i" dir="auto">
                    {{ q.label }} @if (q.required) { <span class="text-rose-600" title="Required">*</span> }
                  </label>
                  @switch (widget(q)) {
                    @case ('textarea') {
                      <textarea class="input" rows="4" [id]="'q' + a.id + '-' + i" [value]="text(a.id, q.label)"
                                (input)="set(a.id, q.label, val($event))"></textarea>
                    }
                    @case ('multi') {
                      <div class="space-y-1" role="group" [attr.aria-label]="q.label">
                        @for (o of q.options; track o) {
                          <label class="flex items-center gap-2 text-sm">
                            <input type="checkbox" [checked]="isOn(a.id, q.label, o)" (change)="toggle(a.id, q.label, o)"> {{ o }}
                          </label>
                        }
                      </div>
                    }
                    @case ('radio') {
                      <div class="space-y-1" role="radiogroup" [attr.aria-label]="q.label">
                        @for (o of choices(q); track o) {
                          <label class="flex items-center gap-2 text-sm">
                            <input type="radio" [name]="'q' + a.id + '-' + i" [checked]="draft()[a.id]?.[q.label] === o"
                                   (change)="set(a.id, q.label, o)"> {{ o }}
                          </label>
                        }
                      </div>
                    }
                    @case ('checkbox') {
                      <!-- never pre-ticked: the user picks Yes or No explicitly -->
                      <select class="input" [id]="'q' + a.id + '-' + i" (change)="setBool(a.id, q.label, val($event))">
                        <option value="" [selected]="draft()[a.id]?.[q.label] === undefined">Choose…</option>
                        <option value="yes" [selected]="draft()[a.id]?.[q.label] === true">Yes</option>
                        <option value="no" [selected]="draft()[a.id]?.[q.label] === false">No</option>
                      </select>
                    }
                    @case ('select') {
                      <select class="input" [id]="'q' + a.id + '-' + i" (change)="set(a.id, q.label, val($event))">
                        <option value="" [selected]="!text(a.id, q.label)">Choose…</option>
                        @for (o of q.options; track o) { <option [value]="o" [selected]="text(a.id, q.label) === o">{{ o }}</option> }
                      </select>
                    }
                    @default {
                      <input class="input" [type]="inputType(q.kind)" [id]="'q' + a.id + '-' + i" [value]="text(a.id, q.label)"
                             (input)="set(a.id, q.label, val($event))">
                    }
                  }
                  @if (q.reason) { <p class="hint">{{ q.reason }}</p> }
                  @if (q.sensitive) {
                    <p class="hint !text-amber-700 dark:!text-amber-400">Sensitive: this was never sent to the AI. Your answer is stored locally.</p>
                  }
                </div>
              }
            </div>
            <div class="mt-4">
              <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="send(a, 'answer')">Save answers and retry</button>
            </div>
          }

          @if (a.kind === 'confirm_submit') {
            <h2 class="mt-5">What was filled in</h2>
            <table class="mt-2 w-full text-sm">
              <tbody>
                @for (row of entries(a); track row.label) {
                  <tr class="border-t border-slate-100 align-top dark:border-slate-800">
                    <th scope="row" class="w-2/5 py-2 pr-3 text-left font-medium text-slate-600 dark:text-slate-400" dir="auto">{{ row.label }}</th>
                    <td class="py-2 pr-3 break-words" dir="auto">{{ show(row.value) }}</td>
                    <td class="py-2 text-right"><span class="badge {{ sourceClass(row.source) }}">{{ row.source || 'unknown' }}</span></td>
                  </tr>
                } @empty {
                  <tr><td class="py-2 text-slate-500">No filled answers were recorded. Check the screenshot.</td></tr>
                }
              </tbody>
            </table>
            <div class="mt-4 flex flex-wrap gap-3">
              <button type="button" class="btn !border-emerald-700 !bg-emerald-600 !font-semibold !text-white hover:!bg-emerald-700"
                      [disabled]="busy()" (click)="send(a, 'confirm')">Submit application</button>
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="send(a, 'skip')">Skip</button>
            </div>
          }

          @if (errors()[a.id]; as err) { <div class="alert alert-error mt-4" role="alert">{{ err }}</div> }

          <footer class="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
            <button type="button" class="btn" [disabled]="busy()" (click)="send(a, 'retry')">Retry</button>
            <a class="btn no-underline hover:no-underline" [href]="a.job.apply_url" target="_blank" rel="noopener">Open application page</a>
            <button type="button" class="btn" [disabled]="busy()" (click)="send(a, 'applied_by_hand')">I applied by hand</button>
            @if (a.kind !== 'confirm_submit') {
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="send(a, 'skip')">Skip</button>
            }
          </footer>
        </section>
      } @empty {
        <div class="card text-center text-sm text-slate-500">{{ loaded() ? 'Nothing needs your attention.' : 'Loading…' }}</div>
      }
    </div>
  `,
})
export class ActionsPage {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  protected readonly items = signal<ActionItem[]>([]);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly errors = signal<Record<number, string>>({});
  /** Typed-in answers per action id, then question label. Survives reloads of the list. */
  protected readonly draft = signal<Record<number, Record<string, AnswerValue>>>({});

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
  }

  async load(): Promise<void> {
    try {
      this.items.set(await this.api.get<ActionItem[]>('/actions?status=open'));
    } catch (e) {
      // keep what we have; the live socket triggers another load on reconnect
      console.error(e);
    } finally {
      this.loaded.set(true);
    }
  }

  title = (k: ActionKind): string => TITLES[k] ?? k;
  help = (k: ActionKind): string => HELP[k] ?? '';
  range = (n: number): number[] => Array.from({ length: n }, (_, i) => i);
  shot = (id: number, n: number): string => `/api/actions/${id}/screenshot/${n}`;
  when = (iso: string): string => new Date(iso).toLocaleString();
  sourceClass = (s: string): string => SOURCES[s] ?? 'tier-low';
  val = (e: Event): string => (e.target as HTMLInputElement).value;
  /** Which control to draw: radios and yes/no -> radio, dropdowns with options -> select, the rest as typed. */
  widget(q: ActionQuestion): string {
    if (q.kind === 'radio' || q.kind === 'yesno') return 'radio';
    if (q.kind === 'select' || q.kind === 'combobox') return q.options.length ? 'select' : 'text';
    return q.kind === 'textarea' || q.kind === 'multi' || q.kind === 'checkbox' ? q.kind : 'text';
  }
  inputType = (kind: string): string => (['email', 'tel', 'number', 'url', 'date'].includes(kind) ? kind : 'text');
  choices = (q: ActionQuestion): string[] => (q.options.length ? q.options : q.kind === 'yesno' ? ['Yes', 'No'] : []);
  entries = (a: ActionItem) => Object.entries(a.answers).map(([label, v]) => ({ label, ...v }));

  show(v: unknown): string {
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    if (Array.isArray(v)) return v.join(', ');
    return v == null ? '' : String(v);
  }

  text(id: number, label: string): string {
    const v = this.draft()[id]?.[label];
    return typeof v === 'string' ? v : '';
  }

  set(id: number, label: string, value: AnswerValue): void {
    this.draft.update((d) => ({ ...d, [id]: { ...d[id], [label]: value } }));
  }

  setBool(id: number, label: string, v: string): void {
    this.draft.update((d) => {
      const { [label]: _drop, ...rest } = d[id] ?? {};
      return { ...d, [id]: v ? { ...rest, [label]: v === 'yes' } : rest };
    });
  }

  isOn(id: number, label: string, option: string): boolean {
    const v = this.draft()[id]?.[label];
    return Array.isArray(v) && v.includes(option);
  }

  toggle(id: number, label: string, option: string): void {
    const v = this.draft()[id]?.[label];
    const cur = Array.isArray(v) ? v : [];
    this.set(id, label, cur.includes(option) ? cur.filter((x) => x !== option) : [...cur, option]);
  }

  async send(a: ActionItem, decision: ActionDecision): Promise<void> {
    this.busy.set(true);
    this.errors.update(({ [a.id]: _drop, ...rest }) => rest);
    try {
      const answers = decision === 'answer' ? (this.draft()[a.id] ?? {}) : {};
      await this.api.post(`/actions/${a.id}`, { decision, answers });
      this.draft.update(({ [a.id]: _drop, ...rest }) => rest);
      // bumping `changed` reloads this list and the nav badge in the shell
      this.live.changed.update((n) => n + 1);
    } catch (e) {
      this.errors.update((m) => ({ ...m, [a.id]: e instanceof Error ? e.message : String(e) }));
    } finally {
      this.busy.set(false);
    }
  }
}
