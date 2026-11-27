import { Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { apiFetch, apiSrc } from '../net';
import { Profile } from '../types';

export interface SheetRow { label: string; value: string }

/** Profile facts worth copying into any form; the sensitive answers stay out (CLAUDE.md §2). */
const PROFILE: (keyof Profile)[] = ['full_name', 'email', 'phone', 'location', 'address', 'postal_code'];
const ANSWERS = ['linkedin', 'github', 'portfolio', 'current_title', 'current_company', 'years_experience', 'notice_period'];

/**
 * "Apply on this phone" (docs/phone.md): open the application link, copy each answer with one tap, share the CV PDF.
 * The phone fills nothing in itself: the user pastes into the employer's form.
 */
@Component({
  selector: 'app-answer-sheet',
  imports: [TPipe],
  template: `
    <div class="mt-4 space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-700">
      <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'sheet.intro' | t }}</p>
      <div class="flex flex-wrap gap-3">
        <a class="btn btn-go" [href]="url()" target="_blank" rel="noopener">{{ 'sheet.open' | t }}</a>
        <button type="button" class="btn" [disabled]="sharing()" (click)="shareCv()">{{ 'sheet.cv' | t }}</button>
      </div>
      @if (cvError()) { <div class="alert alert-error" role="alert">{{ 'sheet.cvMissing' | t }}</div> }
      <ul class="divide-y divide-slate-100 dark:divide-slate-800">
        @for (row of rows(); track row.label) {
          <li class="flex items-center gap-3 py-2">
            <div class="min-w-0 flex-1">
              <div class="text-xs text-slate-500" dir="auto">{{ row.label }}</div>
              <div class="break-words text-sm" dir="auto">{{ row.value }}</div>
            </div>
            <button type="button" class="btn min-h-10 shrink-0" (click)="copy(row)" [attr.aria-label]="('sheet.copy' | t) + ': ' + row.label">
              {{ (copied() === row.label ? 'sheet.copied' : 'sheet.copy') | t }}
            </button>
          </li>
        } @empty {
          <li class="py-2 text-sm text-slate-500">{{ 'common.loading' | t }}</li>
        }
      </ul>
    </div>
  `,
})
export class AnswerSheet implements OnInit {
  private readonly api = inject(Api);
  private readonly i18n = inject(I18n);
  /** The application page. */
  readonly url = input.required<string>();
  /** CV PDFs to try in order (the tailored one first). */
  readonly cvs = input.required<string[]>();
  /** What the app filled for this job so far. */
  readonly filled = input<SheetRow[]>([]);
  readonly title = input('');
  private readonly basics = signal<SheetRow[]>([]);
  protected readonly rows = computed(() => {
    const seen = new Set(this.filled().map((r) => r.value));
    return [...this.filled(), ...this.basics().filter((r) => !seen.has(r.value))].filter((r) => r.value);
  });
  protected readonly copied = signal('');
  protected readonly sharing = signal(false);
  protected readonly cvError = signal(false);

  async ngOnInit(): Promise<void> {
    try {
      const [p, a] = await Promise.all([this.api.get<Profile>('/profile'), this.api.get<Record<string, unknown>>('/profile/answers')]);
      const t = (k: string) => this.i18n.t('sheet.f.' + k);
      this.basics.set([
        ...PROFILE.map((k) => ({ label: t(k), value: String(p[k] ?? '') })),
        ...ANSWERS.map((k) => ({ label: t(k), value: a[k] == null ? '' : String(a[k]) })),
      ]);
    } catch {
      // the filled answers still show
    }
  }

  protected async copy(row: SheetRow): Promise<void> {
    try {
      await navigator.clipboard.writeText(row.value);
      this.copied.set(row.label);
    } catch {
      this.copied.set('');
    }
  }

  /** Web Share with the PDF itself (Android, iOS); where files cannot be shared, open the PDF instead. */
  protected async shareCv(): Promise<void> {
    this.sharing.set(true);
    this.cvError.set(false);
    try {
      for (const src of this.cvs()) {
        const res = await apiFetch(src);
        if (!res.ok) continue;
        const file = new File([await res.blob()], 'CV.pdf', { type: 'application/pdf' });
        if (navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file], title: this.title() });
        else window.open(await apiSrc(src), '_blank', 'noopener');
        return;
      }
      this.cvError.set(true);
    } catch {
      // the user closed the share sheet
    } finally {
      this.sharing.set(false);
    }
  }
}
