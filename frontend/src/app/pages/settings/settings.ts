import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Hint, resetHints } from '../../components/hint';
import { TPipe } from '../../i18n';
import { AccountsSection } from './accounts';
import { AdvancedSection } from './advanced';
import { AiSection } from './ai';
import { AnswersSection } from './answers';
import { ApplyingSection } from './applying';
import { JobsSection } from './jobs';
import { ProfileSection } from './profile';
import { SourcesSection } from './sources';
import { SettingsStore } from './store';

type Section = { id: string; label: string };

/** Settings shell: the section list (a select on a phone) and the open section. */
@Component({
  selector: 'app-settings',
  imports: [Hint, RouterLink, TPipe, ProfileSection, JobsSection, SourcesSection, AnswersSection, ApplyingSection, AccountsSection, AiSection, AdvancedSection],
  template: `
    <h1>{{ 'settings.title' | t }}</h1>
    <p class="mt-1 text-sm text-slate-500">{{ 'settings.subtitle' | t }}</p>
    <app-hint id="settings">{{ 'hint.settings' | t }}</app-hint>

    <div class="mt-6 grid gap-6 md:grid-cols-[14rem_minmax(0,1fr)]">
      <aside>
        <label class="sr-only" for="section-pick">{{ 'settings.pick' | t }}</label>
        <select id="section-pick" class="input md:hidden" (change)="pick($event)">
          @for (s of sections; track s.id) { <option [value]="s.id" [selected]="s.id === section()">{{ s.label | t }}</option> }
        </select>
        <nav class="hidden md:block" [attr.aria-label]="'settings.nav' | t">
          <ul class="space-y-1">
            @for (s of sections; track s.id) {
              <li>
                <a [routerLink]="['/settings', s.id]" [attr.aria-current]="s.id === section() ? 'page' : null"
                   class="block rounded-lg px-3 py-2 text-sm font-medium no-underline hover:bg-slate-100 hover:no-underline dark:hover:bg-slate-800"
                   [class]="s.id === section() ? 'bg-brand-50 text-brand-700 dark:bg-slate-800 dark:text-white' : 'text-slate-600 dark:text-slate-300'">
                  {{ s.label | t }}
                </a>
              </li>
            }
          </ul>
        </nav>
        <a routerLink="/welcome" class="mt-4 block px-3 text-sm">{{ 'settings.rerun' | t }}</a>
        <button type="button" class="mt-2 block px-3 text-start text-sm text-brand-700 hover:underline dark:text-brand-300" (click)="showTips()">{{ 'settings.tips' | t }}</button>
        @if (tipsReset()) { <p class="hint px-3" role="status">{{ 'settings.tipsDone' | t }}</p> }
      </aside>

      <div class="min-w-0 max-w-3xl">
        @if (store.loaded()) {
          @if (store.alert(); as a) {
            <div class="alert alert-error mb-4" role="alert" dir="auto">{{ 'settings.alert' | t: { text: a } }}</div>
          }
          @switch (section()) {
            @case ('profile') { <app-settings-profile /> }
            @case ('jobs') { <app-settings-jobs /> }
            @case ('sources') { <app-settings-sources /> }
            @case ('answers') { <app-settings-answers /> }
            @case ('applying') { <app-settings-applying /> }
            @case ('accounts') { <app-settings-accounts /> }
            @case ('ai') { <app-settings-ai /> }
            @case ('advanced') { <app-settings-advanced /> }
          }
        } @else if (store.loadError(); as e) {
          <div class="alert alert-error" role="alert">
            <p><strong>{{ 'settings.loadFailed' | t }}</strong></p>
            <p class="mt-1" dir="auto">{{ e }}</p>
            <button type="button" class="btn mt-3" (click)="store.load()">{{ 'welcome.retry' | t }}</button>
          </div>
        } @else {
          <p class="text-sm text-slate-500">{{ 'common.loading' | t }}</p>
        }
      </div>
    </div>
  `,
})
export class SettingsPage implements OnInit {
  protected readonly store = inject(SettingsStore);
  private readonly router = inject(Router);
  private readonly params = toSignal(inject(ActivatedRoute).paramMap);

  protected readonly sections: Section[] = [
    { id: 'profile', label: 'settings.s.profile' },
    { id: 'jobs', label: 'settings.s.jobs' },
    { id: 'sources', label: 'settings.s.sources' },
    { id: 'answers', label: 'settings.s.answers' },
    { id: 'applying', label: 'settings.s.applying' },
    { id: 'accounts', label: 'settings.s.accounts' },
    { id: 'ai', label: 'settings.s.ai' },
    { id: 'advanced', label: 'settings.s.advanced' },
  ];
  protected readonly current = computed(() => this.sections.find((s) => s.id === this.params()?.get('section')) ?? this.sections[0]);
  protected readonly section = computed(() => this.current().id);

  ngOnInit(): void {
    void this.store.load();
  }

  protected readonly tipsReset = signal(false);

  protected showTips(): void {
    resetHints();
    this.tipsReset.set(true);
  }

  protected pick(event: Event): void {
    void this.router.navigate(['/settings', (event.target as HTMLSelectElement).value]);
  }
}
