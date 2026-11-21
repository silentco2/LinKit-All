import { Component, computed, ElementRef, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { JobRow } from '../types';

/** `@word` filters, in both languages whatever the UI language; the first word of each language is the hint shown. */
const FILTERS: { en: string[]; ar: string[]; param: 'tier' | 'state'; value: string }[] = [
  { en: ['strong'], ar: ['قوي', 'قوية'], param: 'tier', value: 'high' },
  { en: ['possible'], ar: ['محتمل', 'محتملة'], param: 'tier', value: 'mid' },
  { en: ['weak'], ar: ['ضعيف', 'ضعيفة'], param: 'tier', value: 'low' },
  { en: ['needs'], ar: ['بانتظارك', 'متابعتك'], param: 'state', value: 'needs_user' },
  { en: ['applied'], ar: ['قدمت', 'تقديم'], param: 'state', value: 'applied' },
  { en: ['failed'], ar: ['فشلت', 'فشل'], param: 'state', value: 'failed' },
  { en: ['skipped'], ar: ['تخطيت', 'تخطي'], param: 'state', value: 'skipped' },
];
const PAGES: { path: string; label: string }[] = [
  { path: '/home', label: 'shell.nav.home' },
  { path: '/jobs', label: 'shell.nav.jobs' },
  { path: '/needs-you', label: 'shell.nav.needsYou' },
  ...['profile', 'jobs', 'sources', 'answers', 'applying', 'accounts', 'ai', 'advanced'].map((s) => ({ path: `/settings/${s}`, label: `settings.s.${s}` })),
];
const JOBS_SHOWN = 8;

interface Item { id: string; label: string; detail: string; go: () => void }

/** Ctrl/Cmd+K: jump to a job (title or company, `@strong`, `@applied`...) or to a page. Applied jobs are found too; the trash never. */
@Component({
  selector: 'app-quick-jump',
  imports: [TPipe],
  host: { '(document:keydown)': 'onKey($event)' },
  template: `
    <dialog #box class="m-auto mt-[12vh] w-[min(95vw,36rem)] rounded-xl bg-white p-0 text-slate-900 backdrop:bg-black/50 dark:bg-slate-900 dark:text-slate-100"
            [attr.aria-label]="'jump.label' | t" (close)="text.set('')" (click)="$event.target === box && box.close()">
      <div class="border-b border-slate-200 p-3 dark:border-slate-800">
        <input #field class="input" type="text" role="combobox" autocomplete="off" dir="auto" aria-controls="jump-list" aria-autocomplete="list"
               [attr.aria-expanded]="items().length > 0" [attr.aria-activedescendant]="items().length ? 'jump-' + active() : null"
               [attr.aria-label]="'jump.label' | t" [placeholder]="'jump.placeholder' | t"
               [value]="text()" (input)="type($any($event.target).value)" (keydown)="move($event)">
        <p class="hint mt-1.5" dir="auto">{{ 'jump.filters' | t }} @for (w of hints(); track w) { <bdi class="me-1.5">&#64;{{ w }}</bdi> }</p>
      </div>
      <ul id="jump-list" role="listbox" class="max-h-[50vh] overflow-auto p-1.5" [attr.aria-label]="'jump.label' | t">
        @for (it of items(); track it.id; let i = $index) {
          <li [id]="'jump-' + i" role="option" [attr.aria-selected]="i === active()" (mousemove)="active.set(i)" (click)="it.go()"
              class="cursor-pointer rounded-md px-3 py-2 text-sm" [class.is-picked]="i === active()">
            <bdi class="block truncate font-medium">{{ it.label }}</bdi>
            <bdi class="block truncate text-xs text-slate-500">{{ it.detail }}</bdi>
          </li>
        } @empty {
          <li class="px-3 py-6 text-center text-sm text-slate-500">{{ (loading() ? 'jump.searching' : 'jump.none') | t }}</li>
        }
      </ul>
    </dialog>
  `,
})
export class QuickJump {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  private readonly router = inject(Router);
  protected readonly box = viewChild.required<ElementRef<HTMLDialogElement>>('box');
  private readonly field = viewChild.required<ElementRef<HTMLInputElement>>('field');
  protected readonly text = signal('');
  protected readonly active = signal(0);
  protected readonly loading = signal(false);
  private readonly jobs = signal<JobRow[]>([]);
  private timer?: ReturnType<typeof setTimeout>;
  private asked = 0;

  protected readonly hints = computed(() => FILTERS.map((f) => (this.i18n.lang() === 'ar' ? f.ar[0] : f.en[0])));
  /** The words typed, split into `@` filters and the search text. */
  private readonly parsed = computed(() => parse(this.text()));
  protected readonly items = computed<Item[]>(() => {
    const { q, filters } = this.parsed();
    const words = q.toLowerCase();
    const pages = filters.length ? [] : PAGES.filter((p) => this.i18n.t(p.label).toLowerCase().includes(words) || p.path.includes(words));
    return [
      ...pages.map((p) => ({ id: p.path, label: this.i18n.t(p.label), detail: this.i18n.t('jump.page'), go: () => this.go(p.path) })),
      ...this.jobs().map((j) => ({
        id: `job${j.id}`,
        label: j.title,
        detail: [j.company, j.location, this.i18n.t('common.state.' + j.state)].filter(Boolean).join(' · '),
        go: () => this.go('/jobs', j.id),
      })),
    ];
  });

  open(): void {
    const box = this.box().nativeElement;
    if (!box.open) box.showModal();
    this.field().nativeElement.focus();
    this.type(this.text());
  }

  protected onKey(e: KeyboardEvent): void {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      this.open();
    }
  }

  protected type(value: string): void {
    this.text.set(value);
    this.active.set(0);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.search(), 150);
  }

  protected move(e: KeyboardEvent): void {
    const n = this.items().length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (n) this.active.set((this.active() + (e.key === 'ArrowDown' ? 1 : n - 1)) % n);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      this.items()[this.active()]?.go();
    }
  }

  private async search(): Promise<void> {
    const { q, filters } = this.parsed();
    if (!q && !filters.length) return this.jobs.set([]);
    const params = new URLSearchParams({ applied: 'true', limit: String(JOBS_SHOWN) });
    if (q) params.set('q', q);
    for (const f of filters) params.set(f.param, f.value);
    const mine = ++this.asked; // an older, slower answer never replaces a newer one
    this.loading.set(true);
    try {
      const rows = await this.api.get<JobRow[]>(`/jobs?${params}`);
      if (mine === this.asked) this.jobs.set(rows);
    } catch {
      if (mine === this.asked) this.jobs.set([]);
    } finally {
      if (mine === this.asked) this.loading.set(false);
    }
  }

  private go(path: string, job?: number): void {
    this.box().nativeElement.close();
    void this.router.navigate([path], job ? { queryParams: { job } } : {});
  }
}

/** "@strong backend" -> tier high + "backend". An `@` word matches any filter it starts (`@str`); unknown ones are dropped. */
export function parse(text: string): { q: string; filters: { param: 'tier' | 'state'; value: string }[] } {
  const filters: { param: 'tier' | 'state'; value: string }[] = [];
  const rest: string[] = [];
  for (const word of text.trim().split(/\s+/).filter(Boolean)) {
    if (!word.startsWith('@')) {
      rest.push(word);
      continue;
    }
    const w = word.slice(1).toLowerCase();
    const hit = w && FILTERS.find((f) => [...f.en, ...f.ar].some((a) => a.startsWith(w)));
    if (hit && !filters.some((f) => f.param === hit.param)) filters.push({ param: hit.param, value: hit.value });
  }
  return { q: rest.join(' '), filters };
}
