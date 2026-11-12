// 화면 ↔ 구글 시트(앱스 스크립트) 연결.
// 시트 쪽 주소는 저장소에 없습니다. 단톡방 링크 뒤 ?s=<배포 아이디> 로 들어와
// 이 휴대폰에 기억됩니다. ?s=preview 는 가짜 서버(이 브라우저에만 기록)로 미리보기.
var Api = (function () {
  var params = new URLSearchParams(location.search);
  var KEY = 'bible.s';
  var s = params.get('s');
  // ?s=demo 는 리더·임원 시연용: 2027년 1월 중순처럼, 예시 회원과 기록이 들어 있는 가짜 서버
  var DEMO = s === 'demo';
  if (DEMO) s = 'preview';
  // 링크의 열쇠(s)·모임(g)은 서버에 한 번 연결된 뒤에야 이 폰에 기억함.
  // (잘린 링크로 열었다가 원래 연결까지 잃는 일을 막음 — 연결이 안 되면 예전 연결로 다시 시도)
  var GKEY = 'bible.g', g = '', prevS = null, prevG = '', fromLink = false;
  try { prevS = localStorage.getItem(KEY); prevG = localStorage.getItem(GKEY) || ''; } catch (e) {}
  function okS(x) { return !!x && /^[A-Za-z0-9_-]{20,150}$/.test(x); }
  function okG(x) { return /^[a-z0-9]{0,20}$/.test(x || ''); }
  if (s && s !== 'preview') { fromLink = true; g = params.get('g') || ''; }
  else if (!s) { s = prevS; g = prevG; }
  if (s && s !== 'preview' && !okS(s)) { s = fromLink && okS(prevS) ? prevS : null; g = prevG; fromLink = false; }
  if (!okG(g)) g = '';
  if (!okS(prevS)) prevS = null;
  // 관리자 폰: 시트 메뉴 '관리자 폰 등록' 링크(&admin=열쇠)를 한 번 열면 이 폰에 기억. 주소창에서는 바로 지움.
  var AKEY = 'bible.admin', adminKey = params.get('admin');
  if (adminKey && /^[a-f0-9]{32}$/.test(adminKey)) {
    try { localStorage.setItem(AKEY, adminKey); } catch (e) {}
    // 카톡·삼성 인터넷은 곧 크롬으로 넘기므로 주소에 열쇠를 남겨 둠 (지우면 크롬에 열쇠 없는 주소가 감)
    var willMove = /KAKAOTALK|SamsungBrowser/i.test(navigator.userAgent) &&
      !(navigator.standalone === true || matchMedia('(display-mode: standalone)').matches);
    if (!willMove) try { params.delete('admin'); history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : '')); } catch (e) {}
  }
  function admin() { try { return localStorage.getItem(AKEY) || ''; } catch (e) { return ''; } }

  var base = s && s !== 'preview' ? 'https://script.google.com/macros/s/' + s + '/exec' : null;
  function remember() { if (fromLink) try { localStorage.setItem(KEY, s); localStorage.setItem(GKEY, g); fromLink = false; } catch (e) {} }
  function friendly(e) {
    if (e && /fetch|network|load failed/i.test(e.message || '')) return new Error('연결 안 됨 · 링크가 잘렸거나 인터넷이 끊겼을 수 있어요');
    return e;
  }

  function unwrap(r) {
    if (!r.ok) throw new Error('연결이 원활하지 않아요 (' + r.status + '). 잠시 뒤 다시 눌러 주세요.');
    return r.json().then(function (j) {
      if (!j.ok) throw new Error(j.error);
      return j.data;
    });
  }
  var real = {
    state: function () {
      function once() { return fetch(base + (g ? '?g=' + g : ''), { cache: 'no-store' }).then(unwrap); }
      return once().then(function (d) { remember(); return d; }, function (e) {
        // 링크로 처음 열었는데 연결이 안 되면: 이 폰에 예전 연결이 있으면 그걸로 (잘린 링크 대비)
        if (fromLink && prevS && prevS !== s) {
          s = prevS; g = prevG; fromLink = false; base = 'https://script.google.com/macros/s/' + s + '/exec';
          return once();
        }
        throw friendly(e);
      });
    },
    call: function (fn, args) {
      return fetch(base, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify({ g: g, fn: fn, args: args }) }).then(unwrap).catch(function (e) { throw friendly(e); });
    },
    calendarUrl: function (h) { return base + '?cal=1&h=' + (Core.alarmHour(h) || Core.DEFAULT_ALARM_HOUR) + (g ? '&g=' + g : ''); }
  };

  // ── 미리보기용 가짜 서버: server.gs 와 같은 규칙. ?today=2027-01-05 로 날짜 바꾸기 ──
  var fake = (function () {
    var K = 'bible.preview.db';
    if (DEMO) K = 'bible.demo.db';
    function db() {
      var d = null;
      try { d = JSON.parse(localStorage.getItem(K)); } catch (e) {}
      return d || (DEMO ? demoSeed() : { members: [], records: [] });
    }
    // 시연용 예시: 1월 1일~어제까지 사람마다 다르게 읽고·필사한 기록
    function demoSeed() {
      var people = [['김은혜', 1, 0], ['박소망', 0.85, 0.6], ['이믿음', 0.6, 0], ['최사랑', 0, 0.9], ['정기쁨', 0.95, 0.95]];
      var d = { members: [], records: [], joins: [] }, end = Core.addDays(today(), -1);
      people.forEach(function (x, i) {
        d.members.push(x[0]);
        if (!x[1]) d.joins.push([x[0], '1', '읽기', '나감']);
        if (x[2]) d.joins.push([x[0], '1', '필사', '참여']);
        var k = 0;
        for (var day = Core.FIRST_START; day <= end; day = Core.addDays(day, 1), k++) {
          if (x[1] && ((k * 7 + i * 3) % 20) / 20 < x[1]) d.records.push([x[0], day, '완료']);
          if (x[2] && ((k * 5 + i) % 20) / 20 < x[2]) d.records.push([x[0], day, '필사완료']);
        }
      });
      return d;
    }
    function put(d) { try { localStorage.setItem(K, JSON.stringify(d)); } catch (e) {} }
    function today() { return params.get('today') || (DEMO ? '2027-01-15' : new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10)); }
    // ?term2=2028-01-03 이면 2기가 열린 상태로 미리보기
    function terms() { var t = [['1', Core.FIRST_START]]; if (params.get('term2')) t.push(['2', params.get('term2')]); return Core.termsFrom(t); }
    function openTerm() { var tn = Core.termsNow(terms(), today()); return tn.next || tn.cur; }
    function state(d) { return { today: today(), members: d.members.slice(), records: d.records.slice(), vapidKey: params.get('vapid') || '',
      terms: terms(), joins: (d.joins || []).slice(), groupName: params.get('gname') || '' }; }
    function joinTerm(d, name, team, on) {
      var t = openTerm(); d.joins = d.joins || []; team = team || '읽기'; on = on !== false;
      var now = Core.participants(t, [name], d.joins, team).length > 0;
      if (now !== on) d.joins.push([name, String(t.n), team, on ? '참여' : '나감']);
    }
    var fns = {
      register: function (name) {
        var n = Core.validName(name);
        if (!n) throw new Error('이름은 1~20자로 적어 주세요.');
        var d = db(); if (d.members.indexOf(n) < 0) d.members.push(n); joinTerm(d, n); put(d);
        var st = state(d); st.name = n; return st;
      },
      join: function (name, team, on) { var d = db(); joinTerm(d, name, team, on); put(d); return state(d); },
      mark: function (name, date, done, kind) {
        var pre = kind === '필사' ? '필사' : '';
        if (!terms().some(function (t) { return Core.makePlan(t.start).portionFor(date); })) throw new Error('읽기표에 없는 날짜입니다.');
        if (date > today()) throw new Error('아직 오지 않은 날은 체크할 수 없어요.');
        var d = db();
        if (d.members.indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
        d.records.push([name, date, pre + (done ? '완료' : '취소')]); put(d); return state(d);
      }
    };
    function later(f) { return new Promise(function (ok) { setTimeout(ok, 150); }).then(f); }
    var blobs = {};
    return {
      state: function () { return later(function () { return state(db()); }); },
      call: function (fn, args) { return later(function () { return fns[fn].apply(null, args); }); },
      calendarUrl: function (h) {
        var H = Core.alarmHour(h) || Core.DEFAULT_ALARM_HOUR;
        if (!blobs[H]) blobs[H] = URL.createObjectURL(new Blob([Core.makePlan(openTerm().start).icsFor(Core.APP_BASE + '?s=preview', H)], { type: 'text/calendar' }));
        return blobs[H];
      }
    };
  })();

  var impl = s === 'preview' ? fake : base ? real : null;
  return {
    ready: !!impl,
    preview: s === 'preview', demo: DEMO, group: g,
    admin: function () { return base ? admin() : ''; },
    adminOff: function () { try { localStorage.removeItem(AKEY); } catch (e) {} },
    sw: 'sw.js' + (s ? '?s=' + encodeURIComponent(s) + (g ? '&g=' + g : '') : ''),
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
        var err = new Error(p === 'denied' ? '🔕 알림 비활성 · 아래 순서대로 허용' : '알림 허용 필요 · 다시 눌러 "허용"');
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
