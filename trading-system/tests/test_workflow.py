"""예약 실행 설정 검사 — 조용히 죽는 자리를 막습니다.

2026-09-01 부터 2026-09-14 까지 장부에 한 건도 안 쌓였습니다. 원인은
워크플로의 두 단계에만 `working-directory: trading-system` 이 빠진
것이었습니다. 매일 ModuleNotFoundError 로 죽었는데
`continue-on-error: true` 가 그 실패를 숨겨서, 워크플로는 계속
'성공' 으로 찍혔습니다.

    · 스캐너·요약 단계는 전부 working-directory 가 있었습니다
    · 빠진 둘이 하필 **장부 기록**과 **월말 브리핑** 이었습니다
    · 앞으로의 자료를 모으는 일이 2주 동안 통째로 멈춰 있었습니다

코드만 검사하고 설정은 검사하지 않으면 이런 일이 또 생깁니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML 이 없으면 이 검사는 건너뜁니다")

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/stock-scan-kr.yml"


def _steps() -> list[dict]:
    if not WORKFLOW.exists():
        pytest.skip(f"워크플로 파일이 없습니다: {WORKFLOW}")
    문서 = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    작업 = 문서["jobs"]
    return [s for 이름 in 작업 for s in 작업[이름].get("steps", [])]


def _python_steps() -> list[dict]:
    return [s for s in _steps() if "python -m src.cli" in (s.get("run") or "")]


def test_파이썬을_부르는_단계는_전부_폴더를_지정한다():
    """이게 이 파일의 존재 이유입니다."""
    빠진것 = [s.get("name", "(이름 없음)") for s in _python_steps()
            if s.get("working-directory") != "trading-system"]
    assert not 빠진것, (
        "working-directory: trading-system 이 빠진 단계가 있습니다. "
        f"그 단계는 ModuleNotFoundError 로 죽습니다 → {빠진것}"
    )


def test_파이썬을_부르는_단계가_실제로_있다():
    """위 검사가 '단계가 0개라 전부 통과' 로 새지 않게 합니다."""
    assert len(_python_steps()) >= 5


def test_실패를_숨기는_단계는_에러를_남긴다():
    """continue-on-error 를 쓰면 실패해도 워크플로가 초록불입니다.

    그러면 조용히 죽습니다. 최소한 화면에 빨갛게 남겨야 합니다.
    """
    숨기는것 = [s for s in _python_steps() if s.get("continue-on-error")]
    assert 숨기는것, "이 검사가 뜻을 가지려면 그런 단계가 하나는 있어야 합니다"
    안남기는것 = [s.get("name", "(이름 없음)") for s in 숨기는것
              if "::error::" not in (s.get("run") or "")]
    assert not 안남기는것, (
        "continue-on-error 를 쓰면서 ::error:: 를 안 남기는 단계가 있습니다. "
        f"실패해도 아무도 모릅니다 → {안남기는것}"
    )


def test_장부를_기록하는_단계가_있다():
    """장부는 돈이 움직일 통로입니다 (12번). 기록하는 자리가 있어야 합니다."""
    assert any("livetest-record" in (s.get("run") or "") for s in _steps())


def test_장부를_저장소에_올린다():
    """기록해 놓고 안 올리면 다음 실행에서 사라집니다."""
    글 = WORKFLOW.read_text(encoding="utf-8")
    assert "git add trading-system/data/livetest.csv" in 글
