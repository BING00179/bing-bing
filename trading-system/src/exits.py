"""어떻게 하면 될까 — 나가는 규칙을 바꿔 보는 자리.

지금까지 우리는 "안 된다" 만 여섯 번 확인했습니다. PF 0.779, t 1.95.
그런데 그 숫자들은 **신호 + 손절 + 익절 + 보유기간 + 비용** 을 한
덩어리로 잰 것입니다. 어디가 문제인지는 말해 주지 않습니다.

우리기술이 그 이야기를 합니다. 시스템은 2018-02-01, 671원에 그 종목을
**찾아냈습니다.** 나중에 29,300원까지 갔습니다. 그런데 17번 사고 팔아서
14번을 정확히 -3.35% 에 잘렸습니다. 고르는 눈이 문제가 아니라
**파는 손이 문제였을 수 있습니다.**

이 모듈은 그 가정을 검사합니다. 같은 신호를 그대로 두고 **나가는 규칙만**
바꿔 봅니다.

    ① 며칠 들고 있어야 하나      20일에 끊은 게 이른 건 아니었나
    ② 손절폭을 얼마로            3% 는 첫날에 절반을 자릅니다
    ③ 나간 뒤에 얼마나 더 갔나    놓친 상승이 얼마인가

⚠️ 여기서 나오는 숫자는 **탐색이지 검증이 아닙니다.** 같은 자료를 놓고
조합을 여러 개 돌려 제일 좋은 걸 고르면, 그건 그 자료에 맞춘 것입니다.
여기서 답을 찾으면 **앞으로의 자료로 다시 확인해야** 합니다. 그러라고
장부를 만들어 둔 것입니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# 들고 있는 날 수 후보. 지금 규칙은 20일에서 끊습니다.
HOLDS = (5, 10, 20, 40, 60, 90, 120)

# 손절폭 후보. 지금 규칙은 3% 입니다.
STOPS = (3.0, 5.0, 8.0, 12.0, 20.0)

# 익절 목표 후보. 0 은 "목표 없음"(지금 백테스트 설정) 입니다.
#
# 사장님이 물으신 것 — "일정 목표 금액에 닿으면 20일 전에도 팔아야
# 하지 않나". 맞는 질문이고, 지금 백테스트에는 그 규칙이 없습니다
# (take_profit_pct = 0). 반면 장부에는 +10/+20/+35 로 들어가 있습니다.
# 같은 시스템이 두 규칙으로 돌고 있었습니다. 그래서 재봅니다.
TARGETS = (0.0, 10.0, 20.0, 35.0)

MIN_SAMPLE = 30          # 이보다 적으면 판정하지 않습니다


@dataclass
class Paths:
    """신호 하나 = 한 줄. 진입 시가를 100 으로 놓은 뒤의 길."""
    entry_date: pd.DatetimeIndex     # 신호 수만큼
    code: np.ndarray
    high: np.ndarray                 # (신호 수, 최대일수) 진입시가 대비 %
    low: np.ndarray
    close: np.ndarray
    alive: np.ndarray                # 그날 자료가 있는가 (bool)

    def __len__(self) -> int:
        return len(self.code)


def build_paths(frames: dict[str, pd.DataFrame],
                signals: dict[str, pd.DatetimeIndex],
                max_days: int = max(HOLDS)) -> Paths:
    """신호마다 '산 다음 날들' 을 표로 펴 놓습니다.

    신호는 D일 종가로 나고 매수는 D+1일 시가입니다. 백테스트와 같은
    규칙이라야 비교가 됩니다. 미래를 당겨쓰지 않도록, 진입일보다 앞의
    날은 아예 담지 않습니다.
    """
    dates: list[pd.Timestamp] = []
    codes: list[str] = []
    highs: list[np.ndarray] = []
    lows: list[np.ndarray] = []
    closes: list[np.ndarray] = []
    alives: list[np.ndarray] = []

    for code, when in signals.items():
        daily = frames.get(code)
        if daily is None or len(daily) < 2 or len(when) == 0:
            continue
        pos = daily.index.get_indexer(pd.DatetimeIndex(when))
        pos = pos[pos >= 0]
        entry = pos + 1                       # D+1 시가에 산다
        entry = entry[entry < len(daily)]
        if len(entry) == 0:
            continue

        o = daily["open"].to_numpy(dtype=float)
        h = daily["high"].to_numpy(dtype=float)
        l = daily["low"].to_numpy(dtype=float)
        c = daily["close"].to_numpy(dtype=float)
        n = len(daily)

        for i in entry:
            base = o[i]
            if not np.isfinite(base) or base <= 0:
                continue
            end = min(i + max_days, n)
            길이 = end - i
            폭 = lambda arr: (arr[i:end] / base - 1.0) * 100.0
            채움 = lambda v: np.concatenate([v, np.full(max_days - 길이, np.nan)])
            highs.append(채움(폭(h)))
            lows.append(채움(폭(l)))
            closes.append(채움(폭(c)))
            살아 = np.zeros(max_days, dtype=bool)
            살아[:길이] = True
            alives.append(살아)
            dates.append(daily.index[i])
            codes.append(code)

    if not codes:
        빈 = np.zeros((0, max_days))
        return Paths(pd.DatetimeIndex([]), np.array([], dtype=object),
                     빈, 빈, 빈, 빈.astype(bool))

    return Paths(
        entry_date=pd.DatetimeIndex(dates),
        code=np.array(codes, dtype=object),
        high=np.vstack(highs), low=np.vstack(lows),
        close=np.vstack(closes), alive=np.vstack(alives),
    )


# ────────────────── ① 며칠 들고 있어야 하나 ──────────────────

@dataclass
class HoldRow:
    days: int
    mean: float              # 신호 종목 평균 (%)
    market: float            # 같은 날 아무 종목이나 샀을 때 평균 (%)
    excess: float            # 차이 — 이게 진짜 숫자입니다
    win_rate: float
    t_stat: float
    count: int

    @property
    def passes(self) -> bool:
        """미리 정해 둔 합격선: 표본 30건 이상, t ≥ 2.0."""
        return self.count >= MIN_SAMPLE and self.t_stat >= 2.0


def hold_curve(paths: Paths, market: pd.DataFrame,
               holds: tuple[int, ...] = HOLDS) -> list[HoldRow]:
    """손절도 익절도 없이 N일 들고만 있으면 어떻게 되나.

    20일에서 끊는 지금 규칙이 이른 것인지 늦은 것인지를 봅니다.
    N 이 커질수록 초과수익이 계속 늘면, 우리가 일찍 나온 것입니다.
    """
    rows: list[HoldRow] = []
    if len(paths) == 0:
        return rows

    for n in holds:
        if n > paths.close.shape[1]:
            continue
        끝 = paths.close[:, n - 1]
        있음 = np.isfinite(끝)
        기준 = _market_at(market, paths.entry_date, n)
        있음 &= np.isfinite(기준)
        if 있음.sum() < MIN_SAMPLE:
            continue
        값, 기준값 = 끝[있음], 기준[있음]
        차 = 값 - 기준값
        표준편차 = float(차.std(ddof=1))
        t = float(차.mean() / (표준편차 / np.sqrt(len(차)))) if 표준편차 > 0 else 0.0
        rows.append(HoldRow(
            days=n, mean=float(값.mean()), market=float(기준값.mean()),
            excess=float(차.mean()), win_rate=float((값 > 0).mean() * 100.0),
            t_stat=t, count=int(있음.sum()),
        ))
    return rows


def _market_at(market: pd.DataFrame, dates: pd.DatetimeIndex, n: int) -> np.ndarray:
    """같은 날 전 종목 평균. 없으면 nan (0 으로 채우지 않습니다)."""
    col = f"fwd{n}"
    if market is None or market.empty or col not in market:
        return np.full(len(dates), np.nan)
    return market[col].reindex(dates).to_numpy(dtype=float)


# ────────────────── ② 손절폭을 얼마로 ──────────────────

@dataclass
class ExitRow:
    stop_pct: float
    target_pct: float        # 0 = 목표 없음
    hold_days: int
    mean: float              # 비용 뺀 평균 수익 (%)
    win_rate: float
    stopped_pct: float       # 손절로 끝난 비율
    stopped_day1_pct: float  # 그중 진입 첫날에 잘린 비율
    target_hit_pct: float    # 목표에 닿아서 끝난 비율
    profit_factor: float
    count: int


def exit_grid(paths: Paths, stops: tuple[float, ...] = STOPS,
              holds: tuple[int, ...] = HOLDS,
              targets: tuple[float, ...] = TARGETS,
              cost_pct: float = 0.51) -> pd.DataFrame:
    """손절폭 × 익절목표 × 보유일수 조합마다 결과를 냅니다.

    나가는 길이 셋입니다 — 손절선에 닿거나, 목표에 닿거나, 기간이 다 차거나.
    셋 중 **먼저 오는 것**으로 끝냅니다.

    ⚠️ 손절과 목표가 같은 날에 둘 다 닿으면 **손절 쪽으로 봅니다.** 일봉만
    보면 그날 어느 쪽이 먼저였는지 알 수 없습니다. 모르는 것을 유리하게
    가정하면 백테스트만 좋아지고 실제 돈은 그대로 잃습니다.

    비용 0.51% 는 슬리피지 0.15%×2 + 수수료 0.015%×2 + 거래세 0.18% 입니다.
    """
    if len(paths) == 0:
        return pd.DataFrame()

    아주큼 = np.iinfo(np.int32).max
    rows: list[ExitRow] = []

    for stop in stops:
        선 = -abs(stop)
        손절닿음 = (paths.low <= 선) & paths.alive
        손절날 = np.where(손절닿음.any(axis=1), 손절닿음.argmax(axis=1), 아주큼)

        for target in targets:
            if target > 0:
                목표닿음 = (paths.high >= target) & paths.alive
                목표날 = np.where(목표닿음.any(axis=1), 목표닿음.argmax(axis=1), 아주큼)
            else:
                목표날 = np.full(len(paths), 아주큼)

            for n in holds:
                if n > paths.close.shape[1]:
                    continue
                마지막 = _last_alive(paths.alive, n)
                쓸수있음 = 마지막 >= 0
                if 쓸수있음.sum() < MIN_SAMPLE:
                    continue

                잘림 = 손절날 <= 마지막
                # 같은 날이면 손절 쪽 — 모르는 것을 유리하게 보지 않습니다.
                익절 = (목표날 <= 마지막) & (목표날 < 손절날)

                결과 = np.where(
                    잘림 & ~익절, 선,
                    np.where(익절, target,
                             paths.close[np.arange(len(paths)),
                                         np.maximum(마지막, 0)]),
                )
                결과 = 결과[쓸수있음] - cost_pct
                잘림있음 = (잘림 & ~익절)[쓸수있음]
                익절있음 = 익절[쓸수있음]

                번것 = 결과[결과 > 0].sum()
                잃은것 = -결과[결과 < 0].sum()
                pf = float(번것 / 잃은것) if 잃은것 > 0 else float("inf")
                첫날잘림 = int((손절날[쓸수있음][잘림있음] == 0).sum())
                rows.append(ExitRow(
                    stop_pct=stop, target_pct=target, hold_days=n,
                    mean=float(결과.mean()),
                    win_rate=float((결과 > 0).mean() * 100.0),
                    stopped_pct=float(잘림있음.mean() * 100.0),
                    stopped_day1_pct=float(첫날잘림 / max(잘림있음.sum(), 1) * 100.0),
                    target_hit_pct=float(익절있음.mean() * 100.0),
                    profit_factor=pf, count=int(쓸수있음.sum()),
                ))
    return pd.DataFrame([r.__dict__ for r in rows])


def _last_alive(alive: np.ndarray, n: int) -> np.ndarray:
    """N일 창 안에서 자료가 있는 마지막 날. 하나도 없으면 -1."""
    창 = alive[:, :n]
    있음 = 창.any(axis=1)
    마지막 = 창.shape[1] - 1 - np.argmax(창[:, ::-1], axis=1)
    return np.where(있음, 마지막, -1)


# ────────────────── ③ 나간 뒤에 얼마나 더 갔나 ──────────────────

def missed_upside(paths: Paths, stop_pct: float, hold_days: int,
                  look_days: int = 120) -> dict:
    """손절이나 기간만료로 나간 뒤, 그 종목이 얼마나 더 올랐나.

    우리기술이 여기서 걸립니다. 나가고 나서 크게 올랐다면 나가는 규칙이
    돈을 버린 것입니다. 나가고 나서 더 빠졌다면 나간 게 옳았던 것입니다.
    """
    if len(paths) == 0:
        return {}
    선 = -abs(stop_pct)
    닿음 = (paths.low <= 선) & paths.alive
    첫날 = np.where(닿음.any(axis=1), 닿음.argmax(axis=1), np.iinfo(np.int32).max)
    마지막 = _last_alive(paths.alive, hold_days)
    나간날 = np.where(첫날 <= 마지막, 첫날, 마지막)

    쓸수있음 = (마지막 >= 0) & (나간날 >= 0)
    if 쓸수있음.sum() < MIN_SAMPLE:
        return {}

    끝 = min(look_days, paths.high.shape[1])
    나중최고 = np.full(len(paths), np.nan)
    for i in np.flatnonzero(쓸수있음):
        뒤 = paths.high[i, 나간날[i] + 1:끝]
        뒤 = 뒤[np.isfinite(뒤)]
        if len(뒤):
            나중최고[i] = 뒤.max()

    나간값 = np.where(첫날 <= 마지막, 선,
                    paths.close[np.arange(len(paths)), np.maximum(마지막, 0)])
    볼수있음 = 쓸수있음 & np.isfinite(나중최고)
    if 볼수있음.sum() < MIN_SAMPLE:
        return {}

    더간것 = 나중최고[볼수있음] - 나간값[볼수있음]
    return {
        "표본": int(볼수있음.sum()),
        "손절로_나간_비율": float((첫날 <= 마지막)[볼수있음].mean() * 100.0),
        "나간_뒤_더_오른_비율": float((더간것 > 0).mean() * 100.0),
        "나간_뒤_10퍼_넘게_오른_비율": float((더간것 > 10).mean() * 100.0),
        "나간_뒤_평균_추가상승": float(더간것.mean()),
        "나간_뒤_중앙값_추가상승": float(np.median(더간것)),
        "본_기간": 끝,
    }


# ────────────────── 읽을 수 있게 ──────────────────

def report(curve: list[HoldRow], grid: pd.DataFrame, missed: dict,
           now_stop: float = 3.0, now_hold: int = 20) -> str:
    """숫자가 아니라 '그래서 뭘 바꾸면 되나' 를 씁니다."""
    줄 = ["🔧 나가는 규칙을 바꿔 보면 — 어떻게 하면 될까", ""]
    줄 += [f"   지금 규칙: 손절 {now_stop:g}% / 최대 {now_hold}일 보유", ""]

    줄 += ["① 며칠 들고 있어야 하나 (손절·익절 없이 그냥 들고만)", ""]
    if not curve:
        줄 += ["   자료가 모자라 판정하지 않습니다.", ""]
    else:
        줄 += ["   보유    신호평균   시장평균   차이(초과)    t     표본"]
        for r in curve:
            표 = "  ← 기준 통과" if r.passes else ""
            줄.append(f"   {r.days:3d}일   {r.mean:+7.2f}%  {r.market:+7.2f}%  "
                      f"{r.excess:+7.2f}%  {r.t_stat:5.2f}  {r.count:6,d}{표}")
        줄 += ["", "   " + _hold_lesson(curve, now_hold), ""]

    줄 += ["② 손절폭을 바꾸면 (비용 0.51% 뺀 값)", ""]
    if curve and not any(r.passes for r in curve):
        줄 += ["   ⚠️ ①에서 우위가 확인되지 않았습니다. 그러면 아래 표에서 성적이",
               "      좋아 보이는 조합은 **우리 신호가 좋아서가 아니라 그냥 시장이",
               "      올라서** 그런 것일 수 있습니다. 손절을 넓히면 시장 상승을 더",
               "      담게 되니 PF 는 올라갑니다. 그건 우위가 아닙니다.", ""]
    if grid.empty:
        줄 += ["   자료가 모자라 판정하지 않습니다.", ""]
    else:
        줄 += _grid_lines(grid)
        줄 += ["", "   " + _grid_lesson(grid, now_stop, now_hold), ""]

    줄 += ["③ 나간 뒤에 얼마나 더 갔나", ""]
    if not missed:
        줄 += ["   자료가 모자라 판정하지 않습니다.", ""]
    else:
        줄 += [f"   지금 규칙으로 나간 {missed['표본']:,}건을 "
               f"{missed['본_기간']}일까지 따라가 봤습니다.",
               f"     나간 뒤 더 오른 것          {missed['나간_뒤_더_오른_비율']:.1f}%",
               f"     나간 뒤 10% 넘게 오른 것    {missed['나간_뒤_10퍼_넘게_오른_비율']:.1f}%",
               f"     평균 추가 상승             {missed['나간_뒤_평균_추가상승']:+.2f}%p",
               "", "   " + _missed_lesson(missed), ""]

    줄 += ["", "⚠️ 여기 숫자는 **탐색이지 검증이 아닙니다.**",
           "   같은 자료로 조합을 여러 개 돌려 제일 좋은 걸 골랐으니,",
           "   그 자료에 맞춘 것일 수 있습니다. 바꾸기로 정하면 그때부터",
           "   앞으로의 자료로 다시 확인해야 합니다 (장부가 그 일을 합니다)."]
    return "\n".join(줄)


def _hold_lesson(curve: list[HoldRow], now_hold: int) -> str:
    통과 = [r for r in curve if r.passes]
    지금 = next((r for r in curve if r.days == now_hold), None)
    끝 = curve[-1]
    if not 통과:
        return ("어느 보유기간에서도 기준(t ≥ 2.0)을 넘지 못했습니다. "
                "나가는 규칙을 손봐도 안 된다는 뜻입니다 — 신호를 바꿔야 합니다.")
    최고 = max(통과, key=lambda r: r.excess)
    if 지금 is not None and 최고.days > now_hold and 최고.excess > 지금.excess:
        return (f"{최고.days}일까지 들고 있을 때가 제일 좋습니다 "
                f"(초과 {최고.excess:+.2f}%, t {최고.t_stat:.2f}). "
                f"지금 {now_hold}일에서 끊는 것은 **이른 것으로 보입니다.**")
    if 최고.days < now_hold:
        return (f"{최고.days}일이 제일 좋습니다. 지금 {now_hold}일은 "
                f"**오래 들고 있는 쪽**입니다.")
    return f"지금 {now_hold}일 근처가 제일 낫습니다. 여기는 문제가 아닙니다."


def _grid_lines(grid: pd.DataFrame) -> list[str]:
    """조합이 백 개가 넘습니다. 전부 찍으면 아무것도 안 보입니다.

    그래서 **목표별로 제일 나은 조합 한 줄씩**만 보여줍니다. 사장님이
    물으신 것이 "목표를 켜면 나아지나" 이므로, 그 비교가 보여야 합니다.
    """
    줄 = ["   목표     제일 나은 조합      평균     승률   목표도달   잘린비율    PF"]
    있는목표 = sorted(grid["target_pct"].unique())
    전체최고 = grid["profit_factor"].max()
    for tgt in 있는목표:
        칸 = grid[grid["target_pct"] == tgt]
        r = 칸.sort_values("profit_factor", ascending=False).iloc[0]
        이름 = "없음  " if tgt == 0 else f"+{tgt:g}%  "
        표 = "  ←" if r["profit_factor"] == 전체최고 else ""
        줄.append(
            f"   {이름:6s}  손절{r['stop_pct']:3.0f}% {int(r['hold_days']):3d}일   "
            f"{r['mean']:+6.2f}%  {r['win_rate']:5.1f}%   "
            f"{r['target_hit_pct']:5.1f}%    {r['stopped_pct']:5.1f}%  "
            f"{r['profit_factor']:5.3f}{표}"
        )
    줄 += ["", "   (조합 전부는 output/kr_exit_grid.csv 에 있습니다)"]
    return 줄


def _grid_lesson(grid: pd.DataFrame, now_stop: float, now_hold: int) -> str:
    best = grid.sort_values("profit_factor", ascending=False).iloc[0]
    if best["profit_factor"] < 1.0:
        return ("어느 조합도 PF 1.0 을 넘지 못했습니다. 비용까지 넣으면 "
                "**전부 돈을 잃는 쪽**입니다. 나가는 규칙 문제가 아닙니다.")

    목표이름 = ("없음" if best["target_pct"] == 0
              else f"+{best['target_pct']:g}%")
    앞 = (f"제일 나은 조합은 손절 {best['stop_pct']:g}% / 목표 {목표이름} / "
          f"{int(best['hold_days'])}일 보유 — PF {best['profit_factor']:.3f}.")

    목표없음 = grid[grid["target_pct"] == 0]
    목표있음 = grid[grid["target_pct"] > 0]
    if 목표없음.empty or 목표있음.empty:
        return 앞
    없음최고 = float(목표없음["profit_factor"].max())
    있음최고 = float(목표있음["profit_factor"].max())
    if 있음최고 > 없음최고:
        뒤 = (f" 목표를 켠 쪽이 낫습니다 (PF {있음최고:.3f} vs {없음최고:.3f}). "
              "일정 이익에 닿으면 파는 규칙이 도움이 된다는 뜻입니다.")
    elif 없음최고 > 있음최고:
        뒤 = (f" 목표를 끄는 쪽이 낫습니다 (PF {없음최고:.3f} vs {있음최고:.3f}). "
              "목표를 두면 더 갈 종목이 거기서 끊깁니다.")
    else:
        뒤 = " 목표를 켜나 끄나 차이가 없습니다."
    return 앞 + 뒤


def _missed_lesson(missed: dict) -> str:
    큰것 = missed["나간_뒤_10퍼_넘게_오른_비율"]
    if 큰것 >= 30.0:
        return (f"나간 뒤 10% 넘게 오른 것이 {큰것:.0f}% 입니다. "
                "**나가는 손이 돈을 버리고 있습니다.** 더 들고 가는 쪽을 봐야 합니다.")
    if 큰것 <= 15.0:
        return (f"나간 뒤 크게 오른 것은 {큰것:.0f}% 뿐입니다. "
                "나간 판단은 대체로 옳았습니다. 문제는 다른 데 있습니다.")
    return (f"나간 뒤 10% 넘게 오른 것이 {큰것:.0f}% 입니다. "
            "한쪽으로 말하기 어렵습니다 — 더 봐야 합니다.")
