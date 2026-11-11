// 푸시 서명(ES256) 시험 — node 의 표준 암호 모듈로 우리 서명을 검증합니다.
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const W = require('../webpush.js');

const b64u = (buf) => Buffer.from(buf).toString('base64url');

test('sha256 은 표준과 같다', () => {
  for (const s of ['', 'abc', '가나다', 'x'.repeat(1000)]) {
    const want = crypto.createHash('sha256').update(s, 'utf8').digest('hex');
    assert.equal(Buffer.from(W.sha256(W.utf8(s))).toString('hex'), want);
  }
});

test('HMAC-SHA256 은 표준과 같다', () => {
  const key = W.utf8('키'.repeat(40)); // 64바이트 넘는 키도
  const want = crypto.createHmac('sha256', Buffer.from(key)).update('메시지').digest('hex');
  assert.equal(Buffer.from(W.hmac(key, W.utf8('메시지'))).toString('hex'), want);
});

test('공개키는 표준 ECDH 가 만든 것과 같다', () => {
  const d = crypto.randomBytes(32);
  const ecdh = crypto.createECDH('prime256v1');
  ecdh.setPrivateKey(d);
  const keys = W.keysFromPrivate(b64u(d));
  assert.equal(keys.publicKey, b64u(ecdh.getPublicKey()));
});

test('서명을 node 가 검증한다 (여러 번)', () => {
  for (let i = 0; i < 5; i++) {
    const d = crypto.randomBytes(32);
    const keys = W.keysFromPrivate(b64u(d));
    const msg = 'header.payload-' + i;
    const sig = Buffer.from(W.signES256(keys.privateKey, W.utf8(msg)));
    assert.equal(sig.length, 64);
    const pub = Buffer.from(keys.publicKey, 'base64url');
    const key = crypto.createPublicKey({
      key: { kty: 'EC', crv: 'P-256', x: b64u(pub.subarray(1, 33)), y: b64u(pub.subarray(33, 65)) },
      format: 'jwk',
    });
    assert.ok(crypto.verify('sha256', Buffer.from(msg), { key, dsaEncoding: 'ieee-p1363' }, sig), 'verify ' + i);
    // 글자 하나 바꾸면 실패해야 함
    assert.ok(!crypto.verify('sha256', Buffer.from(msg + 'x'), { key, dsaEncoding: 'ieee-p1363' }, sig));
  }
});

test('새 키는 매번 다르고 형식이 맞다', () => {
  let n = 0;
  const rnd = () => crypto.randomUUID() + (n++);
  const a = W.newKeys(rnd), b = W.newKeys(rnd);
  assert.notEqual(a.privateKey, b.privateKey);
  assert.equal(Buffer.from(a.publicKey, 'base64url').length, 65);
  assert.equal(Buffer.from(a.privateKey, 'base64url').length, 32);
});

test('VAPID 헤더: aud 는 알림 서버 주소, 12시간 유효, 검증 가능', () => {
  const keys = W.keysFromPrivate(b64u(crypto.randomBytes(32)));
  const now = 1_800_000_000;
  const h = W.vapidHeader('https://web.push.apple.com/QGh1abc', keys, 'https://example.org/app/', now);
  const m = h.match(/^vapid t=([^,]+), k=(.+)$/);
  assert.ok(m, h);
  assert.equal(m[2], keys.publicKey);
  const [hd, pl, sg] = m[1].split('.');
  assert.deepEqual(JSON.parse(Buffer.from(hd, 'base64url')), { typ: 'JWT', alg: 'ES256' });
  const p = JSON.parse(Buffer.from(pl, 'base64url'));
  assert.equal(p.aud, 'https://web.push.apple.com');
  assert.equal(p.exp, now + 12 * 3600);
  assert.equal(p.sub, 'https://example.org/app/');
  const pub = Buffer.from(keys.publicKey, 'base64url');
  const key = crypto.createPublicKey({ key: { kty: 'EC', crv: 'P-256', x: b64u(pub.subarray(1, 33)), y: b64u(pub.subarray(33, 65)) }, format: 'jwk' });
  assert.ok(crypto.verify('sha256', Buffer.from(hd + '.' + pl), { key, dsaEncoding: 'ieee-p1363' }, Buffer.from(sg, 'base64url')));
});

test('알림 서버 주소는 알려진 곳만 받는다 (아무 주소로 요청 보내기 방지)', () => {
  assert.ok(W.allowedEndpoint('https://fcm.googleapis.com/fcm/send/abc'));
  assert.ok(W.allowedEndpoint('https://web.push.apple.com/QGh1'));
  assert.ok(W.allowedEndpoint('https://updates.push.services.mozilla.com/wpush/v2/x'));
  assert.ok(!W.allowedEndpoint('http://fcm.googleapis.com/x'));
  assert.ok(!W.allowedEndpoint('https://evil.example/fcm.googleapis.com'));
  assert.ok(!W.allowedEndpoint('https://fcm.googleapis.com.evil.example/x'));
  assert.ok(!W.allowedEndpoint(null));
});
