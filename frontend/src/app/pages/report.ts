import { DatePipe, KeyValuePipe, NgTemplateOutlet } from '@angular/common';
import { Component, computed, effect, ElementRef, inject, OnDestroy, signal, viewChild } from '@angular/core';
import {
  ArcElement, BarController, BarElement, CategoryScale, Chart, DoughnutController, Legend, LinearScale, LineController,
  LineElement, PointElement, Tooltip,
} from 'chart.js';
import { Api } from '../api';
import { I18n, SourcePipe, TPipe } from '../i18n';
import { Live } from '../live';
import { fmtNum, labelOr, localeOf } from '../locale';
import { Report } from '../types';

Chart.register(
  BarController, BarElement, CategoryScale, LinearScale, DoughnutController, ArcElement, Tooltip, Legend,
  LineController, LineElement, PointElement,
);

interface RunRow {
  id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, Record<string, unknown>>;
}

const SERIES = [
  { label: 'report.col.applied', key: 'applied', color: '#10b981' },
  { label: 'report.col.failed', key: 'failed', color: '#ef4444' },
  { label: 'report.col.needsYou', key: 'needs_user', color: '#f59e0b' },
  { label: 'report.col.skipped', key: 'skipped', color: '#94a3b8' },
] as const;

// The server names the funnel steps in English; unknown steps are shown as they come.
const FUNNEL: Record<string, string> = {
  Found: 'report.funnel.found',
  'Passed filters': 'report.funnel.passed',
  'AI scored': 'report.funnel.scored',
  'Queued to apply': 'report.funnel.queued',
  Applied: 'report.funnel.applied',
};

