import { DatePipe, DecimalPipe, KeyValuePipe } from '@angular/common';
import { Component, effect, ElementRef, inject, OnDestroy, signal, viewChild } from '@angular/core';
import {
  ArcElement, BarController, BarElement, CategoryScale, Chart, DoughnutController, Legend, LinearScale, Tooltip,
} from 'chart.js';
import { Api } from '../api';
import { Live } from '../live';

Chart.register(BarController, BarElement, CategoryScale, LinearScale, DoughnutController, ArcElement, Tooltip, Legend);

interface Report {
  funnel: { step: string; count: number }[];
  tiers: Record<string, number>;
  states: Record<string, number>;
  sources: Record<string, Partial<Record<string, number>>>;
}

interface RunRow {
  id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, Record<string, unknown>>;
}

@Component({
  selector: 'app-report',
  imports: [DatePipe, DecimalPipe, KeyValuePipe],
  template: `
    <h1>Report</h1>
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
    }
  `,
})
export class ReportPage implements OnDestroy {
  private readonly api = inject(Api);
  private readonly live = inject(Live);
  protected readonly report = signal<Report | null>(null);
  protected readonly runs = signal<RunRow[]>([]);
  private readonly funnelCanvas = viewChild<ElementRef<HTMLCanvasElement>>('funnel');
  private readonly tiersCanvas = viewChild<ElementRef<HTMLCanvasElement>>('tiers');
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
      if (r && funnel && tiers) this.draw(r, funnel, tiers);
    });
  }

  ngOnDestroy(): void {
    this.charts.forEach((c) => c.destroy());
  }

  async load(): Promise<void> {
    const [report, runs] = await Promise.all([this.api.get<Report>('/report'), this.api.get<{ recent: RunRow[] }>('/runs')]);
    this.report.set(report);
    this.runs.set(runs.recent);
  }

  stat(run: RunRow, stage: string, key: string): string {
    const v = run.stats?.[stage]?.[key];
    return v === undefined ? '–' : String(v);
  }

  private draw(r: Report, funnel: HTMLCanvasElement, tiers: HTMLCanvasElement): void {
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
    ];
  }
}
