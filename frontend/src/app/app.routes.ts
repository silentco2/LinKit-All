import { inject } from '@angular/core';
import { CanActivateFn, RedirectFunction, Router, Routes } from '@angular/router';
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

/** An old page's URL redirected to its tab, keeping whatever query it had. */
const tab = (path: string, id?: string): RedirectFunction => ({ queryParams }) =>
  inject(Router).createUrlTree([path], { queryParams: id ? { ...queryParams, tab: id } : queryParams });

export const routes: Routes = [
  { path: '', pathMatch: 'full', canActivate: [gate('/home')], children: [] },
  { path: 'welcome', title: 'Welcome · LinKit All', loadComponent: () => import('./pages/welcome').then((m) => m.WelcomePage) },
  { path: 'settings', title: 'Settings · LinKit All', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage) },
  { path: 'settings/:section', title: 'Settings · LinKit All', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage) },
  { path: 'setup', pathMatch: 'full', canActivate: [gate('/settings')], children: [] }, // the old wizard
  { path: 'answers', redirectTo: 'settings/answers' },
  { path: 'vault', redirectTo: 'settings/accounts' },
  { path: 'jobs', title: 'Jobs · LinKit All', loadComponent: () => import('./pages/jobs').then((m) => m.JobsPage) },
  { path: 'home', title: 'Home · LinKit All', loadComponent: () => import('./pages/home').then((m) => m.HomePage) },
  { path: 'needs-you', title: 'Needs you · LinKit All', loadComponent: () => import('./pages/needs-you').then((m) => m.NeedsYouPage) },
  { path: 'activity', title: 'Activity · LinKit All', loadComponent: () => import('./pages/activity').then((m) => m.ActivityPage) },
  { path: 'review', redirectTo: tab('/needs-you', 'approve') },
  { path: 'actions', redirectTo: tab('/needs-you', 'finish') },
  { path: 'live', redirectTo: tab('/activity') },
  { path: 'report', redirectTo: tab('/activity', 'history') },
  { path: '**', redirectTo: 'home' },
];
