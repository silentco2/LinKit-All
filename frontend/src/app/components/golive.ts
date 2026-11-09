import { Component, effect, ElementRef, inject, OnInit, output, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api';
import { I18n, TPipe } from '../i18n';
import { SettingsStore } from '../pages/settings/store';
import { Shell } from '../shell';
import { GoLive, JobDetail, SearchConfig, Tailoring } from '../types';
import { LibreOffice, LibreOfficeCard } from './libreoffice-card';
import { PatchDiff } from './patch-diff';
import { Privacy } from './privacy';

/** One checklist line as the user sees it: its real state, its words and the page that fixes it. */
interface Row {
  id: string;
  state: 'ok' | 'todo' | 'undecided';
  label: string;
  link: string;
  query?: Record<string, string>;
}

/**
 * "Ready to apply for real?" (ux-plan 8.2): filled-form screenshots from practice runs, a checklist of real states, and
 * the one button that turns real applications on after a final confirm that names the action. Used on Home and in
 * Settings > Applying.
 */
@Component({
  selector: 'app-golive',
  imports: [LibreOfficeCard, PatchDiff, Privacy, RouterLink, TPipe],
  template: `
    @if (error()) { <div class="alert alert-error mb-3" role="alert" dir="auto">{{ error() }}</div> }
    @if (data(); as d) {
      @if (on()) {
        <div class="alert alert-ok" role="status">{{ 'golive.on' | t }}</div>
      } @else if (!d.eligible) {
        <div class="alert alert-info" role="status">{{ 'golive.notEligible' | t }}</div>
        <div class="mt-3"><button type="button" class="btn" (click)="cancel.emit()">{{ 'golive.notNow' | t }}</button></div>
      } @else {
        <div class="space-y-4">
          <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'golive.intro' | t }}</p>
          <ul class="grid gap-3 sm:grid-cols-3">
            @for (s of d.samples; track s.job_id) {
              <li class="min-w-0 text-sm">
                @if (s.screenshots[0]; as shot) {
                  <button type="button" class="block w-full rounded-lg text-start" [attr.aria-label]="('golive.open' | t) + ': ' + s.title" (click)="zoom(shot, s.title)">
                    <img [src]="shot" [alt]="s.title" loading="lazy" class="h-32 w-full rounded-lg border border-slate-200 object-cover object-top dark:border-slate-700">
                  </button>
                }
                <p class="mt-1 truncate font-medium" dir="auto">{{ s.title }}</p>
                <p class="truncate text-xs text-slate-500" dir="auto">{{ s.company }}</p>
                @if (s.tailored) { <span class="badge tier-high mt-1">{{ 'golive.tailored' | t }}</span> }
              </li>
            }
          </ul>
          <section class="space-y-2" aria-labelledby="golive-diff-title">
            <h3 id="golive-diff-title" class="text-sm font-semibold">{{ 'golive.diff.title' | t }}</h3>
            @if (d.tailored_example; as ex) {
              <p class="text-xs text-slate-500" dir="auto">{{ 'golive.diff.job' | t: { title: ex.title, company: ex.company } }}</p>
              @if (diffError()) {
                <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'golive.diff.error' | t }}</p>
              } @else if (diff(); as tl) {
                @if (!tl.patches.length) { <p class="text-sm text-slate-600 dark:text-slate-400">{{ 'detail.tailor.unchanged' | t }}</p> }
                <ul class="space-y-2">
                  @for (p of shownPatches(tl); track $index) { <li><app-patch-diff [patch]="p" /></li> }
                </ul>
                @if (tl.patches.length > PREVIEW && !allPatches()) {
                  <button type="button" class="btn" (click)="allPatches.set(true)">{{ 'golive.diff.all' | t }}</button>
                }
              } @else {
                <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
              }
              <p class="text-sm"><a [routerLink]="['/jobs']" [queryParams]="{ job: ex.job_id }">{{ 'golive.seeTailored' | t }}</a></p>
            } @else {
              <p class="text-sm text-slate-600 dark:text-slate-400">{{ (tailoring(d).mode === 'original' ? 'golive.diff.original' : 'golive.diff.none') | t }}</p>
            }
          </section>

          <ul class="space-y-1.5 text-sm" [attr.aria-label]="'golive.checklist' | t">
            @for (r of rows(d); track r.id) {
              <li class="flex flex-wrap items-center gap-x-2">
                @switch (r.state) {
                  @case ('ok') {
                    <span class="font-bold text-emerald-600 dark:text-emerald-400" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 13l4 4L19 7" /></svg></span><span class="sr-only">{{ 'golive.done' | t }}:</span>
                  }
                  @case ('undecided') {
                    <span class="font-bold text-amber-600 dark:text-amber-400" aria-hidden="true">?</span><span class="sr-only">{{ 'golive.undecided' | t }}:</span>
                  }
                  @default {
                    <span class="font-bold text-rose-600 dark:text-rose-400" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg></span><span class="sr-only">{{ 'golive.todo' | t }}:</span>
                  }
                }
                <span>{{ r.label }}</span>
                @if (r.state === 'undecided') { <span class="badge tier-mid">{{ 'golive.undecided' | t }}</span> }
                @if (r.state !== 'ok') { <a [routerLink]="r.link" [queryParams]="r.query">{{ 'golive.fix' | t }}</a> }
              </li>
            }
          </ul>
          @if (!tailoring(d).ok && !tailoring(d).libreoffice) { <app-libreoffice-card /> }

          @if (confirming()) {
            <div class="alert alert-error space-y-2" role="alertdialog" aria-labelledby="golive-confirm-title" aria-describedby="golive-confirm-body">
              <p id="golive-confirm-title"><strong>{{ 'golive.confirm' | t }}</strong></p>
              <div id="golive-confirm-body" class="space-y-1">
                <p>{{ 'golive.confirmBody' | t }}</p>
                @if (d.checklist.confirm_each.ok) {
                  <p>{{ 'golive.confirmEachOn' | t }}</p>
                } @else {
                  <p><strong>{{ 'golive.confirmEachOff' | t }}</strong></p>
                }
              </div>
              <div class="flex flex-wrap gap-3 pt-1 max-sm:flex-col">
                <button #cancelBtn type="button" class="btn btn-primary" (click)="confirming.set(false)" [disabled]="busy()">{{ 'golive.confirmNo' | t }}</button>
                <button type="button" class="btn btn-danger" (click)="turnOn()" [disabled]="busy()">{{ 'golive.confirmYes' | t }}</button>
              </div>
            </div>
          } @else {
            <div class="flex flex-wrap items-center gap-3 max-sm:flex-col max-sm:items-stretch max-sm:gap-4">
              <button type="button" class="btn btn-primary max-sm:min-h-11" [disabled]="!ready(d) || busy()" (click)="confirming.set(true)">{{ 'golive.turnOn' | t }}</button>
              <button type="button" class="btn max-sm:min-h-11" (click)="cancel.emit()">{{ 'golive.notNow' | t }}</button>
              @if (!ready(d)) { <span class="hint mt-0">{{ 'golive.needs' | t }}</span> }
            </div>
          }
          <app-privacy />
        </div>
      }
    } @else if (!error()) {
      <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
    }

    <dialog #box class="m-auto max-h-[92vh] max-w-[min(95vw,64rem)] rounded-xl bg-white p-3 text-slate-900 backdrop:bg-black/60 dark:bg-slate-900 dark:text-slate-100"
            [attr.aria-label]="shot()?.alt ?? ''" (close)="shot.set(null)" (click)="backdrop($event)">
      @if (shot(); as s) {
        <img [src]="s.src" [alt]="s.alt" class="mx-auto block max-h-[78vh] w-auto max-w-full rounded-lg">
        <div class="mt-3 flex items-center justify-between gap-3">
          <p class="min-w-0 truncate text-sm" dir="auto">{{ s.alt }}</p>
          <button type="button" class="btn" (click)="box.close()">{{ 'golive.close' | t }}</button>
        </div>
      }
    </dialog>
  `,
})
export class GoLiveCard implements OnInit {
  private readonly api = inject(Api);
  private readonly shell = inject(Shell);
  private readonly store = inject(SettingsStore);
  private readonly i18n = inject(I18n);
  private readonly lo = inject(LibreOffice);
  /** Real applications were just turned on (the status then says live, so the host keeps this card to show the message). */
  readonly enabled = output<void>();
  readonly cancel = output<void>();
  protected readonly data = signal<GoLive | null>(null);
  protected readonly error = signal('');
  protected readonly confirming = signal(false);
  protected readonly busy = signal(false);
  protected readonly on = signal(false);
  /** The tailored CV of `tailored_example`, for the red-line under the screenshots. */
  protected readonly diff = signal<Tailoring | null>(null);
  protected readonly diffError = signal(false);
  protected readonly allPatches = signal(false);
  protected readonly PREVIEW = 5;
  /** The screenshot open in the lightbox. */
  protected readonly shot = signal<{ src: string; alt: string } | null>(null);
  private readonly box = viewChild<ElementRef<HTMLDialogElement>>('box');
  private readonly cancelBtn = viewChild<ElementRef<HTMLButtonElement>>('cancelBtn');

  constructor() {
    effect(() => {
      if (this.confirming()) this.cancelBtn()?.nativeElement.focus(); // the safe answer is where the focus starts
    });
  }

  ngOnInit(): void {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const d = await this.api.get<GoLive>('/golive');
      this.data.set(d);
      this.on.set(d.live);
      if (d.tailored_example) void this.loadDiff(d.tailored_example.job_id);
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  private async loadDiff(id: number): Promise<void> {
    try {
      this.diff.set((await this.api.get<JobDetail>(`/jobs/${id}`)).tailoring);
      if (!this.diff()) this.diffError.set(true);
    } catch {
      this.diffError.set(true);
    }
  }

  protected shownPatches(t: Tailoring) {
    return this.allPatches() ? t.patches : t.patches.slice(0, this.PREVIEW);
  }

  /** The checklist as the user sees it: what is true now, and where to fix what is not. */
  protected rows(d: GoLive): Row[] {
    const c = d.checklist;
    const t = (k: string) => this.i18n.t(k);
    const tail = this.tailoring(d);
    return [
      { id: 'cv', state: c.cv_ready.ok ? 'ok' : 'todo', label: t(`golive.cv.${c.cv_ready.detail}`), link: '/settings/profile' },
      {
        id: 'tailoring',
        state: tail.ok ? 'ok' : tail.mode === 'undecided' ? 'undecided' : 'todo',
        label: t(tail.mode === 'original' ? 'golive.tail.original' : tail.ok ? 'golive.tail.on' : tail.mode === 'undecided' ? 'golive.tail.undecided' : 'golive.tail.noTool'),
        link: '/settings/applying',
      },
      { id: 'answers', state: c.answers_reviewed.ok ? 'ok' : 'todo', label: t('golive.check.answers'), link: '/settings/answers' },
      {
        id: 'open',
        state: c.open_items.ok ? 'ok' : 'todo',
        label: c.open_items.ok ? t('golive.open.ok') : this.i18n.plural('golive.open.count', c.open_items.count),
        link: '/needs-you',
        query: { tab: 'finish' },
      },
      { id: 'confirm', state: c.confirm_each.ok ? 'ok' : 'todo', label: t('golive.check.confirm'), link: '/settings/applying' },
      { id: 'caps', state: c.caps_set.ok ? 'ok' : 'todo', label: t('golive.check.caps'), link: '/settings/applying' },
    ];
  }

  /**
   * How the CV is sent. The server's answer, unless the user just changed it in the LibreOffice card inside this one
   * (decline, Change, install): the card knows before the next load.
   */
  protected tailoring(d: GoLive): GoLive['checklist']['tailoring'] {
    const t = d.checklist.tailoring;
    const choice = this.lo.tailor();
    const mode = choice === undefined ? t.mode : choice === false ? 'original' : choice ? 'tailor' : 'undecided';
    const libreoffice = this.lo.info()?.installed ?? t.libreoffice;
    if (mode === t.mode && libreoffice === t.libreoffice) return t;
    return { mode, libreoffice, ok: mode === 'original' || (mode === 'tailor' && libreoffice) };
  }

  /**
   * The CV, how it is sent and "confirm each submission" are required; answers, open items and daily limits are shown
   * but advisory. With LibreOffice installed, "not decided" means tailoring (the default).
   */
  protected ready = (d: GoLive): boolean => {
    const c = d.checklist;
    const t = this.tailoring(d);
    return c.cv_ready.ok && c.confirm_each.ok && (t.ok || (t.mode === 'undecided' && t.libreoffice));
  };

  protected zoom(src: string, alt: string): void {
    this.shot.set({ src, alt });
    queueMicrotask(() => {
      const box = this.box()?.nativeElement;
      if (box && !box.open) box.showModal(); // Esc closes it, Tab stays inside, focus returns to the thumbnail
      setTimeout(() => box?.querySelector('button')?.focus()); // once the picture and its Close button are drawn
    });
  }

  /** A click on the dim area around the picture (the dialog element itself) closes it. */
  protected backdrop(e: MouseEvent): void {
    if (e.target === this.box()?.nativeElement) this.box()?.nativeElement.close();
  }

  protected async turnOn(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      if (this.store.loaded()) await this.viaStore();
      else {
        // the whole config is one document: read it fresh so other pages' edits are not overwritten
        const cfg = await this.api.get<SearchConfig>('/search');
        await this.api.put('/search', { ...cfg, apply: { ...cfg.apply, live: true } });
      }
      await this.shell.refresh(); // the header badge flips
      this.on.set(true);
      this.confirming.set(false);
      this.enabled.emit();
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }

  /** The settings store keeps its own copy of the config and saves it whole, so the change has to go through it. */
  private async viaStore(): Promise<void> {
    this.store.update('apply.live', true);
    for (let i = 0; i < 50; i++) { // the store saves about 400 ms after an edit
      await new Promise((r) => setTimeout(r, 100));
      const f = this.store.fields()['apply.live'];
      if (f?.state === 'saved') return;
      if (f?.state === 'error') {
        this.store.update('apply.live', false);
        throw new Error(f.error);
      }
    }
    throw new Error(this.i18n.t('settings.err.network'));
  }
}
