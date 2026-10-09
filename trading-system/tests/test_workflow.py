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


# ── 2026-10-08 추가 ──────────────────────────────────────────────────
# 위 두 가지를 고친 뒤에도 장부는 한 건도 안 쌓였습니다. 2026-09-24 부터
# 10-05 까지 마감 실행 6건이 전부 '취소' 였습니다. 장부 단계가 29.4분을
# 돌다 **잡 제한 30분**에 걸려 잘렸고, 그 뒤의 '저장소에 올리기' 가
# 건너뛰어졌습니다. 러너는 매번 새로 시작해 시세 저장고가 없으므로
# 1,825종목을 종목당 약 1초(네트워크 + 0.2초 쉼)로 전부 새로 받습니다.
# 일이 30분 넘게 걸리는데 제한이 30분이면 영원히 못 끝납니다.

UNIVERSE = Path(__file__).resolve().parents[1] / "data/universe_kosdaq.txt"
초당_종목당 = 1.2   # 2026-10-05 실측 0.97초 + 여유
여유분 = 15        # 라이브러리 설치·스캐너·업로드 등 나머지 단계(분)


def _job_timeout_minutes() -> int:
    문서 = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    (작업,) = 문서["jobs"].values()
    return int(작업.get("timeout-minutes", 360))


def test_잡_제한시간이_장부_기록에_걸리는_시간보다_길다():
    """장부 단계는 종목 수만큼 시세를 새로 받습니다. 그 시간을 못 덮는
    제한은 '매일 취소' 와 같습니다."""
    if not UNIVERSE.exists():
        pytest.skip(f"종목 목록이 없습니다: {UNIVERSE}")
    종목수 = sum(1 for 줄 in UNIVERSE.read_text(encoding="utf-8").splitlines()
             if 줄.strip() and not 줄.lstrip().startswith("#"))
    필요 = 종목수 * 초당_종목당 / 60 + 여유분
    제한 = _job_timeout_minutes()
    assert 제한 >= 필요, (
        f"timeout-minutes {제한}분 < 필요 {필요:.0f}분 "
        f"({종목수:,}종목 × {초당_종목당}초 + {여유분}분). "
        "장부 단계가 매일 잘립니다 — 2026-09-24~10-05 에 그랬습니다."
    )


# ── 2026-10-08 추가 (둘째) ──────────────────────────────────────────
# 제한 시간을 고치고 보니 벽이 하나 더 있었습니다. 2026-09-28 부터 깃허브가
# 예약 실행을 하루 3번쯤만 띄웁니다(정의는 25번). 시각도 들쭉날쭉해서
# 마감창 15:20~15:40 에 드는 날이 절반뿐입니다 (9/30 15:14, 10/1 15:45,
# 10/6 16:06, 10/7 15:47 — 전부 비켜감). 장부는 (날짜, 종목) 이 같으면
# 건너뛰므로 두 번 돌아도 해가 없습니다. 그러니 장부 단계는 창을 닫지
# 않습니다 — 15:20 이후 그날 아무 실행에서나 적습니다.

def _ledger_step() -> dict:
    (단계,) = [s for s in _steps() if "livetest-record" in (s.get("run") or "")]
    return 단계


def test_장부_단계는_15시40분에_창을_닫지_않는다():
    """20분짜리 창은 예약 실행이 제때 뜬다는 가정입니다. 그 가정이 깨졌습니다."""
    글 = _ledger_step().get("run") or ""
    assert '"$HOUR" -gt 15' in 글, "15시 이후 시간대를 허용하는 조건이 없습니다"
    assert '"$MIN" -le 40' not in 글, (
        "장부 단계가 15:40 에 창을 닫습니다. 예약 실행이 15:41 에 뜨면 그날은 "
        "장부가 비게 됩니다 — 2026-10-01·10-06·10-07 이 그랬습니다."
    )


