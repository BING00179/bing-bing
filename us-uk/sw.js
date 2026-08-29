/* 매일 영어 단어장 — 서비스 워커
 *
 * 새 버전을 올리면 설치한 분들 기기에서 자동으로 받아 갑니다.
 *   1) 앱을 열면 브라우저가 이 파일을 다시 확인합니다
 *   2) 내용이 바뀌었으면 새 워커를 설치하고 곧바로 넘겨받습니다 (skipWaiting + claim)
 *   3) 화면이 스스로 한 번 새로고침되어 새 버전이 적용됩니다
 * 배포할 때 아래 VERSION 만 바꾸면 됩니다 (python3 bump-version.py).
 */
var VERSION = "2026.08.29-13";
var CACHE = "eng-words-usuk-" + VERSION;
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
  /* 파일 하나가 없더라도 설치가 실패하지 않도록 개별로 담는다 */
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

self.addEventListener("message", function(e){
  if(e.data === "SKIP_WAITING") self.skipWaiting();
  if(e.data === "VERSION" && e.source) e.source.postMessage({ version: VERSION });
});

self.addEventListener("fetch", function(e){
  var req = e.request;
  if(req.method !== "GET") return;
  if(new URL(req.url).origin !== self.location.origin) return;  /* 글꼴 등 외부 요청은 그대로 통과 */

  /* 화면 이동: 인터넷이 되면 항상 최신 화면을, 안 되면 저장해 둔 화면을 */
  if(req.mode === "navigate"){
    e.respondWith(
      fetch(req).then(function(res){
        var copy = res.clone();
        caches.open(CACHE).then(function(c){ c.put("./index.html", copy); });
        return res;
      })["catch"](function(){
        return caches.match("./index.html").then(function(hit){ return hit || caches.match("./"); });
      })
    );
    return;
  }

  /* 나머지 파일: 저장해 둔 것을 바로 주고, 뒤에서 조용히 새 것으로 갈아 둔다 */
  e.respondWith(
    caches.match(req).then(function(hit){
      var live = fetch(req).then(function(res){
        if(res && res.status === 200){
          var copy = res.clone();
          caches.open(CACHE).then(function(c){ c.put(req, copy); });
        }
        return res;
      })["catch"](function(){ return hit; });
      return hit || live;
    })
  );
});
