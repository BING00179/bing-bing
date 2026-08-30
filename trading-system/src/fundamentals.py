"""기업 기본 정보 — 시가총액 · PER · PBR · 업종.

신호가 왜 나왔는지 볼 때 "이 회사가 어떤 회사인가"도 같이 보이면
판단이 쉬워집니다. 코드만 보고는 알 수 없으니까요.

두 곳에서 가져옵니다.
  pykrx              한국거래소 공식. 시가총액·PER·PBR
  FinanceDataReader  종목명·업종

⚠️ PER·PBR 은 참고용입니다. 적자 기업은 PER 이 아예 없고, 업종마다
   적정 수준이 완전히 달라서 숫자만으로 싸다·비싸다를 말할 수 없습니다.
   이 시스템은 추세추종이라 매수 판단에 PER 을 쓰지 않습니다.
   화면에 함께 보여줄 뿐입니다.

조회에 실패해도 스캔은 그대로 진행됩니다. 기본 정보는 부가 정보라
없다고 매매 판단이 달라지지 않습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Fundamentals:
    code: str
    name: str = ""
    sector: str = ""          # 업종
    market_cap: float = 0.0   # 시가총액 (원)
    per: float | None = None
    pbr: float | None = None
    shares: float = 0.0       # 상장주식수

    @property
    def market_cap_label(self) -> str:
        if self.market_cap <= 0:
            return ""
        trillion = self.market_cap / 1e12
        if trillion >= 1:
            return f"{trillion:,.1f}조"
        return f"{self.market_cap / 1e8:,.0f}억"

    @property
    def size_label(self) -> str:
        """시가총액 규모. 대형주는 갭이 잘 안 나므로 참고가 됩니다."""
        if self.market_cap <= 0:
            return ""
        cap = self.market_cap
        if cap >= 5e12:
            return "대형주"
        if cap >= 1e12:
            return "중형주"
        if cap >= 3e11:
            return "중소형주"
        return "소형주"


def _recent_business_day(days_back: int = 0) -> str:
    """pykrx 조회용 YYYYMMDD. 주말이면 직전 금요일로 당깁니다."""
    day = date.today() - timedelta(days=days_back)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y%m%d")


def fetch_bulk(codes: list[str]) -> dict[str, Fundamentals]:
    """여러 종목의 기본 정보를 한 번에 가져옵니다.

    pykrx 는 날짜별로 전 종목을 한 번에 주므로, 종목마다 따로
    조회하는 것보다 훨씬 빠릅니다.
    """
    wanted = set(codes)
    out = {code: Fundamentals(code=code) for code in wanted}

    _fill_from_pykrx(out, wanted)
    _fill_from_fdr(out, wanted)
    return out


def _fill_from_pykrx(out: dict[str, Fundamentals], wanted: set[str]) -> None:
    try:
        from pykrx import stock  # noqa: PLC0415
    except ImportError:
        return

    # 오늘 데이터가 아직 없을 수 있어 며칠 거슬러 올라가며 시도합니다.
    for back in range(0, 6):
        day = _recent_business_day(back)
        try:
            cap = stock.get_market_cap(day)
            fundamental = stock.get_market_fundamental(day)
        except Exception:  # noqa: BLE001 - 조회 실패는 부가 정보 누락으로만 처리
            continue
        if cap is None or cap.empty:
            continue

        for code in wanted:
            item = out[code]
            if code in cap.index:
                row = cap.loc[code]
                item.market_cap = float(row.get("시가총액", 0) or 0)
                item.shares = float(row.get("상장주식수", 0) or 0)
            if fundamental is not None and code in fundamental.index:
                row = fundamental.loc[code]
                per = float(row.get("PER", 0) or 0)
                pbr = float(row.get("PBR", 0) or 0)
                item.per = per if per > 0 else None      # 적자면 0 으로 옵니다
                item.pbr = pbr if pbr > 0 else None
        return


def _fill_from_fdr(out: dict[str, Fundamentals], wanted: set[str]) -> None:
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
    except ImportError:
        return
    try:
        listing = fdr.StockListing("KRX")
    except Exception:  # noqa: BLE001
        return
    if listing is None or listing.empty:
        return

    lower = {str(c).strip().lower(): c for c in listing.columns}
    code_col = lower.get("code") or lower.get("symbol")
    if code_col is None:
        return
    name_col = lower.get("name")
    sector_col = lower.get("sector") or lower.get("industry")

    listing = listing.copy()
    listing[code_col] = listing[code_col].astype(str).str.zfill(6)
    subset = listing[listing[code_col].isin(wanted)]

    for row in subset.itertuples(index=False):
        values = dict(zip(subset.columns, row))
        code = str(values[code_col]).zfill(6)
        item = out.get(code)
        if item is None:
            continue
        if name_col and values.get(name_col):
            item.name = str(values[name_col])
        if sector_col and values.get(sector_col):
            item.sector = str(values[sector_col])
