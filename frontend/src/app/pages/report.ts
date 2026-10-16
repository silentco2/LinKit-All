import { DatePipe, DecimalPipe, KeyValuePipe, NgTemplateOutlet } from '@angular/common';
import { Component, effect, ElementRef, inject, OnDestroy, signal, viewChild } from '@angular/core';
import {
  ArcElement, BarController, BarElement, CategoryScale, Chart, DoughnutController, Legend, LinearScale, LineController,
  LineElement, PointElement, Tooltip,
} from 'chart.js';
import { Api } from '../api';
import { Live } from '../live';
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
  { label: 'Applied', key: 'applied', color: '#10b981' },
  { label: 'Failed', key: 'failed', color: '#ef4444' },
  { label: 'Needs you', key: 'needs_user', color: '#f59e0b' },
  { label: 'Skipped', key: 'skipped', color: '#94a3b8' },
] as const;

@Component({
  selector: 'app-report',
  imports: [DatePipe, DecimalPipe, KeyValuePipe, NgTemplateOutlet],
  template: `
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1>Report</h1>
      <div class="flex flex-wrap items-center gap-3 text-sm">
        <label class="flex items-center gap-2">Run
          <select class="rounded border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700" (change)="pick($event)">
            <option value="" [selected]="runId() === null">All runs</option>
            @for (run of runs(); track run.id) {
              <option [value]="run.id" [selected]="runId() === run.id">#{{ run.id }}</option>
            }
          </select>
        </label>
        <a class="underline" [href]="exportUrl('csv')" download>Export CSV</a>
        <a class="underline" [href]="exportUrl('pdf')" download>Export PDF</a>
      </div>
    </div>
    @if (report(); as r) {
      <div class="mt-6 grid gap-6 lg:grid-cols-3">
        <section class="card lg:col-span-2">
          <h2>Funnel</h2>
          <div class="mt-4 h-64"><canvas #funnel aria-label="Funnel from jobs found to applied" role="img"></canvas></div>
        </section>
        <section class="card">
          <h2>AI tiers</h2>
          <div class="mt-4 h-64"><canvas #tiers aria-label="Jobs per tier" role="img"></canvas></div>
        </section>
      </div>

      <section class="card mt-6">
        <h2>Applications over time</h2>
        <div class="mt-4 h-64"><canvas #overtime aria-label="Daily applied, failed, needs-you and skipped counts, last 90 days" role="img"></canvas></div>
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>By platform</h2>
        <ng-container *ngTemplateOutlet="outcomes; context: { $implicit: r.per_platform.source, label: 'Source' }" />
        <ng-container *ngTemplateOutlet="outcomes; context: { $implicit: r.per_platform.ats, label: 'ATS' }" />
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>By career page (company)</h2>
        <ng-container *ngTemplateOutlet="outcomes; context: { $implicit: r.per_board, label: 'Company' }" />
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>By source</h2>
        <table class="mt-3 w-full text-sm">
          <thead class="text-left text-xs tracking-wide text-slate-500 uppercase">
            <tr><th class="py-2">Source</th><th class="text-right">Found</th><th class="text-right">Filtered out</th><th class="text-right">To review</th><th class="text-right">To apply</th><th class="text-right">Applied</th><th class="text-right">Failed</th></tr>
          </thead>
          <tbody>
            @for (s of r.sources | keyvalue; track s.key) {
              <tr class="border-t border-slate-100 dark:border-slate-800">
                <td class="py-2 font-medium">{{ s.key }}</td>
                <td class="text-right">{{ s.value['total'] | number }}</td>
                <td class="text-right">{{ (s.value['filtered_out'] ?? 0) | number }}</td>
                <td class="text-right">{{ (s.value['awaiting_review'] ?? 0) | number }}</td>
                <td class="text-right">{{ (s.value['queued_apply'] ?? 0) | number }}</td>
                <td class="text-right">{{ (s.value['applied'] ?? 0) | number }}</td>
                <td class="text-right">{{ (s.value['failed'] ?? 0) | number }}</td>
              </tr>
            } @empty {
              <tr><td colspan="7" class="py-4 text-center text-slate-500">No jobs yet.</td></tr>
            }
          </tbody>
        </table>
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>Runs</h2>
        <table class="mt-3 w-full text-sm">
          <thead class="text-left text-xs tracking-wide text-slate-500 uppercase">
            <tr><th class="py-2">Run</th><th>Started</th><th>Status</th><th class="text-right">New jobs</th><th class="text-right">Ranked</th><th class="text-right">High</th><th class="text-right">Mid</th></tr>
          </thead>
          <tbody>
            @for (run of runs(); track run.id) {
              <tr class="border-t border-slate-100 dark:border-slate-800">
                <td class="py-2">#{{ run.id }}</td>
                <td>{{ run.started_at + 'Z' | date: 'medium' }}</td>
                <td>{{ run.status }}</td>
                <td class="text-right">{{ stat(run, 'discover', 'new') }}</td>
                <td class="text-right">{{ stat(run, 'rank', 'ranked') }}</td>
                <td class="text-right">{{ stat(run, 'score', 'high') }}</td>
                <td class="text-right">{{ stat(run, 'score', 'mid') }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>

      <section class="card mt-6 overflow-x-auto">
        <h2>Outcomes per run</h2>
        <table class="mt-3 w-full text-sm">
          <thead class="text-left text-xs tracking-wide text-slate-500 uppercase">
            <tr><th class="py-2">Run</th><th class="text-right">Found</th><th class="text-right">Applied</th><th class="text-right">Failed</th><th class="text-right">Skipped</th><th class="text-right">Needs you</th></tr>
          </thead>
          <tbody>
            @for (run of r.per_run; track run.run_id) {
              <tr class="border-t border-slate-100 dark:border-slate-800">
                <td class="py-2">#{{ run.run_id }}</td>
                <td class="text-right">{{ run.found | number }}</td>
                <td class="text-right">{{ run.applied | number }}</td>
                <td class="text-right">{{ run.failed | number }}</td>
                <td class="text-right">{{ run.skipped | number }}</td>
                <td class="text-right">{{ run.needs_user | number }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }

    <ng-template #outcomes let-rows let-label="label">
      <table class="mt-3 w-full text-sm">
        <thead class="text-left text-xs tracking-wide text-slate-500 uppercase">
          <tr><th class="py-2">{{ label }}</th><th class="text-right">Found</th><th class="text-right">Applied</th><th class="text-right">Failed</th><th class="text-right">Skipped</th><th class="text-right">Needs you</th></tr>
        </thead>
        <tbody>
          @for (row of rows; track row.name) {
            <tr class="border-t border-slate-100 dark:border-slate-800">
              <td class="py-2 font-medium">{{ row.name }}</td>
              <td class="text-right">{{ row.found | number }}</td>
              <td class="text-right">{{ row.applied | number }}</td>
              <td class="text-right">{{ row.failed | number }}</td>
              <td class="text-right">{{ row.skipped | number }}</td>
              <td class="text-right">{{ row.needs_user | number }}</td>
            </tr>
          } @empty {
            <tr><td colspan="6" class="py-4 text-center text-slate-500">Nothing yet.</td></tr>
          }
        </tbody>
      </table>
    </ng-template>
  `,
})
export class ReportPage implements OnDestroy {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
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

