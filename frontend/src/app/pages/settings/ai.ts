import { Component, inject } from '@angular/core';
import { AiBody, AiConnect } from '../../components/ai-connect';
import { TPipe } from '../../i18n';
import { SettingsStore } from './store';

/** Settings > AI: the same connect box as the first run. A passing test saves the choice through the store. */
@Component({
  selector: 'app-settings-ai',
  imports: [AiConnect, TPipe],
  template: `
    <section class="card space-y-5">
      <h2>{{ 'welcome.ai.title' | t }}</h2>
      <app-ai-connect intro="setup.ai.intro" [testOnLoad]="false" [persist]="save" />
    </section>
  `,
})
export class AiSection {
  private readonly store = inject(SettingsStore);
  protected readonly save = (ai: AiBody): Promise<void> => this.store.saveAi(ai);
}
