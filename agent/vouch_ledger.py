"""Vouch 本地账本 —— 事件流 + Treasury 损益。

链上合约存的是"当前状态"（信誉/押金/雇佣单余额），但有些东西链上读不到或
不该上链：对抗投票的逐票理由、x402 付费证据的成本与 tx、每笔交易的 gas、
平台累计佣金收入。这些由 agent 在运行时记进本地账本，供 x402 feed 卖出 +
看板展示「对抗投票流」和「Treasury 自赚自花」。

账本文件 web/vouch_ledger.json：
  events   : 时间倒序的事件流（claim / verdict / hire / settle / refund / evidence）
  treasury : 累计损益（commission 佣金收入 + query_fees 查询费 − evidence_cost 证据成本 − gas_cost）

时间戳用本机时间（中国时区 UTC+8）。所有写入原子追加，不删历史。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

LEDGER_FILE = Path(__file__).resolve().parent.parent / "web" / "vouch_ledger.json"

_EMPTY = {
    "events": [],
    "treasury": {
        "commission": 0,  # 雇佣结算抽取的佣金（X402 最小单位）
        "query_fees": 0,  # x402 卖信誉/裁决/feed 的查询费收入
        "evidence_cost": 0,  # x402 买 premium 证据的支出
        "gas_cost_cspr": 0.0,  # 链上 gas 支出（CSPR，估算）
    },
}


def _load() -> dict:
    if LEDGER_FILE.exists():
        try:
            data = json.loads(LEDGER_FILE.read_text())
            # 容错：补齐缺失键。
            for k, v in _EMPTY.items():
                data.setdefault(k, v if not isinstance(v, dict) else dict(v))
            for k, v in _EMPTY["treasury"].items():
                data["treasury"].setdefault(k, v)
            return data
        except json.JSONDecodeError:
            pass
    return {"events": [], "treasury": dict(_EMPTY["treasury"])}


def _save(data: dict) -> None:
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _now() -> str:
    # 本机时间即中国时间（UTC+8）。
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_event(kind: str, **fields) -> None:
    """追加一条事件（最新在前）。"""
    data = _load()
    event = {"kind": kind, "at": _now(), **fields}
    data["events"].insert(0, event)
    data["events"] = data["events"][:200]  # 只留最近 200 条，避免文件无限膨胀
    _save(data)


def add_treasury(
    commission: int = 0,
    query_fee: int = 0,
    evidence_cost: int = 0,
    gas_cspr: float = 0.0,
) -> None:
    """累计 Treasury 损益。"""
    data = _load()
    t = data["treasury"]
    t["commission"] += commission
    t["query_fees"] += query_fee
    t["evidence_cost"] += evidence_cost
    t["gas_cost_cspr"] = round(t["gas_cost_cspr"] + gas_cspr, 4)
    _save(data)


def read() -> dict:
    """读取整个账本（含派生的净利润）。"""
    data = _load()
    t = data["treasury"]
    # 净利润（X402 口径）= 佣金 + 查询费 − 证据成本（gas 单独以 CSPR 计）。
    t["net_profit"] = t["commission"] + t["query_fees"] - t["evidence_cost"]
    return data