  stat(run: RunRow, stage: string, key: string): string {
    const v = run.stats?.[stage]?.[key];
    return v === undefined ? '–' : String(v);
  }

  private draw(r: Report, funnel: HTMLCanvasElement, tiers: HTMLCanvasElement, overtime: HTMLCanvasElement): void {
    this.charts.forEach((c) => c.destroy());
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    Chart.defaults.color = dark ? '#cbd5e1' : '#475569';
    Chart.defaults.borderColor = dark ? '#1e293b' : '#e2e8f0';
    this.charts = [
      new Chart(funnel, {
        type: 'bar',
        data: {
          labels: r.funnel.map((f) => `${f.step} (${f.count.toLocaleString()})`),
          datasets: [{ data: r.funnel.map((f) => f.count), backgroundColor: '#3b6fd8', borderRadius: 6 }],
        },
        options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false } } },
      }),
      new Chart(tiers, {
        type: 'doughnut',
        data: {
          labels: ['High (auto-apply)', 'Mid (review)', 'Low (hidden)'],
          datasets: [{ data: [r.tiers['high'] ?? 0, r.tiers['mid'] ?? 0, r.tiers['low'] ?? 0], backgroundColor: ['#10b981', '#f59e0b', '#94a3b8'] }],
        },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } },
      }),
      new Chart(overtime, {
        type: 'line',
        data: {
          labels: r.over_time.map((d) => d.date),
          datasets: SERIES.map((s) => ({
            label: s.label,
            data: r.over_time.map((d) => d[s.key]),
            borderColor: s.color,
            backgroundColor: s.color,
            pointRadius: 0,
            tension: 0.2,
          })),
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom' } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        },
      }),
    ];
  }
}
