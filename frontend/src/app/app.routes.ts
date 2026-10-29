import { inject } from '@angular/core';
import { CanActivateFn, Router, Routes } from '@angular/router';
import { Api } from './api';
import { Status } from './types';

/** Send to `done` once the server says the required setup is done, else to the first-run flow. */
const gate = (done: string): CanActivateFn => async () => {
  const router = inject(Router);
  try {
    const s = await inject(Api).get<Status>('/status');
    return router.parseUrl(s.setup.required_done ? done : '/welcome');
  } catch {
    return router.parseUrl(done); // server hiccup: do not trap the user in setup
  }
};

export const routes: Routes = [
  { path: '', pathMatch: 'full', canActivate: [gate('/jobs')], children: [] },
  { path: 'welcome', title: 'Welcome · LinKit All', loadComponent: () => import('./pages/welcome').then((m) => m.WelcomePage) },
  { path: 'settings', title: 'Settings · LinKit All', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage) },
  { path: 'settings/:section', title: 'Settings · LinKit All', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage) },
  { path: 'setup', pathMatch: 'full', canActivate: [gate('/settings')], children: [] }, // the old wizard
  { path: 'answers', redirectTo: 'settings/answers' },
  { path: 'vault', redirectTo: 'settings/accounts' },
  { path: 'jobs', title: 'Jobs · LinKit All', loadComponent: () => import('./pages/jobs').then((m) => m.JobsPage) },
  { path: 'review', title: 'Review · LinKit All', loadComponent: () => import('./pages/review').then((m) => m.ReviewPage) },
  { path: 'actions', title: 'Action Center · LinKit All', loadComponent: () => import('./pages/actions').then((m) => m.ActionsPage) },
  { path: 'live', title: 'Live run · LinKit All', loadComponent: () => import('./pages/live').then((m) => m.LivePage) },
  { path: 'report', title: 'Report · LinKit All', loadComponent: () => import('./pages/report').then((m) => m.ReportPage) },
  { path: '**', redirectTo: 'jobs' },
];
