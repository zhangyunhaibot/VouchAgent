"""Vouch 一轮自主验证闭环 demo。

RWA 预言机(Provider) 抓价 → submit_claim 上链 → 验证网络对抗式投票 → record_verdict 上链
→ 读回 Provider 链上信誉。全程由 agent 自主驱动 Vouch 合约。

环境变量（agent/.env + 运行时）：
  DEEPSEEK_API_KEY  验证网络 LLM
  REGISTRY_HASH     TrustRegistry 地址
  PROVIDER_KEY      Provider 私钥（已注册的 agent）
  VERIFIER_KEY      验证网络私钥（合约里的 verifier）
  AGENT_ID          已注册的 provider agent id（默认 0）
运行：venv/bin/python vouch_cycle.py
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from judge import judge_asset  # noqa: E402
from verifier_network import verify_claim  # noqa: E402
import vouch_chain  # noqa: E402
import vouch_ledger  # noqa: E402

GAS_PER_TX_CSPR = 2.0  # 单笔链上交易 gas 粗估（CSPR）

PROVIDER_KEY = os.environ["PROVIDER_KEY"]
VERIFIER_KEY = os.environ["VERIFIER_KEY"]
AGENT_ID = int(os.environ.get("AGENT_ID", "0"))
TOPIC = os.environ.get("TOPIC", "XAU/USD")


def main() -> None:
    print(f"\n=== Vouch 自主验证一轮 | 资产 {TOPIC} | Provider agent#{AGENT_ID} ===\n")

    # 1. Provider（RWA 预言机）抓多源价格 + 自身判断，提交 claim 上链
    readings, judgement = judge_asset(TOPIC)
    real = judgement.consensus_value
    fake = os.environ.get("FAKE_VALUE")
    if fake:
        claimed = float(fake)
        print(
            f"① ⚠️ [恶意 Provider] 真实约 {real:.2f}，却谎报虚高价 {claimed:.2f}"
            f"（自报置信度 {judgement.confidence}）→ 提交 claim 上链…"
        )
    else:
        claimed = real
        print(
            f"① Provider 抓 {len(readings)} 源，共识价 {claimed:.4f}"
            f"（自报置信度 {judgement.confidence}）→ 提交 claim 上链…"
        )
    sub = vouch_chain.submit_claim(
        PROVIDER_KEY,
        AGENT_ID,
        TOPIC,
        int(round(claimed * vouch_chain.PRICE_SCALE)),
        judgement.confidence,
        len(readings),
    )
    claim_id = sub["claim_id"]
    print(f"   claim#{claim_id} 上链: {sub['tx']}\n")
    vouch_ledger.record_event(
        "claim", claim_id=claim_id, agent=AGENT_ID, topic=TOPIC,
        value=int(round(claimed * vouch_chain.PRICE_SCALE)),
        confidence=judgement.confidence, tx=sub["tx"],
    )
    vouch_ledger.add_treasury(gas_cspr=GAS_PER_TX_CSPR)

    # 2. 验证网络对抗式裁决（独立重新取证 + 3 个人格互异的 verifier 投票）
    print("② 验证网络对抗式裁决（独立取证 + 多 verifier 投票）:")
    verdict = verify_claim(TOPIC, claimed)
    print()

    # 3. 裁决（含投票分布）写上链
    print(f"③ 裁决上链（票型 {verdict.votes_for}:{verdict.votes_against}）…")
    rec = vouch_chain.record_verdict(
        VERIFIER_KEY,
        claim_id,
        verdict.accurate,
        verdict.confidence,
        verdict.votes_for,
        verdict.votes_against,
    )
    print(f"   verdict 上链: {rec['tx']}\n")
    vouch_ledger.record_event(
        "verdict", claim_id=claim_id, topic=TOPIC, accurate=verdict.accurate,
        votes_for=verdict.votes_for, votes_against=verdict.votes_against,
        confidence=verdict.confidence, tx=rec["tx"],
    )
    vouch_ledger.add_treasury(
        evidence_cost=verdict.paid_cost, gas_cspr=GAS_PER_TX_CSPR
    )

    # 4. 读回 Provider 最新链上信誉
    ag = vouch_chain.get_agent(VERIFIER_KEY, AGENT_ID)
    print(
        f"④ Provider agent#{AGENT_ID} 链上信誉 → {ag['reputation']}"
        f"（质押 {ag['stake']}, 状态 {ag['status']}）"
    )
    print("\n=== 一轮完成：Provider 提交 → 验证网络对抗裁决 → 信誉上链，全自主 ===\n")


if __name__ == "__main__":
    main()
