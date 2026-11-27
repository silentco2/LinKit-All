import { ApplicationConfig, provideBrowserGlobalErrorListeners, isDevMode } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { provideServiceWorker } from '@angular/service-worker';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // the phone only (docs/phone.md): it caches the app shell, never API data; the PC keeps
    // loading each new build straight from the server
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode() && !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
