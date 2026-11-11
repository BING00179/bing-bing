// 아침 알림을 받아 띄우는 곳. 서버는 내용 없는 알림만 보내고(암호화가 필요 없게),
// 그날 읽을 곳은 여기서 core.js 로 계산합니다.
importScripts('core.js');

var SEARCH = self.location.search; // '?s=…' — 알림을 누르면 이 주소로 앱을 엶

self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });

function todayKST() { return new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10); }

function morningNotice(today) {
  var p = Core.portionFor(today);
  return {
    title: '📖 오늘 읽을 곳',
    body: p ? Core.portionLabel(p) : '함께 읽는 성경',
    tag: 'bible-' + today
  };
}

self.addEventListener('push', function (e) {
  var n = morningNotice(todayKST());
  // 아이폰은 알림을 받으면 반드시 화면에 띄워야 합니다 (안 띄우면 알림 권한이 끊김)
  e.waitUntil(self.registration.showNotification(n.title, {
    body: n.body, tag: n.tag, icon: 'icon-192.png', badge: 'icon-192.png', data: { url: './' + SEARCH }
  }));
});

self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var url = new URL((e.notification.data && e.notification.data.url) || './', self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].url.indexOf(self.registration.scope) === 0 && 'focus' in list[i]) return list[i].focus();
    }
    return self.clients.openWindow(url);
  }));
});

if (typeof module !== 'undefined') module.exports = { morningNotice: morningNotice };

// 화면 파일을 저장해 두었다가 인터넷이 끊겨도 앱이 열리게 (같은 주소의 파일만, 최신 우선).
// 크롬은 이 처리가 있어야 앱이 '설치 창' 을 직접 띄울 수 있습니다.
var CACHE = 'bible-v1';
self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  // cache: 'no-cache' — 휴대폰이 붙잡아 둔 옛 파일 대신 매번 GitHub 에 새것인지 확인 (열 때마다 최신)
  e.respondWith(fetch(req, { cache: 'no-cache' }).then(function (res) {
    if (res.ok) { var copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
    return res;
  }).catch(function () {
    return caches.match(req, { ignoreSearch: req.mode === 'navigate' }).then(function (hit) {
      return hit || new Response('인터넷 연결을 확인해 주세요.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    });
  }));
});
