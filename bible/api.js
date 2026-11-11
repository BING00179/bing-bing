// 화면 ↔ 구글 시트(앱스 스크립트) 연결.
// 시트 쪽 주소는 저장소에 없습니다. 단톡방 링크 뒤 ?s=<배포 아이디> 로 들어와
// 이 휴대폰에 기억됩니다. ?s=preview 는 가짜 서버(이 브라우저에만 기록)로 미리보기.
var Api = (function () {
  var params = new URLSearchParams(location.search);
  var KEY = 'bible.s';
  var s = params.get('s');
  try {
    if (s) localStorage.setItem(KEY, s);
    else s = localStorage.getItem(KEY);
  } catch (e) {}
  if (s && s !== 'preview' && !/^[A-Za-z0-9_-]{20,150}$/.test(s)) s = null;

  var base = s && s !== 'preview' ? 'https://script.google.com/macros/s/' + s + '/exec' : null;

  function unwrap(r) {
    if (!r.ok) throw new Error('연결이 원활하지 않아요 (' + r.status + '). 잠시 뒤 다시 눌러 주세요.');
    return r.json().then(function (j) {
      if (!j.ok) throw new Error(j.error);
      return j.data;
    });
  }
  var real = {
    state: function () { return fetch(base, { cache: 'no-store' }).then(unwrap); },
    call: function (fn, args) {
      return fetch(base, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify({ fn: fn, args: args }) }).then(unwrap);
    },
    calendarUrl: function (h) { return base + '?cal=1&h=' + (Core.alarmHour(h) || Core.DEFAULT_ALARM_HOUR); }
  };

  // ── 미리보기용 가짜 서버: server.gs 와 같은 규칙. ?today=2027-01-05 로 날짜 바꾸기 ──
  var fake = (function () {
    var K = 'bible.preview.db';
    function db() { try { return JSON.parse(localStorage.getItem(K)) || { members: [], records: [] }; } catch (e) { return { members: [], records: [] }; } }
    function put(d) { try { localStorage.setItem(K, JSON.stringify(d)); } catch (e) {} }
    function today() { return params.get('today') || new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10); }
    function state(d) { return { today: today(), members: d.members.slice(), records: d.records.slice(), vapidKey: params.get('vapid') || '' }; }
    var fns = {
      register: function (name) {
        var n = Core.validName(name);
        if (!n) throw new Error('이름은 1~20자로 적어 주세요.');
        var d = db(); if (d.members.indexOf(n) < 0) d.members.push(n); put(d);
        var st = state(d); st.name = n; return st;
      },
      mark: function (name, date, done) {
        if (!Core.portionFor(date)) throw new Error('읽기표에 없는 날짜입니다.');
        if (date > today()) throw new Error('아직 오지 않은 날은 체크할 수 없어요.');
        var d = db();
        if (d.members.indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
        d.records.push([name, date, done ? '완료' : '취소']); put(d); return state(d);
      }
    };
    function later(f) { return new Promise(function (ok) { setTimeout(ok, 150); }).then(f); }
    var blobs = {};
    return {
      state: function () { return later(function () { return state(db()); }); },
      call: function (fn, args) { return later(function () { return fns[fn].apply(null, args); }); },
      calendarUrl: function (h) {
        var H = Core.alarmHour(h) || Core.DEFAULT_ALARM_HOUR;
        if (!blobs[H]) blobs[H] = URL.createObjectURL(new Blob([Core.icsFor(Core.APP_BASE + '?s=preview', H)], { type: 'text/calendar' }));
        return blobs[H];
      }
    };
  })();

  var impl = s === 'preview' ? fake : base ? real : null;
  return {
    ready: !!impl,
    preview: s === 'preview',
    sw: 'sw.js' + (s ? '?s=' + encodeURIComponent(s) : ''),
    state: function () { return impl.state(); },
    call: function (fn) { return impl.call(fn, Array.prototype.slice.call(arguments, 1)); },
    calendarUrl: function (h) { return impl.calendarUrl(h); }
  };
})();

