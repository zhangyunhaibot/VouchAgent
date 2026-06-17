"""Vouch 信任层状态快照 —— 看板与 x402 feed 的统一数据源。

合成一份 web/vouch_state.json：
  agents   : 从链上拉的信誉榜（按信誉降序）—— 当前信誉/押金/单价/状态，准确权威
  hires    : 从链上拉的雇佣单 —— 托管/已结算/里程碑/状态
  events   : 本地账本的事件流（claim/verdict/hire/settle/refund + 逐票理由/tx）
  treasury : 本地账本的 Treasury 损益（佣金+查询费−证据成本−gas，含净利润）

链上部分用 get_*_count 遍历读取（合约提供 agent/hire 计数；claim 无计数方法，
故 claim/verdict 走账本事件流）。看板定时刷新或 x402 feed 被买时重新生成。

环境：REGISTRY_HASH、VERIFIER_KEY（或 READ_KEY，任意账户私钥，仅作只读查询）。
运行：venv/bin/python vouch_state.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import vouch_chain  # noqa: E402
import vouch_ledger  # noqa: E402

STATE_FILE = Path(__file__).resolve().parent.parent / "web" / "vouch_state.json"
READ_KEY = os.environ.get("VERIFIER_KEY") or os.environ.get("READ_KEY")
STATUS_NAME = {0: "active", 1: "paused", 2: "banned", 3: "expired"}
HIRE_STATUS_NAME = {0: "active", 1: "settled", 2: "refunded"}


def snapshot(write: bool = True) -> dict:
    """从链上 + 账本合成一份完整状态快照。"""
    if not READ_KEY:
        raise RuntimeError("缺少 VERIFIER_KEY/READ_KEY（只读查询用）")

    # 1. 链上信誉榜。
    agents = []
    for i in range(vouch_chain.get_agent_count(READ_KEY)):
        a = vouch_chain.get_agent(READ_KEY, i)
        agents.append(
            {
                "id": i,
                "reputation": a["reputation"],
                "stake": a["stake"],
                "price_per_day": a["price_per_day"],
                "status": a["status"],
                "status_name": STATUS_NAME.get(a["status"], "?"),
                "lock_until": a["lock_until"],
            }
        )
    agents.sort(key=lambda x: -(x["reputation"] or 0))

    # 2. 链上雇佣单。
    hires = []
    for i in range(vouch_chain.get_hire_count(READ_KEY)):
        h = vouch_chain.get_hire(READ_KEY, i)
        hires.append(
            {
                "id": i,
                "provider": h["provider"],
                "total": h["total"],
                "escrow": h["escrow"],
                "settled": h["settled"],
                "milestones_passed": h["milestones_passed"],
                "milestones_total": h["milestones_total"],
                "status": h["status"],
                "status_name": HIRE_STATUS_NAME.get(h["status"], "?"),
            }
        )

    # 3. 账本事件流 + Treasury。
    ledger = vouch_ledger.read()

    state = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "registry_hash": os.environ.get("REGISTRY_HASH", ""),
        "agents": agents,
        "hires": hires,
        "events": ledger["events"],
        "treasury": ledger["treasury"],
    }
    if write:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return state


if __name__ == "__main__":
    s = snapshot()
    print(f"已写 {STATE_FILE}")
    print(f"  agents={len(s['agents'])} hires={len(s['hires'])} events={len(s['events'])}")
    print(f"  treasury={s['treasury']}")
