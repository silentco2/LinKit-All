import { Component, inject, input, output, signal } from '@angular/core';
import { I18n, TPipe } from '../i18n';
import { Combo, ComboOption } from './combo';

const SEPARATORS = /[,،\n]/;
const DEBOUNCE_MS = 150;

/**
 * The one list-of-words box: chips above a text box. Enter, a comma or "Add" adds; x removes; Backspace in an empty box
 * marks the last chip and a second Backspace removes it (announced); a word already there (any case) is ignored. `(changed)` emits the whole new list.
 * - `suggest`: `(q) => Promise<string[]>` fills a dropdown while typing.
 * - `recommended` + `caption`: "+ chip" buttons that add on tap (never added by themselves).
 * - `split`: turns what was typed into the words to keep, e.g. `expandQueries` for roles ("React/Vue Developer").
 * `<app-tag-input inputId="skills" [values]="skills" [recommended]="rec" (changed)="save($event)" />`
 */
@Component({
  selector: 'app-tag-input',
  imports: [Combo, TPipe],
  host: { class: 'block' },
  template: `
    <div class="space-y-2">
      @if (values().length) {
        <ul class="flex flex-wrap gap-2" [attr.aria-label]="ariaLabel() || null">
          @for (v of values(); track v) {
            <li class="inline-flex items-center gap-1 rounded-md border border-brand-500 bg-brand-50 py-0.5 ps-3 pe-1 text-sm max-sm:min-h-10 text-brand-700 dark:bg-slate-800 dark:text-white"
                [class.ring-2]="v === marked()" [class.ring-rose-500]="v === marked()" [class.!bg-rose-50]="v === marked()">
              <bdi>{{ v }}</bdi>
              <button type="button" class="rounded-md px-1.5 leading-none text-brand-700 max-sm:min-h-10 max-sm:min-w-10 hover:bg-brand-100 dark:text-slate-300 dark:hover:bg-slate-700"
                      [attr.aria-label]="'tags.remove' | t: { name: v }" (click)="remove(v)"><span aria-hidden="true">×</span></button>
            </li>
          }
        </ul>
      }
      <div class="flex gap-2">
        <app-combo class="min-w-0 flex-1" [inputId]="inputId()" [(value)]="draft" [options]="options()" [placeholder]="placeholder()" [label]="ariaLabel()" [dir]="dir()"
                   (valueChange)="typed($event)" (picked)="add($event.label)" (submitted)="add(draft())" (blurred)="add(draft())" (backspaceEmpty)="removeLast()" />
        <button type="button" class="btn" (click)="add(draft())">{{ 'tags.add' | t }}</button>
      </div>
      @if (left().length) {
        <div>
          @if (caption()) { <p class="hint !mt-0 mb-1.5">{{ caption() }}</p> }
          <ul class="flex flex-wrap gap-2">
            @for (r of left(); track r) {
              <li><button type="button" class="rounded-md border border-dashed border-slate-300 px-3 py-0.5 text-sm max-sm:min-h-10 text-slate-600 hover:border-brand-500 hover:text-brand-700 dark:border-slate-600 dark:text-slate-300 dark:hover:text-white" (click)="add(r)"><span aria-hidden="true">+ </span><bdi>{{ r }}</bdi></button></li>
            }
          </ul>
        </div>
      }
      <p class="sr-only" role="status" aria-live="polite">{{ note() }}</p>
    </div>
  `,
})
export class TagInput {
  private readonly i18n = inject(I18n);
  readonly values = input<string[]>([]);
  readonly inputId = input('');
  readonly placeholder = input('');
  readonly ariaLabel = input('');
  readonly dir = input<'auto' | 'ltr'>('auto');
  readonly suggest = input<((q: string) => Promise<string[]>) | null>(null);
  readonly recommended = input<string[]>([]);
  readonly caption = input('');
  readonly split = input<((words: string[]) => string[]) | null>(null);
  readonly changed = output<string[]>();

  protected readonly draft = signal('');
  /** The chip a first Backspace marked; a second one removes it. */
  protected readonly marked = signal('');
  protected readonly note = signal('');
  protected readonly options = signal<ComboOption[]>([]);
  private timer?: ReturnType<typeof setTimeout>;
  private seq = 0;

  protected left(): string[] {
    const have = new Set(this.values().map((v) => v.toLowerCase()));
    return this.recommended().filter((r) => !have.has(r.toLowerCase()));
  }

  protected typed(text: string): void {
    this.marked.set('');
    if (SEPARATORS.test(text)) return this.add(text);
    clearTimeout(this.timer);
    const fn = this.suggest();
    const mine = ++this.seq;
    if (!fn || !text.trim()) return this.options.set([]);
    this.timer = setTimeout(async () => {
      const found = await fn(text.trim()).catch(() => [] as string[]);
      if (mine !== this.seq) return; // a newer keystroke asked again
      const have = new Set(this.values().map((v) => v.toLowerCase()));
      this.options.set(found.filter((s) => !have.has(s.toLowerCase())).map((s) => ({ key: s, label: s })));
    }, DEBOUNCE_MS);
  }

  protected add(text: string): void {
    this.marked.set('');
    this.seq++;
    this.options.set([]);
    this.draft.set('');
    const words = text.split(SEPARATORS).map((s) => s.trim()).filter(Boolean);
    const out = [...this.values()];
    const seen = new Set(out.map((v) => v.toLowerCase()));
    for (const w of this.split()?.(words) ?? words) {
      if (!seen.has(w.toLowerCase())) { seen.add(w.toLowerCase()); out.push(w); }
    }
    if (out.length !== this.values().length) this.changed.emit(out);
  }

  protected remove(v: string): void {
    this.marked.set('');
    this.changed.emit(this.values().filter((x) => x !== v));
  }

  /** Backspace in the empty box: the first press marks the last chip, the second removes it. */
  protected removeLast(): void {
    const last = this.values().at(-1);
    if (last === undefined) return;
    if (this.marked() !== last) {
      this.marked.set(last);
      this.note.set(this.i18n.t('tags.removeAsk', { name: last }));
      return;
    }
    this.note.set(this.i18n.t('tags.removed', { name: last }));
    this.remove(last);
  }
}
