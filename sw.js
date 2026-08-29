/* 오프라인에서도 열리도록 앱 파일을 캐시에 담아 둔다. 파일을 고치면 CACHE 이름의 숫자를 올린다. */
var CACHE = "eng-words-v6";
var ASSETS = [
  "./",
  "./index.html",
  "./dictionary.js",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./icon-maskable-512.png",
  "./icon-180.png"
];

self.addEventListener("install", function(e){
  /* 파일 하나가 없더라도 설치가 실패하지 않도록 개별로 담는다 (addAll 은 하나라도 실패하면 전체 실패) */
  e.waitUntil(
    caches.open(CACHE).then(function(c){
      return Promise.all(ASSETS.map(function(url){
        return c.add(url)["catch"](function(){ /* 이 파일은 나중에 필요할 때 받는다 */ });
      }));
    }).then(function(){ return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function(e){
  e.waitUntil(
    caches.keys().then(function(keys){
      return Promise.all(keys.map(function(k){ return k === CACHE ? null : caches.delete(k); }));
    }).then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function(e){
  var req = e.request;
  if(req.method !== "GET") return;

  /* 화면 이동은 캐시된 앱 화면으로 (오프라인에서도 바로 열린다) */
  if(req.mode === "navigate"){
    e.respondWith(
      fetch(req)["catch"](function(){ return caches.match("./index.html"); })
    );
    return;
  }

  var sameOrigin = new URL(req.url).origin === self.location.origin;
  if(!sameOrigin) return;   /* 글꼴 등 외부 요청은 그대로 통과 (없으면 기본 글꼴로 대체된다) */

  e.respondWith(
    caches.match(req).then(function(hit){
      if(hit) return hit;
      return fetch(req).then(function(res){
        if(res && res.status === 200){
          var copy = res.clone();
          caches.open(CACHE).then(function(c){ c.put(req, copy); });
        }
        return res;
      });
    })
  );
});
