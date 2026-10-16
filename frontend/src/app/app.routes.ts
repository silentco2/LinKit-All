import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'jobs' },
  { path: 'setup', title: 'Setup · LinKit All', loadComponent: () => import('./pages/setup').then((m) => m.SetupPage) },
  { path: 'jobs', title: 'Jobs · LinKit All', loadComponent: () => import('./pages/jobs').then((m) => m.JobsPage) },
  { path: 'review', title: 'Review · LinKit All', loadComponent: () => import('./pages/review').then((m) => m.ReviewPage) },
  { path: 'actions', title: 'Action Center · LinKit All', loadComponent: () => import('./pages/actions').then((m) => m.ActionsPage) },
  { path: 'answers', title: 'Answer bank · LinKit All', loadComponent: () => import('./pages/answers').then((m) => m.AnswersPage) },
  { path: 'vault', title: 'Vault · LinKit All', loadComponent: () => import('./pages/vault').then((m) => m.VaultPage) },
  { path: 'live', title: 'Live run · LinKit All', loadComponent: () => import('./pages/live').then((m) => m.LivePage) },
  { path: 'report', title: 'Report · LinKit All', loadComponent: () => import('./pages/report').then((m) => m.ReportPage) },
  { path: '**', redirectTo: 'jobs' },
];
