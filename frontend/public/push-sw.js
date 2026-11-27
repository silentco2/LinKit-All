// LinKit All's service worker on a paired phone (docs/phone.md): Angular's app-shell cache, plus
// the push alert. A push carries only {"count": n}; the words come from the phone's own language,
// saved by Settings > Phone when push was switched on.
importScripts('./ngsw-worker.js');

self.addEventListener('push', (event) => {
  let count = 0;
  try {
    count = Number(event.data && event.data.json().count) || 0;
  } catch (e) {
    // not JSON: still say something needs the user
  }
  event.waitUntil(
    (async () => {
      const saved = await (await caches.open('linkit-push')).match('/push-title');
      const title = (saved ? await saved.text() : 'LinKit needs you ({n})').replace('{n}', String(count));
      await self.registration.showNotification(title, { tag: 'linkit-needs-you', icon: 'icons/icon-192.png' });
    })(),
  );
});

self.addEventListener('notificationclick', (event) => {
  if (event.notification.tag !== 'linkit-needs-you') return;
  event.notification.close();
  event.waitUntil(clients.openWindow('/needs-you'));
});
