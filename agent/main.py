"""RWA 多智能体预言机 —— 入口。

运行协调器一轮：DeepSeek 协调器用工具调用【自主编排】
抓取 → Judge 交叉验证 → 上链 → Risk 评估 → 更新链上信誉分。

用法：
  python main.py            处理全部资产（黄金/BTC/欧元，含多笔链上交易，较慢）
  python main.py --quick    仅处理 1 个资产（快速演示）
  python main.py --loop     自主循环：每隔一段时间自动跑一轮（按 Ctrl+C 停止）
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from coordinator import run_cycle

# 自主循环模式下，每轮之间的间隔（秒）。
LOOP_INTERVAL = 300

# 状态快照写到 web/ 供 Dashboard 读取。
STATE_PATH = Path(__file__).resolve().parent.parent / "web" / "oracle_state.json"


def _write_state(tools) -> None:
    snapshot = tools.snapshot()
    snapshot["updated_at"] = int(time.time())
    snapshot["contract_hash"] = os.environ.get("CONTRACT_HASH", "")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"\n💾 状态快照已写入 {STATE_PATH.relative_to(STATE_PATH.parent.parent)}")


def run_one(max_assets: int | None) -> None:
    tools = run_cycle(max_assets=max_assets)
    _write_state(tools)
    print("\n=== 本轮链上动作汇总 ===")
    if not tools.actions:
        print("  （本轮无链上动作）")
    for a in tools.actions:
        action_cn = {"submit": "提交数据", "score": "更新信誉分"}.get(a["action"], a["action"])
        print(f"  · {action_cn:8} {a['asset']}")


def main() -> None:
    load_dotenv()
    quick = "--quick" in sys.argv
    loop = "--loop" in sys.argv
    max_assets = 1 if quick else None

    print("=== RWA 多智能体预言机 · 协调器启动 ===")
    if quick:
        print("（快速演示模式：仅处理 1 个资产）")
    print()

    if not loop:
        run_one(max_assets)
        return

    # 自主循环：持续监控。
    print(f"（自主循环模式：每 {LOOP_INTERVAL // 60} 分钟一轮，Ctrl+C 停止）\n")
    cycle = 1
    while True:
        print(f"\n──────── 第 {cycle} 轮 ────────")
        try:
            run_one(max_assets)
        except Exception as exc:  # noqa: BLE001 — 单轮失败不应中断整个守护循环
            print(f"  ⚠️  本轮出错（已跳过）：{exc}")
        cycle += 1
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