@Component({
  selector: 'app-report',
  imports: [DatePipe, KeyValuePipe, NgTemplateOutlet, SourcePipe, TPipe],
  template: `
    <div class="flex flex-wrap items-center justify-end gap-3">
      <div class="flex flex-wrap items-center gap-3 text-sm">
        <label class="flex items-center gap-2">{{ 'report.run' | t }}
          <select class="rounded border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700" (change)="pick($event)">
            <option value="" [selected]="runId() === null">{{ 'report.allRuns' | t }}</option>
            @for (run of runs(); track run.id) {
              <option [value]="run.id" [selected]="runId() === run.id">#{{ num(run.id) }}</option>
            }
          </select>
        </label>
        <a class="underline" [href]="exportUrl('csv')" download>{{ 'report.exportCsv' | t }}</a>
        <a class="underline" [href]="exportUrl('pdf')" download>{{ 'report.exportPdf' | t }}</a>
      </div>
    </div>
    @if (report(); as r) {
      <div class="mt-6 grid gap-6 lg:grid-cols-3">
        <section class="card lg:col-span-2">
          <h2>{{ 'report.funnel.title' | t }}</h2>
          <div class="mt-4 h-64"><canvas #funnel [attr.aria-label]="'report.funnel.aria' | t" role="img"></canvas></div>
        </section>
        <section class="card">
          <h2>{{ 'report.tiers.title' | t }}</h2>
          <div class="mt-4 h-64"><canvas #tiers [attr.aria-label]="'report.tiers.aria' | t" role="img"></canvas></div>
        </section>
      </div>

      <section class="card mt-6">
        <h2>{{ 'report.overtime.title' | t }}</h2>
        <div class="mt-4 h-64"><canvas #overtime [attr.aria-label]="'report.overtime.aria' | t" role="img"></canvas></div>
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>{{ 'report.platform.title' | t }}</h2>
        <ng-container *ngTemplateOutlet="outcomes; context: { $implicit: r.per_platform.source, label: 'report.col.source', names: true }" />
        <ng-container *ngTemplateOutlet="outcomes; context: { $implicit: r.per_platform.ats, label: 'report.col.ats', names: true }" />
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>{{ 'report.board.title' | t }}</h2>
        <ng-container *ngTemplateOutlet="outcomes; context: { $implicit: r.per_board, label: 'report.col.company' }" />
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>{{ 'report.source.title' | t }}</h2>
        <table class="mt-3 w-full text-sm">
          <thead class="text-start text-xs tracking-wide text-slate-500 uppercase rtl:tracking-normal">
            <tr><th class="py-2">{{ 'report.col.source' | t }}</th><th class="text-end">{{ 'report.col.found' | t }}</th><th class="text-end">{{ 'report.col.filteredOut' | t }}</th><th class="text-end">{{ 'report.col.toReview' | t }}</th><th class="text-end">{{ 'report.col.toApply' | t }}</th><th class="text-end">{{ 'report.col.applied' | t }}</th><th class="text-end">{{ 'report.col.failed' | t }}</th></tr>
          </thead>
          <tbody>
            @for (s of r.sources | keyvalue; track s.key) {
              <tr class="border-t border-slate-100 dark:border-slate-800">
                <td class="py-2 font-medium"><bdi>{{ s.key | src }}</bdi></td>
                <td class="text-end">{{ num(s.value['total']) }}</td>
                <td class="text-end">{{ num(s.value['filtered_out'] ?? 0) }}</td>
                <td class="text-end">{{ num(s.value['awaiting_review'] ?? 0) }}</td>
                <td class="text-end">{{ num(s.value['queued_apply'] ?? 0) }}</td>
                <td class="text-end">{{ num(s.value['applied'] ?? 0) }}</td>
                <td class="text-end">{{ num(s.value['failed'] ?? 0) }}</td>
              </tr>
            } @empty {
              <tr><td colspan="7" class="py-4 text-center text-slate-500">{{ 'report.source.empty' | t }}</td></tr>
            }
          </tbody>
        </table>
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>{{ 'report.runs.title' | t }}</h2>
        <table class="mt-3 w-full text-sm">
          <thead class="text-start text-xs tracking-wide text-slate-500 uppercase rtl:tracking-normal">
            <tr><th class="py-2">{{ 'report.run' | t }}</th><th>{{ 'report.col.started' | t }}</th><th>{{ 'report.col.status' | t }}</th><th class="text-end">{{ 'report.col.newJobs' | t }}</th><th class="text-end">{{ 'report.col.ranked' | t }}</th><th class="text-end">{{ 'common.tier.high' | t }}</th><th class="text-end">{{ 'common.tier.mid' | t }}</th></tr>
          </thead>
          <tbody>
            @for (run of runs(); track run.id) {
              <tr class="border-t border-slate-100 dark:border-slate-800">
                <td class="py-2">#{{ num(run.id) }}</td>
                <td>{{ run.started_at + 'Z' | date: 'medium' : undefined : loc() }}</td>
                <td>{{ runStatus(run.status) }}</td>
                <td class="text-end">{{ stat(run, 'discover', 'new') }}</td>
                <td class="text-end">{{ stat(run, 'rank', 'ranked') }}</td>
                <td class="text-end">{{ stat(run, 'score', 'high') }}</td>
                <td class="text-end">{{ stat(run, 'score', 'mid') }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>{{ 'report.outcomes.title' | t }}</h2>
        <table class="mt-3 w-full text-sm">
          <thead class="text-start text-xs tracking-wide text-slate-500 uppercase rtl:tracking-normal">
            <tr><th class="py-2">{{ 'report.run' | t }}</th><th class="text-end">{{ 'report.col.found' | t }}</th><th class="text-end">{{ 'report.col.applied' | t }}</th><th class="text-end">{{ 'report.col.failed' | t }}</th><th class="text-end">{{ 'report.col.skipped' | t }}</th><th class="text-end">{{ 'report.col.needsYou' | t }}</th></tr>
          </thead>
          <tbody>
            @for (run of r.per_run; track run.run_id) {
              <tr class="border-t border-slate-100 dark:border-slate-800">
                <td class="py-2">#{{ num(run.run_id) }}</td>
                <td class="text-end">{{ num(run.found) }}</td>
                <td class="text-end">{{ num(run.applied) }}</td>
                <td class="text-end">{{ num(run.failed) }}</td>
                <td class="text-end">{{ num(run.skipped) }}</td>
                <td class="text-end">{{ num(run.needs_user) }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }

    <ng-template #outcomes let-rows let-label="label" let-names="names">
      <table class="mt-3 w-full text-sm">
        <thead class="text-start text-xs tracking-wide text-slate-500 uppercase rtl:tracking-normal">
          <tr><th class="py-2">{{ label | t }}</th><th class="text-end">{{ 'report.col.found' | t }}</th><th class="text-end">{{ 'report.col.applied' | t }}</th><th class="text-end">{{ 'report.col.failed' | t }}</th><th class="text-end">{{ 'report.col.skipped' | t }}</th><th class="text-end">{{ 'report.col.needsYou' | t }}</th></tr>
        </thead>
        <tbody>
          @for (row of rows; track row.name) {
            <tr class="border-t border-slate-100 dark:border-slate-800">
              <td class="py-2 font-medium"><bdi>{{ names ? (row.name | src) : row.name }}</bdi></td>
              <td class="text-end">{{ num(row.found) }}</td>
              <td class="text-end">{{ num(row.applied) }}</td>
              <td class="text-end">{{ num(row.failed) }}</td>
              <td class="text-end">{{ num(row.skipped) }}</td>
              <td class="text-end">{{ num(row.needs_user) }}</td>
            </tr>
          } @empty {
            <tr><td colspan="6" class="py-4 text-center text-slate-500">{{ 'report.empty' | t }}</td></tr>
          }
        </tbody>
      </table>
    </ng-template>
  `,
})
export class ReportPage implements OnDestroy {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  private readonly i18n = inject(I18n);
  protected readonly loc = computed(() => localeOf(this.i18n.lang()));
  protected readonly report = signal<Report | null>(null);
  protected readonly runs = signal<RunRow[]>([]);
  protected readonly runId = signal<number | null>(null);
  private readonly funnelCanvas = viewChild<ElementRef<HTMLCanvasElement>>('funnel');
  private readonly tiersCanvas = viewChild<ElementRef<HTMLCanvasElement>>('tiers');
  private readonly overtimeCanvas = viewChild<ElementRef<HTMLCanvasElement>>('overtime');
  private charts: Chart[] = [];

