"""Vouch Keeper —— 到期自动执行器。

链上合约没有定时器，无法在到期时刻自己执行结算/退款/退押金（设计文档 §11.7）。
keeper 是验证网络的一项定时任务，周期性扫描链上状态、在到期时刻代为发起交易：

  1. 到期的雇佣单（now ≥ ends_at 且仍 active）：读链上已通过里程碑数 →
     达标（准确率 ≥ 阈值）则 settle_hire 放款给 Provider；不达标则 refund_hire 退款罚没。
     （履约的"判定"由验证网络 sla_evaluator 先行完成并写上链；keeper 只负责"执行"。）
  2. 到期的入驻（now ≥ lock_until 且仍有押金）：release_expired_stake 把押金退回原付款地址，
     体验上即"押金到期自动返还"。

keeper 用合约 verifier 账户运行（settle/refund 需 verifier 权限；release 任意人可调）。

环境变量：REGISTRY_HASH、VERIFIER_KEY、（可选）SLA_THRESHOLD。
运行：venv/bin/python keeper.py [--force] [--dry-run]
  --force    忽略 ends_at/lock_until 的"未到期"检查，立即处理（demo 用：testnet 真实时间戳
             下里程碑要等真实天数才到期，演示时用 --force 模拟"到期时刻 keeper 触发"）。
  --dry-run  只扫描打印计划动作，不发交易。
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import vouch_chain  # noqa: E402

VERIFIER_KEY = os.environ["VERIFIER_KEY"]
SLA_THRESHOLD = float(os.environ.get("SLA_THRESHOLD", "0.6"))


def _now_ms() -> int:
    # testnet 区块时间戳 ≈ 真实时间（毫秒）。
    return int(time.time() * 1000)


def sweep_hires(now: int, force: bool, dry_run: bool) -> list[dict]:
    """扫描所有雇佣单，到期的按链上履约记录执行 settle / refund。"""
    actions: list[dict] = []
    n = vouch_chain.get_hire_count(VERIFIER_KEY)
    print(f"\n[keeper] 扫描 {n} 张雇佣单…")
    for hid in range(n):
        h = vouch_chain.get_hire(VERIFIER_KEY, hid)
        if h["status"] != 0:
            print(f"  hire#{hid}: 已结束（status={h['status']}），跳过")
            continue
        expired = now >= (h["ends_at"] or 0)
        if not expired and not force:
            print(f"  hire#{hid}: 未到期（ends_at={h['ends_at']}），跳过")
            continue
        total_ms = h["milestones_total"] or 1
        accuracy = (h["milestones_passed"] or 0) / total_ms
        is_pass = accuracy >= SLA_THRESHOLD
        op = "settle" if is_pass else "refund"
        print(
            f"  hire#{hid}: 到期 | 里程碑 {h['milestones_passed']}/{h['milestones_total']}"
            f"（准确率 {accuracy:.0%}，阈值 {SLA_THRESHOLD:.0%}）→ {op}"
        )
        if dry_run:
            actions.append({"hire": hid, "op": op, "tx": None, "dry_run": True})
            continue
        if is_pass:
            res = vouch_chain.settle_hire(VERIFIER_KEY, hid)
        else:
            res = vouch_chain.refund_hire(VERIFIER_KEY, hid)
        print(f"      ↳ {op} 上链: {res['tx']}")
        actions.append({"hire": hid, "op": op, "tx": res["tx"]})
    return actions


def sweep_stakes(now: int, force: bool, dry_run: bool) -> list[dict]:
    """扫描所有 agent，到期入驻释放押金（押金到期自动返还）。"""
    actions: list[dict] = []
    n = vouch_chain.get_agent_count(VERIFIER_KEY)
    print(f"\n[keeper] 扫描 {n} 个 agent 的押金到期…")
    for aid in range(n):
        ag = vouch_chain.get_agent(VERIFIER_KEY, aid)
        if not ag["stake"]:
            print(f"  agent#{aid}: 无押金可释放，跳过")
            continue
        expired = now >= (ag["lock_until"] or 0)
        if not expired and not force:
            print(f"  agent#{aid}: 未到期（lock_until={ag['lock_until']}），跳过")
            continue
        print(f"  agent#{aid}: 入驻到期 → release_expired_stake（退押金 {ag['stake']}）")
        if dry_run:
            actions.append({"agent": aid, "op": "release", "tx": None, "dry_run": True})
            continue
        res = vouch_chain.release_expired_stake(VERIFIER_KEY, aid)
        print(f"      ↳ release 上链: {res['tx']}")
        actions.append({"agent": aid, "op": "release", "tx": res["tx"]})
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Vouch keeper：到期自动执行 settle/refund/release")
    parser.add_argument("--force", action="store_true", help="忽略未到期检查，立即处理（demo）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划动作，不发交易")
    parser.add_argument("--skip-stakes", action="store_true", help="本轮不扫押金到期")
    args = parser.parse_args()

    now = _now_ms()
    print(f"=== Vouch Keeper | now={now} | force={args.force} | dry_run={args.dry_run} ===")
    hire_actions = sweep_hires(now, args.force, args.dry_run)
    stake_actions = [] if args.skip_stakes else sweep_stakes(now, args.force, args.dry_run)

    print(
        f"\n=== keeper 完成：处理 {len(hire_actions)} 张到期雇佣单"
        f" + {len(stake_actions)} 笔到期押金 ==="
    )


if __name__ == "__main__":
    main()
