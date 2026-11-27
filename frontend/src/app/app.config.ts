import { ApplicationConfig, provideBrowserGlobalErrorListeners, isDevMode } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { REMOTE } from './remote';
import { provideServiceWorker } from '@angular/service-worker';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // the phone only (docs/phone.md): it caches the app shell, never API data; the PC keeps
    // loading each new build straight from the server
    provideServiceWorker('push-sw.js', { // Angular's ngsw-worker.js plus the push alert
      enabled: !isDevMode() && REMOTE,
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