// ── 앱 알림(웹 푸시) ──
var Push = (function () {
  function supported() { return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window; }
  function isIOS() { return /iPhone|iPad|iPod/.test(navigator.userAgent); }
  function standalone() { return navigator.standalone === true || matchMedia('(display-mode: standalone)').matches; }
  function keyBytes(b64) {
    var s = atob(b64.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((b64.length + 3) % 4));
    var a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a;
  }
  function reg() { return navigator.serviceWorker.register(Api.sw).then(function () { return navigator.serviceWorker.ready; }); }

  // 무엇을 안내해야 하는지: 'ok' | 'ios-home' (아이폰은 홈 화면에 추가해야 함) | 'no'
  function status() {
    if (supported()) return 'ok';
    if (isIOS() && !standalone()) return 'ios-home';
    return 'no';
  }
  function on(vapidKey) {
    return Notification.requestPermission().then(function (p) {
      if (p !== 'granted') {
        var err = new Error(p === 'denied' ? '알림이 막혀 있어요. 아래 순서대로 설정에서 허용해 주세요.' : '"허용" 을 눌러야 알림이 와요. 다시 눌러 주세요.');
        err.code = p; // 'denied' (막힘 — 설정에서만 풀 수 있음) / 'default' (창을 그냥 닫음)
        throw err;
      }
      return reg();
    }).then(function (r) {
      return r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(vapidKey) });
    }).then(function (sub) { return sub.endpoint; });
  }
  function off() {
    if (!supported()) return Promise.resolve(null);
    return navigator.serviceWorker.getRegistration(Api.sw).then(function (r) {
      return r && r.pushManager.getSubscription();
    }).then(function (sub) {
      if (!sub) return null;
      var u = sub.endpoint;
      return sub.unsubscribe().then(function () { return u; });
    });
  }
  // 지금 알림 권한: 'granted' | 'denied' | 'default' | '' (지원 안 함)
  function permission() { return 'Notification' in window ? Notification.permission : ''; }
  return { status: status, on: on, off: off, permission: permission };
})();

// ── 홈 화면 설치 ──
// 안드로이드 크롬·삼성 인터넷: 설치 창을 앱이 직접 띄울 수 있음(beforeinstallprompt).
// 아이폰: 앱이 띄울 수 없어서 Safari 공유 버튼 → 홈 화면에 추가 를 안내.
var Install = (function () {
  var deferred = null;
  var listeners = [];
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferred = e;
    // 크롬이 '설치할 수 있다' 고 알림 = 아직 설치 안 됨. 예전에 눌린 '설치했어요' 기록은 지움.
    try { localStorage.removeItem('bible.installed'); } catch (err) {}
    listeners.forEach(function (f) { f(); });
  });
  window.addEventListener('appinstalled', function () {
    deferred = null;
    try { localStorage.setItem('bible.installed', '1'); } catch (e) {}
    listeners.forEach(function (f) { f(); });
  });
  var ua = navigator.userAgent;
  return {
    isKakao: function () { return /KAKAOTALK/i.test(ua); },
    isIOS: function () { return /iPhone|iPad|iPod/.test(ua); },
    isAndroid: function () { return /Android/.test(ua); },
    isSamsung: function () { return /SamsungBrowser/.test(ua); },
    // 갤럭시: 크롬으로 열기 (크롬이 설치 창·알림 허용 창을 가장 잘 띄움). 크롬이 없으면 지금 브라우저에 그대로.
    openInChrome: function () {
      location.href = 'intent://' + location.href.replace(/^https?:\/\//, '') +
        '#Intent;scheme=https;package=com.android.chrome;S.browser_fallback_url=' + encodeURIComponent(location.href) + ';end';
    },
    standalone: function () { return navigator.standalone === true || matchMedia('(display-mode: standalone)').matches; },
    installed: function () {
      if (this.standalone()) return true;
      try { return localStorage.getItem('bible.installed') === '1'; } catch (e) { return false; }
    },
    canPrompt: function () { return !!deferred; },
    prompt: function () {
      var d = deferred; deferred = null;
      d.prompt();
      return d.userChoice.then(function (c) {
        if (c.outcome === 'accepted') { try { localStorage.setItem('bible.installed', '1'); } catch (e) {} }
        return c.outcome === 'accepted';
      });
    },
    onChange: function (f) { listeners.push(f); },
    // 카톡 안 브라우저 → 외부 브라우저 (카카오 비공식 주소, 안 되는 경우가 있어 안내 화면을 같이 보여 줌)
    openExternal: function () {
      if (/Android/.test(ua)) return this.openInChrome();
      location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(location.href);
    }
  };
})();
