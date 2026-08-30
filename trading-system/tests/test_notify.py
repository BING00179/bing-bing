import pytest

from src.notify import MAX_MESSAGE_CHARS, TelegramNotConfigured, send, split_message


def test_short_message_is_not_split():
    assert split_message("안녕") == ["안녕"]


def test_long_message_is_split_within_limit():
    text = "\n".join(f"{i}번 줄" for i in range(3000))
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_MESSAGE_CHARS for c in chunks)
    assert "".join(chunks) == text


def test_single_line_longer_than_limit_is_hard_split():
    text = "x" * (MAX_MESSAGE_CHARS * 2 + 10)
    chunks = split_message(text)
    assert all(len(c) <= MAX_MESSAGE_CHARS for c in chunks)
    assert "".join(chunks) == text


def test_send_without_credentials_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(TelegramNotConfigured):
        send("테스트")


def test_dry_run_does_not_need_credentials(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert send("테스트 메시지", dry_run=True) is True
    assert "테스트 메시지" in capsys.readouterr().out
