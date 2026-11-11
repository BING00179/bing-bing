// 웹 푸시 서명(VAPID, ES256) — 앱스 스크립트에는 타원곡선 서명 기능이 없어서
// 순수 자바스크립트로 씁니다. node 시험이 표준 암호 모듈로 결과를 검증합니다
// (test/webpush.test.js). 알림 내용은 보내지 않으므로(빈 푸시) 암호화는 필요 없고,
// 휴대폰의 sw.js 가 그날 분량을 스스로 계산해 보여줍니다.
var WebPush = (function () {
  // ── SHA-256 ──
  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  function sha256(bytes) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var len = bytes.length, total = ((len + 9 + 63) >> 6) << 6;
    var m = new Array(total).fill(0);
    for (var i = 0; i < len; i++) m[i] = bytes[i] & 0xff;
    m[len] = 0x80;
    var bits = len * 8;
    for (i = 0; i < 8; i++) m[total - 1 - i] = Math.floor(bits / Math.pow(2, 8 * i)) & 0xff;
    var w = new Array(64);
    for (var off = 0; off < total; off += 64) {
      for (i = 0; i < 16; i++) w[i] = (m[off + 4 * i] << 24) | (m[off + 4 * i + 1] << 16) | (m[off + 4 * i + 2] << 8) | m[off + 4 * i + 3];
      for (i = 16; i < 64; i++) {
        var a = w[i - 15], b = w[i - 2];
        var s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
        var s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var A = H[0], B = H[1], C = H[2], D = H[3], E = H[4], F = H[5], G = H[6], Hh = H[7];
      for (i = 0; i < 64; i++) {
        var S1 = ((E >>> 6) | (E << 26)) ^ ((E >>> 11) | (E << 21)) ^ ((E >>> 25) | (E << 7));
        var ch = (E & F) ^ (~E & G);
        var t1 = (Hh + S1 + ch + K[i] + w[i]) | 0;
        var S0 = ((A >>> 2) | (A << 30)) ^ ((A >>> 13) | (A << 19)) ^ ((A >>> 22) | (A << 10));
        var mj = (A & B) ^ (A & C) ^ (B & C);
        var t2 = (S0 + mj) | 0;
        Hh = G; G = F; F = E; E = (D + t1) | 0; D = C; C = B; B = A; A = (t1 + t2) | 0;
      }
      H[0] = (H[0] + A) | 0; H[1] = (H[1] + B) | 0; H[2] = (H[2] + C) | 0; H[3] = (H[3] + D) | 0;
      H[4] = (H[4] + E) | 0; H[5] = (H[5] + F) | 0; H[6] = (H[6] + G) | 0; H[7] = (H[7] + Hh) | 0;
    }
    var out = [];
    H.forEach(function (h) { out.push((h >>> 24) & 0xff, (h >>> 16) & 0xff, (h >>> 8) & 0xff, h & 0xff); });
    return out;
  }
  function hmac(key, msg) {
    if (key.length > 64) key = sha256(key);
    var k = key.slice(); while (k.length < 64) k.push(0);
    var ip = k.map(function (x) { return x ^ 0x36; }), op = k.map(function (x) { return x ^ 0x5c; });
    return sha256(op.concat(sha256(ip.concat(msg))));
  }

  // ── 바이트·글자 ──
  function utf8(s) {
    var out = [], str = unescape(encodeURIComponent(s));
    for (var i = 0; i < str.length; i++) out.push(str.charCodeAt(i));
    return out;
  }
  var B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  function b64u(bytes) {
    var s = '', i;
    for (i = 0; i + 2 < bytes.length; i += 3) {
      var n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
      s += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63];
    }
    if (bytes.length - i === 1) { n = bytes[i] << 16; s += B64[n >> 18] + B64[(n >> 12) & 63]; }
    else if (bytes.length - i === 2) { n = (bytes[i] << 16) | (bytes[i + 1] << 8); s += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63]; }
    return s;
  }
  function unb64u(s) {
    var out = [], buf = 0, bits = 0;
    for (var i = 0; i < s.length; i++) {
      var v = B64.indexOf(s[i]); if (v < 0) throw new Error('base64url 아님');
      buf = (buf << 6) | v; bits += 6;
      if (bits >= 8) { bits -= 8; out.push((buf >> bits) & 0xff); }
    }
    return out;
  }
  function toInt(bytes) { var n = 0n; bytes.forEach(function (b) { n = (n << 8n) | BigInt(b); }); return n; }
  function toBytes(n, len) { var out = new Array(len); for (var i = len - 1; i >= 0; i--) { out[i] = Number(n & 0xffn); n >>= 8n; } return out; }

  // ── P-256 ──
  var P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
  var N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
  var G = [0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296n,
           0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5n];
  function mod(a, m) { var r = a % m; return r < 0n ? r + m : r; }
  function inv(a, m) {
    var t = 0n, nt = 1n, r = m, nr = mod(a, m);
    while (nr !== 0n) { var q = r / nr; var x = t - q * nt; t = nt; nt = x; x = r - q * nr; r = nr; nr = x; }
    return mod(t, m);
  }
  // 야코비안 좌표 (역수 계산을 마지막 한 번으로)
  function dbl(p) {
    if (!p) return null;
    var X = p[0], Y = p[1], Z = p[2];
    if (Y === 0n) return null;
    var YY = mod(Y * Y, P), S = mod(4n * X * YY, P), ZZ = mod(Z * Z, P);
    var M = mod(3n * (X - ZZ) * (X + ZZ), P); // a = -3
    var X3 = mod(M * M - 2n * S, P);
    return [X3, mod(M * (S - X3) - 8n * YY * YY, P), mod(2n * Y * Z, P)];
  }
  function add(p, q) {
    if (!p) return q; if (!q) return p;
    var Z1Z1 = mod(p[2] * p[2], P), Z2Z2 = mod(q[2] * q[2], P);
    var U1 = mod(p[0] * Z2Z2, P), U2 = mod(q[0] * Z1Z1, P);
    var S1 = mod(p[1] * q[2] * Z2Z2, P), S2 = mod(q[1] * p[2] * Z1Z1, P);
    if (U1 === U2) return S1 === S2 ? dbl(p) : null;
    var H = mod(U2 - U1, P), R = mod(S2 - S1, P), HH = mod(H * H, P), HHH = mod(H * HH, P), V = mod(U1 * HH, P);
    var X3 = mod(R * R - HHH - 2n * V, P);
    return [X3, mod(R * (V - X3) - S1 * HHH, P), mod(p[2] * q[2] * H, P)];
  }
  function mul(k) {
    var R = null, Q = [G[0], G[1], 1n];
    while (k > 0n) { if (k & 1n) R = add(R, Q); Q = dbl(Q); k >>= 1n; }
    var zi = inv(R[2], P), zi2 = mod(zi * zi, P);
    return [mod(R[0] * zi2, P), mod(R[1] * zi2 * zi, P)];
  }

  function keysFromPrivate(privB64) {
    var d = toInt(unb64u(privB64));
    if (d <= 0n || d >= N) throw new Error('개인키 범위 밖');
    var Q = mul(d);
    return { privateKey: b64u(toBytes(d, 32)), publicKey: b64u([4].concat(toBytes(Q[0], 32), toBytes(Q[1], 32))) };
  }
  // random: 호출할 때마다 다른 글자를 주는 함수 (앱스 스크립트: Utilities.getUuid)
  function newKeys(random) {
    for (;;) {
      var seed = sha256(utf8(random() + random() + random() + random()));
      var d = toInt(seed);
      if (d > 0n && d < N) return keysFromPrivate(b64u(seed));
    }
  }

  // RFC 6979 — 난수 없이 서명용 k 를 정함 (앱스 스크립트에 안전한 난수가 없어서)
  function signES256(privB64, msg) {
    var x = unb64u(privB64), d = toInt(x), h1 = sha256(msg);
    var e = toInt(h1), hb = toBytes(mod(e, N), 32);
    var V = new Array(32).fill(1), Kk = new Array(32).fill(0);
    Kk = hmac(Kk, V.concat([0], x, hb)); V = hmac(Kk, V);
    Kk = hmac(Kk, V.concat([1], x, hb)); V = hmac(Kk, V);
    for (;;) {
      V = hmac(Kk, V);
      var k = toInt(V);
      if (k > 0n && k < N) {
        var r = mod(mul(k)[0], N);
        if (r !== 0n) {
          var s = mod(inv(k, N) * (e + r * d), N);
          if (s !== 0n) return toBytes(r, 32).concat(toBytes(s, 32));
        }
      }
      Kk = hmac(Kk, V.concat([0])); V = hmac(Kk, V);
    }
  }

  function vapidHeader(endpoint, keys, subject, nowSec) {
    var aud = endpoint.match(/^https:\/\/[^\/]+/)[0];
    var head = b64u(utf8(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
    var body = b64u(utf8(JSON.stringify({ aud: aud, exp: nowSec + 12 * 3600, sub: subject })));
    var sig = b64u(signES256(keys.privateKey, utf8(head + '.' + body)));
    return 'vapid t=' + head + '.' + body + '.' + sig + ', k=' + keys.publicKey;
  }

  // 휴대폰 회사들의 알림 서버만 받습니다. 아무 주소나 받으면 우리 서버가
  // 남의 주소로 요청을 보내는 데 쓰일 수 있습니다.
  var HOSTS = [/^fcm\.googleapis\.com$/, /^web\.push\.apple\.com$/, /^updates\.push\.services\.mozilla\.com$/,
    /^[a-z0-9-]+\.notify\.windows\.com$/];
  function allowedEndpoint(u) {
    if (typeof u !== 'string' || u.length > 1000) return false;
    var m = u.match(/^https:\/\/([^\/:?#]+)\//);
    return !!m && HOSTS.some(function (h) { return h.test(m[1]); });
  }

  return { sha256: sha256, hmac: hmac, utf8: utf8, b64u: b64u, keysFromPrivate: keysFromPrivate,
    newKeys: newKeys, signES256: signES256, vapidHeader: vapidHeader, allowedEndpoint: allowedEndpoint };
})();

if (typeof module !== 'undefined') module.exports = WebPush;
