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
  { path: '', pathMatch: 'full', canActivate: [gate('/home')], children: [] },
  { path: 'welcome', title: 'Welcome · LinKit All', loadComponent: () => import('./pages/welcome').then((m) => m.WelcomePage) },
  { path: 'settings', title: 'Settings · LinKit All', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage) },
  { path: 'settings/:section', title: 'Settings · LinKit All', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage) },
  { path: 'jobs', title: 'Jobs · LinKit All', loadComponent: () => import('./pages/jobs').then((m) => m.JobsPage) },
  { path: 'home', title: 'Home · LinKit All', loadComponent: () => import('./pages/home').then((m) => m.HomePage) },
  { path: 'needs-you', title: 'Needs you · LinKit All', loadComponent: () => import('./pages/needs-you').then((m) => m.NeedsYouPage) },
  { path: '**', redirectTo: 'home' },
];
