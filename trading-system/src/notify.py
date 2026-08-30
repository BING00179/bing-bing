"""텔레그램 알림.

봇 토큰과 채팅 ID 는 반드시 환경변수로 넘깁니다.
코드나 config.json 에 적어두고 깃허브에 올리면 즉시 탈취당합니다.

    export TELEGRAM_BOT_TOKEN="123456:AAA..."
    export TELEGRAM_CHAT_ID="123456789"

봇 만드는 법: 텔레그램에서 @BotFather 에게 /newbot → 토큰 발급.
채팅 ID 확인: 봇에게 아무 말이나 보낸 뒤
  https://api.telegram.org/bot<토큰>/getUpdates 를 열어 chat.id 확인.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096   # 텔레그램 1건 길이 제한


class TelegramNotConfigured(RuntimeError):
    """토큰이나 채팅 ID 가 환경변수에 없을 때."""


def _credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise TelegramNotConfigured(
            "TELEGRAM_BOT_TOKEN 과 TELEGRAM_CHAT_ID 환경변수를 설정해 주세요. "
            "(.env.example 참고)"
        )
    return token, chat_id


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """길이 제한에 맞춰 줄 단위로 나눕니다."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:            # 한 줄이 제한보다 긴 예외적 경우
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def send(text: str, *, timeout: int = 15, dry_run: bool = False) -> bool:
    """텔레그램으로 메시지를 보냅니다. 성공하면 True."""
    if dry_run:
        print("[dry-run] 텔레그램 전송 생략:\n" + text)
        return True

    token, chat_id = _credentials()
    url = f"{API_BASE}/bot{token}/sendMessage"
    ok = True
    for chunk in split_message(text):
        payload = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"}
        ).encode()
        request = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode())
                if not body.get("ok"):
                    print(f"[텔레그램] 전송 실패: {body}")
                    ok = False
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            # 알림 실패가 스캐너 자체를 죽이면 안 되므로 잡아서 보고만 합니다.
            print(f"[텔레그램] 전송 오류: {exc}")
            ok = False
    return ok