# ── 2026-10-08 추가 (셋째) — 다섯 번째 벽 ───────────────────────────
# 월말 `value-record` 는 DART 재무 파일(data/fin_kr.csv)이 있어야 하는데
# 러너에는 없고 만드는 단계도 없었습니다. 2026-10-31 에도 "재무 파일이
# 없습니다" 로 끝날 상태였습니다. 그리고 말일이 주말이면 아예 안 돌고,
# 15:20~15:40 창을 비켜가면 또 안 돌았습니다.

def _monthly_step() -> dict:
    (단계,) = [s for s in _steps() if "value-record" in (s.get("run") or "")]
    return 단계


def test_월말_단계는_재무를_먼저_받는다():
    글 = _monthly_step().get("run") or ""
    assert "value-fetch" in 글, "value-fetch 없이 value-record 는 '재무 파일이 없습니다' 로 끝납니다"
    assert 글.index("value-fetch") < 글.index("value-record")


def test_월말_단계는_DART_키를_받는다():
    env = _monthly_step().get("env") or {}
    assert "DART_API_KEY" in env, "secrets.DART_API_KEY 가 단계 env 에 없습니다"


def test_월말_단계는_마지막_평일_판정을_명령에_맡긴다():
    글 = _monthly_step().get("run") or ""
    assert "month-end-check" in 글
    assert 'TOMORROW" = "01"' not in 글, "내일이 1일 로만 보면 말일이 주말인 달은 안 돕니다"
    assert '"$MIN" -le 40' not in 글, "15:40 에 창을 닫으면 예약이 늦게 뜬 날은 못 돕니다"


def test_월말_브리핑은_한_달에_한_번만():
    글 = _monthly_step().get("run") or ""
    assert "monthly_review_" in 글 and ".done" in 글, "표시 파일 없이는 두 번 돌면 텔레그램이 두 번 갑니다"


def test_월말_단계는_후보_전체를_남긴다():
    assert "--candidates-out data/value_candidates.csv" in (_monthly_step().get("run") or "")


def test_커밋_단계가_새_파일들을_올린다():
    글 = WORKFLOW.read_text(encoding="utf-8")
    for 파일 in ("trading-system/data/value_candidates.csv",
                "trading-system/data/monthly_review_"):
        assert f"git add {파일}" in 글, f"{파일} 를 커밋하지 않으면 다음 실행에서 사라집니다"


def test_표시_파일은_후보_기록이_성공했을_때만_쓴다():
    """value-record 가 실패했는데 .done 이 써지면 그 달은 재시도가 없고 후보 파일이 빕니다."""
    글 = _monthly_step().get("run") or ""
    assert "ok=0" in 글, "value-record 실패를 기억하는 자리가 없습니다"
    assert '[ "$ok" = 1 ]' in 글, ".done 쓰기가 value-record 성공 조건에 걸려 있지 않습니다"
    assert 글.index('[ "$ok" = 1 ]') < 글.index('> "$DONE"'), ".done 쓰기가 조건 밖에 있습니다"
    assert 글.index("ok=0") < 글.index("src.cli monthly-review"), "ok=0 은 value-record 실패 처리여야 합니다"


# ── 가상 계좌 단계 ──────────────────────────────────────────────────
def _virtual_step() -> dict:
    (단계,) = [s for s in _steps() if "virtual-update" in (s.get("run") or "")]
    return 단계


def test_가상_계좌_단계가_있고_웹을_갱신한다():
    글 = _virtual_step().get("run") or ""
    assert "virtual-update --web" in 글


def test_가상_계좌_단계는_장부_뒤에_온다():
    이름들 = [s.get("name", "") for s in _steps()]
    장부 = next(i for i, n in enumerate(이름들) if "실시간 검증" in n)
    가상 = next(i for i, n in enumerate(이름들) if "가상 계좌" in n)
    assert 장부 < 가상, "가상 계좌는 그날 장부(후보 추적)가 끝난 뒤에 돕니다"


def test_가상_계좌_단계는_창을_닫지_않는다():
    글 = _virtual_step().get("run") or ""
    assert '"$HOUR" -gt 15' in 글 and '"$MIN" -le 40' not in 글


def test_가상_계좌_기록을_커밋한다():
    글 = WORKFLOW.read_text(encoding="utf-8")
    assert "trading-system/data/virtual_" in 글
