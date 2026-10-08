"""가상 계좌 기록 — 세 CSV. 추가만 하고 지우지 않습니다 (§12).

    virtual_trades.csv   체결 한 건 = 한 줄
    virtual_log.csv      결정 한 건 = 한 줄 (낸 것도, 막힌 것도)
    virtual_daily.csv    하루 스냅샷 = 한 줄

보유 현황은 저장하지 않습니다. 체결에서 되감습니다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.virtual_account import VIRTUAL_VERSION, Decision, Fill, Order

TRADES_COLUMNS = ("row_id", "version", "order_id", "date", "code", "name", "side", "tranche",
                  "shares", "price", "fee", "tax", "slippage", "amount", "reason")
LOG_COLUMNS = ("row_id", "version", "date", "code", "name", "action", "gate", "detail",
               "order_id", "order_json")
DAILY_COLUMNS = ("version", "date", "cash", "positions_value", "equity", "day_pnl",
                 "day_pnl_pct", "halted", "n_positions", "kosdaq_close")


class StoreShrank(RuntimeError):
    """기록이 줄어드는 저장을 막습니다."""


def _load(path: Path, columns: tuple) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(columns))
    frame = pd.read_csv(path, dtype={"code": str, "row_id": str, "order_id": str, "version": str},
                        keep_default_na=False)
    for c in columns:
        if c not in frame.columns:
            frame[c] = ""
    return frame[list(columns)]


def _save(frame: pd.DataFrame, path: Path, columns: tuple, key: str) -> None:
    if path.exists():
        기존 = _load(path, columns)
        사라진 = set(기존[key].astype(str)) - set(frame[key].astype(str))
        if len(frame) < len(기존) or 사라진:
            raise StoreShrank(f"{path.name}: 기록 {len(기존):,}건 → {len(frame):,}건. 이 기록은 덧붙이기만 합니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[list(columns)].to_csv(path, index=False, encoding="utf-8-sig")


def _row_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


@dataclass
class Store:
    trades_path: Path
    log_path: Path
    daily_path: Path

    @classmethod
    def default(cls, data_dir: Path) -> "Store":
        data_dir = Path(data_dir)
        return cls(data_dir / "virtual_trades.csv", data_dir / "virtual_log.csv", data_dir / "virtual_daily.csv")

    def load_trades(self) -> pd.DataFrame:
        return _load(self.trades_path, TRADES_COLUMNS)

    def load_log(self) -> pd.DataFrame:
        return _load(self.log_path, LOG_COLUMNS)

    def load_daily(self) -> pd.DataFrame:
        return _load(self.daily_path, DAILY_COLUMNS)

    def append_fills(self, fills: list[Fill]) -> int:
        frame = self.load_trades()
        있는것 = set(frame["order_id"].astype(str))
        새것 = []
        for f in fills:
            if f.order_id in 있는것:
                continue
            row = asdict(f)
            row.update(row_id=_row_id("fill", f.order_id), version=VIRTUAL_VERSION)
            새것.append(row)
        if 새것:
            frame = pd.concat([frame, pd.DataFrame(새것)], ignore_index=True)
            _save(frame, self.trades_path, TRADES_COLUMNS, key="row_id")
        return len(새것)

    def append_decisions(self, decisions: list[Decision],
                         orders: dict[tuple[str, str, str], Order]) -> int:
        frame = self.load_log()
        있는것 = set(frame["row_id"].astype(str))
        새것 = []
        for d in decisions:
            order = None
            if d.action == "주문":
                order = next((o for o in orders.values() if o.code == d.code and o.reason == d.detail), None)
            order_id = order.order_id if order else ""
            rid = _row_id("log", d.date, d.code, d.action, d.gate, d.detail, order_id)
            if rid in 있는것:
                continue
            row = asdict(d)
            row.update(row_id=rid, version=VIRTUAL_VERSION, order_id=order_id,
                       order_json=json.dumps(asdict(order), ensure_ascii=False) if order else "")
            새것.append(row)
        if 새것:
            frame = pd.concat([frame, pd.DataFrame(새것)], ignore_index=True)
            _save(frame, self.log_path, LOG_COLUMNS, key="row_id")
        return len(새것)

    def pending_orders(self, as_of: str) -> list[Order]:
        """주문 낸 날보다 뒤(as_of)에, 아직 체결 줄이 없는 주문."""
        log = self.load_log()
        체결된 = set(self.load_trades()["order_id"].astype(str))
        out: list[Order] = []
        주문들 = log[(log["action"].astype(str) == "주문") & (log["order_json"].astype(str) != "")
                   & (log["date"].astype(str) < as_of)]
        if 주문들.empty:
            return []
        # 주문은 '다음 거래일' 용입니다. 가장 최근 주문일 묶음만 체결 대상이고,
        # 그보다 오래된 미체결(살 수 없었던 것 등)은 다시 시도하지 않습니다.
        마지막날 = str(주문들["date"].astype(str).max())
        for _, r in 주문들[주문들["date"].astype(str) == 마지막날].iterrows():
            if str(r["order_id"]) in 체결된:
                continue
            out.append(Order(**json.loads(str(r["order_json"]))))
        return out

    def upsert_daily(self, row: dict) -> None:
        frame = self.load_daily()
        row = dict(row, version=VIRTUAL_VERSION)
        frame = frame[frame["date"].astype(str) != str(row["date"])]
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True).sort_values("date")
        기존 = _load(self.daily_path, DAILY_COLUMNS)
        if len(frame) < len(기존):
            raise StoreShrank("virtual_daily.csv 가 줄어듭니다")
        self.daily_path.parent.mkdir(parents=True, exist_ok=True)
        frame[list(DAILY_COLUMNS)].to_csv(self.daily_path, index=False, encoding="utf-8-sig")

    def last_daily_before(self, as_of: str) -> dict | None:
        d = self.load_daily()
        d = d[d["date"].astype(str) < as_of]
        if d.empty:
            return None
        r = d.sort_values("date").iloc[-1].to_dict()
        for k in ("cash", "positions_value", "equity", "day_pnl", "day_pnl_pct", "kosdaq_close"):
            r[k] = float(r[k]) if str(r[k]) != "" else float("nan")
        return r
