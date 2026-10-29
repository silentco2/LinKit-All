import { Component, computed, ElementRef, inject, input, output } from '@angular/core';
import { I18n, TPipe } from '../i18n';
import { fmtNum, localeOf } from '../locale';

export interface TabItem { id: string; label: string; count?: number }

/**
 * A tab strip (role=tablist) with roving focus and arrow keys. The page owns the state and renders the panel:
 * `<div role="tabpanel" [id]="prefix + '-panel-' + active" [attr.aria-labelledby]="prefix + '-tab-' + active">`.
 */
@Component({
  selector: 'app-tabs',
  imports: [TPipe],
  template: `
    <div role="tablist" class="flex flex-wrap gap-2" [attr.aria-label]="label() | t" (keydown)="key($event)">
      @for (t of tabs(); track t.id) {
        <button type="button" role="tab" class="btn" [id]="prefix() + '-tab-' + t.id" [attr.aria-controls]="prefix() + '-panel-' + t.id"
                [class.btn-primary]="t.id === active()" [attr.aria-selected]="t.id === active()" [attr.aria-current]="t.id === active() ? 'true' : null"
                [attr.tabindex]="t.id === active() ? 0 : -1" (click)="pick.emit(t.id)">
          {{ t.label | t }}
          @if (t.count) { <span class="badge tier-mid">{{ num(t.count) }}</span> }
        </button>
      }
    </div>
  `,
})
export class Tabs {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly i18n = inject(I18n);
  readonly tabs = input.required<TabItem[]>();
  readonly active = input.required<string>();
  readonly prefix = input.required<string>();
  readonly label = input.required<string>();
  readonly pick = output<string>();
  private readonly loc = computed(() => localeOf(this.i18n.lang()));

  protected num = (n: number): string => fmtNum(this.loc(), n);

  protected key(e: KeyboardEvent): void {
    const ids = this.tabs().map((t) => t.id);
    const rtl = document.documentElement.dir === 'rtl';
    const step = e.key === 'ArrowRight' ? (rtl ? -1 : 1) : e.key === 'ArrowLeft' ? (rtl ? 1 : -1) : 0;
    let i = ids.indexOf(this.active());
    if (step) i = (i + step + ids.length) % ids.length;
    else if (e.key === 'Home') i = 0;
    else if (e.key === 'End') i = ids.length - 1;
    else return;
    e.preventDefault();
    this.pick.emit(ids[i]);
    this.host.nativeElement.querySelector<HTMLElement>(`#${this.prefix()}-tab-${ids[i]}`)?.focus();
  }
}
