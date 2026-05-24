const CACHE = 'decidr-v1'
const PRECACHE = [
  '/static/manifest.json',
  '/static/icons/icon.svg',
]

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE))
  )
})

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  )
})

self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/'))
    )
    return
  }
  e.respondWith(
    caches.match(e.request).then(cached =>
      cached || fetch(e.request).then(res => {
        const clone = res.clone()
        caches.open(CACHE).then(c => c.put(e.request, clone))
        return res
      })
    )
  )
})

self.addEventListener('push', e => {
  let data = { title: 'Decidr', body: 'Nuevo mensaje' }
  try {
    if (e.data) {
      data = e.data.json()
    }
  } catch (err) {
    data.body = e.data.text() || 'Nuevo mensaje'
  }
  const opts = {
    body: data.body,
    icon: '/static/icons/icon.svg',
    badge: '/static/icons/icon.svg',
    vibrate: [200, 100, 200],
    data: { room: data.room || '' }
  }
  e.waitUntil(self.registration.showNotification(data.title, opts))
})

self.addEventListener('notificationclick', e => {
  e.notification.close()
  const urlToOpen = '/'
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url === urlToOpen && 'focus' in client) {
          return client.focus()
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen)
      }
    })
  )
})