  constructor() {
    effect(() => {
      this.live.changed();
      this.load();
    });
    effect(() => {
      const r = this.report();
      const funnel = this.funnelCanvas()?.nativeElement;
      const tiers = this.tiersCanvas()?.nativeElement;
      const overtime = this.overtimeCanvas()?.nativeElement;
      this.i18n.lang(); // redraw with translated labels when the language changes
      if (r && funnel && tiers && overtime) this.draw(r, funnel, tiers, overtime);
    });
  }

  ngOnDestroy(): void {
    this.charts.forEach((c) => c.destroy());
  }

  async load(): Promise<void> {
    const [report, runs] = await Promise.all([
      this.api.get<Report>(`/report${this.query()}`),
      this.api.get<{ recent: RunRow[] }>('/runs'),
    ]);
    this.report.set(report);
    this.runs.set(runs.recent);
  }

  protected pick(e: Event): void {
    const v = (e.target as HTMLSelectElement).value;
    this.runId.set(v === '' ? null : Number(v));
  }

  protected exportUrl(kind: 'csv' | 'pdf'): string {
    return `/api/report/export.${kind}${this.query()}`;
  }

  private query(): string {
    const id = this.runId();
    return id === null ? '' : `?run_id=${id}`;
  }

  protected num = (n: number | null | undefined): string => fmtNum(this.loc(), n);
  protected runStatus = (s: string): string => labelOr(this.i18n, 'report.runStatus.', s);

  stat(run: RunRow, stage: string, key: string): string {
    const v = run.stats?.[stage]?.[key];
    return v === undefined ? '–' : String(v);
  }

  private draw(r: Report, funnel: HTMLCanvasElement, tiers: HTMLCanvasElement, overtime: HTMLCanvasElement): void {
    this.charts.forEach((c) => c.destroy());
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    const t = (key: string) => this.i18n.t(key);
    const loc = this.loc();
    const rtl = this.i18n.lang() === 'ar';
    const legend = { position: 'bottom' as const, rtl, textDirection: rtl ? 'rtl' : 'ltr' };
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = dark ? '#cbd5e1' : '#475569';
    Chart.defaults.borderColor = dark ? '#1e293b' : '#e2e8f0';
    this.charts = [
      new Chart(funnel, {
        type: 'bar',
        data: {
          labels: r.funnel.map((f) => `${FUNNEL[f.step] ? t(FUNNEL[f.step]) : f.step} (${fmtNum(loc, f.count)})`),
          datasets: [{ data: r.funnel.map((f) => f.count), backgroundColor: '#3b6fd8', borderRadius: 6 }],
        },
        options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false } } },
      }),
      new Chart(tiers, {
        type: 'doughnut',
        data: {
          labels: [t('report.tier.high'), t('report.tier.mid'), t('report.tier.low')],
          datasets: [{ data: [r.tiers['high'] ?? 0, r.tiers['mid'] ?? 0, r.tiers['low'] ?? 0], backgroundColor: ['#10b981', '#f59e0b', '#94a3b8'] }],
        },
        options: { maintainAspectRatio: false, plugins: { legend } },
      }),
      new Chart(overtime, {
        type: 'line',
        data: {
          labels: r.over_time.map((d) => d.date),
          datasets: SERIES.map((s) => ({
            label: t(s.label),
            data: r.over_time.map((d) => d[s.key]),
            borderColor: s.color,
            backgroundColor: s.color,
            pointRadius: 0,
            tension: 0.2,
          })),
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        },
      }),
    ];
  }
}
