"""Vouch 雇佣托管端到端闭环 demo。

把雇佣托管全链路由 agent 自主跑通：
  Consumer 托管资金雇佣 Provider → 验证网络按客观 SLA 评估履约 → 裁决上链
  → keeper 到期结算（达标放款 / 不达标退款罚没）→ 读回资金与信誉变化。

两种场景对照（信任层的核心价值 = 两头都不能作弊）：
  honest（默认）：Provider 诚实履约（各里程碑报真实价）→ SLA 达标 → settle 放款 + 信誉↑
  fail        ：Provider 摆烂（谎报虚高 + 掉线）→ SLA 不达标 → refund 退款 + 罚没押金 + 信誉↓

环境变量（agent/.env + 运行时）：
  DEEPSEEK_API_KEY  验证网络 LLM
  REGISTRY_HASH     TrustRegistry 地址
  CONSUMER_KEY      Consumer 私钥（持 X402 用于托管 + CSPR gas）
  VERIFIER_KEY      验证网络私钥（合约 verifier，记录履约 + 结算）
  AGENT_ID          被雇佣的 Provider agent id（默认 0）
  TOPIC             资产（默认 XAU/USD）
运行：venv/bin/python hire_cycle.py [--scenario honest|fail] [--days N] [--milestones N]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from judge import judge_asset  # noqa: E402
from sla_evaluator import evaluate_sla  # noqa: E402
import vouch_chain  # noqa: E402
import vouch_ledger  # noqa: E402

COMMISSION_BPS = 1000  # 与合约一致：10%
GAS_PER_TX_CSPR = 2.0  # 单笔链上交易 gas 粗估（CSPR），用于 Treasury 成本侧

CONSUMER_KEY = os.environ["CONSUMER_KEY"]
VERIFIER_KEY = os.environ["VERIFIER_KEY"]
AGENT_ID = int(os.environ.get("AGENT_ID", "0"))
TOPIC = os.environ.get("TOPIC", "XAU/USD")


def _provider_quotes(scenario: str, real: float, milestones: int) -> list[float | None]:
    """构造 Provider 在各里程碑的产出报价。"""
    if scenario == "honest":
        # 诚实：围绕真实价的正常波动，全部应判准确。
        wobble = (1.0, 1.001, 0.999, 1.0008, 0.9992)
        return [round(real * wobble[i % len(wobble)], 4) for i in range(milestones)]
    # 摆烂：谎报虚高 + 掉线（None），应判不达标。
    pattern: list[float | None] = [round(real * 1.15, 4), None, round(real * 1.12, 4)]
    return [pattern[i % len(pattern)] for i in range(milestones)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Vouch 雇佣托管端到端 demo")
    parser.add_argument("--scenario", choices=["honest", "fail"], default="honest")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--milestones", type=int, default=3)
    args = parser.parse_args()

    print(
        f"\n=== Vouch 雇佣托管闭环 | 资产 {TOPIC} | Provider agent#{AGENT_ID}"
        f" | 场景 {args.scenario} ===\n"
    )

    # 0. 读 Provider 链上单价，算托管总额。
    ag0 = vouch_chain.get_agent(VERIFIER_KEY, AGENT_ID)
    price = ag0["price_per_day"] or 0
    total = price * args.days
    print(
        f"① Provider 单价 {price}/天 × {args.days} 天 = 托管 {total}"
        f"（当前信誉 {ag0['reputation']}, 押金 {ag0['stake']}）"
    )

    # 1. Consumer 授权 + 托管雇佣（资金进合约托管）。
    print("② Consumer 授权 registry 动用资金并创建雇佣单（资金进合约托管）…")
    vouch_chain.approve(CONSUMER_KEY, total)
    hire = vouch_chain.create_hire(CONSUMER_KEY, AGENT_ID, args.days, args.milestones)
    hid = hire["hire_id"]
    print(f"   hire#{hid} 上链: {hire['tx']}\n")
    vouch_ledger.record_event(
        "hire", hire_id=hid, provider=AGENT_ID, topic=TOPIC,
        days=args.days, total=total, tx=hire["tx"],
    )
    vouch_ledger.add_treasury(gas_cspr=GAS_PER_TX_CSPR * 2)  # approve + create_hire

    # 2. 验证网络按 SLA 评估 Provider 各里程碑履约（独立取证 + 对抗投票）。
    readings, judgement = judge_asset(TOPIC)
    real = judgement.consensus_value
    quotes = _provider_quotes(args.scenario, real, args.milestones)
    print(f"③ 验证网络 SLA 评估（真实约 {real:.2f}，Provider 各里程碑产出 {quotes}）：")
    report = evaluate_sla(TOPIC, quotes)
    print()

    # 3. 履约裁决（已通过里程碑数）写上链。
    print(f"④ 履约裁决上链（通过 {report.milestones_passed}/{report.milestones_total}）…")
    rec = vouch_chain.record_hire_verdict(VERIFIER_KEY, hid, report.milestones_passed)
    print(f"   record_hire_verdict 上链: {rec['tx']}\n")
    vouch_ledger.record_event(
        "hire_verdict", hire_id=hid, passed=report.milestones_passed,
        total=report.milestones_total, accuracy=round(report.accuracy, 3),
        passed_sla=report.passed_sla, tx=rec["tx"],
    )
    vouch_ledger.add_treasury(gas_cspr=GAS_PER_TX_CSPR)

    # 4. keeper 到期执行：达标 settle 放款 / 不达标 refund 退款罚没。
    #    （生产中由 keeper 在 ends_at 到期时自动发起；这里立即执行演示该到期动作。）
    settled_amount = total * report.milestones_passed // args.milestones
    if report.passed_sla:
        print("⑤ keeper 判定达标 → settle 放款给 Provider（平台抽佣金）…")
        res = vouch_chain.settle_hire(VERIFIER_KEY, hid)
        print(f"   settle 上链: {res['tx']}\n")
        commission = settled_amount * COMMISSION_BPS // 10000
        vouch_ledger.record_event(
            "settle", hire_id=hid, provider=AGENT_ID, paid=settled_amount,
            commission=commission, tx=res["tx"],
        )
        vouch_ledger.add_treasury(commission=commission, gas_cspr=GAS_PER_TX_CSPR)
    else:
        print("⑤ keeper 判定不达标 → refund 退款 Consumer + 罚没 Provider 押金…")
        res = vouch_chain.refund_hire(VERIFIER_KEY, hid)
        print(f"   refund 上链: {res['tx']}\n")
        vouch_ledger.record_event(
            "refund", hire_id=hid, provider=AGENT_ID, refunded=total,
            slashed=total, tx=res["tx"],  # slash_factor 1.0：罚没=未交付额
        )
        vouch_ledger.add_treasury(gas_cspr=GAS_PER_TX_CSPR)

    # 5. 读回最终链上状态。
    h = vouch_chain.get_hire(VERIFIER_KEY, hid)
    ag = vouch_chain.get_agent(VERIFIER_KEY, AGENT_ID)
    status_name = {0: "active", 1: "settled", 2: "refunded"}.get(h["status"], "?")
    print(
        f"⑥ 终局：hire#{hid} status={status_name} | 已结算 {h['settled']} | 剩余托管 {h['escrow']}\n"
        f"   Provider agent#{AGENT_ID} 信誉 {ag0['reputation']} → {ag['reputation']}"
        f" | 押金 {ag0['stake']} → {ag['stake']}"
    )
    print("\n=== 一轮完成：托管 → SLA 客观裁决 → 按履约结算/罚没，全自主 ===\n")


if __name__ == "__main__":
    main()
