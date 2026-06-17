"""验证网络 —— Vouch 的对抗式裁决核心。

对一条 Provider 提交的 claim，派 N 个【人格互异】的独立 Verifier（不同角度 + 不同温度）
各自投票，分歧浮现后加权收敛成最终 verdict（含投票分布）。

这是单 LLM "盖章式" 验证比不了的：分歧被显式记录并上链，可视化"多个 AI 如何
独立判断、产生分歧、再达成共识"。验证网络【不信 Provider 自报值】，用 fetcher
独立重新取证（抓真实多源价格）后再判。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from openai import OpenAI

from fetcher import fetch_asset
import x402_buyer


@dataclass
class VerifierVote:
    name: str
    accurate: bool
    confidence: int
    reasoning: str


@dataclass
class Verdict:
    accurate: bool
    confidence: int
    votes_for: int
    votes_against: int
    evidence: str = ""
    votes: list = field(default_factory=list)
    reasoning: str = ""
    paid_cost: int = 0  # 本轮为补证据通过 x402 付费的 X402 支出（成本侧）
    paid_tx: str | None = None  # 付费证据的链上结算 tx


# 三个角度互异的验证者人格 —— 故意制造独立视角，让分歧能浮现（name, persona, temperature）。
VERIFIER_PERSONAS = [
    (
        "严格核验员",
        "你是一丝不苟的价格核验员。只看数字事实：对比 claim 声称价格与你独立抓到的多源真实价格，相对偏差 >1% 就倾向判不准确。",
        0.0,
    ),
    (
        "异常猎手",
        "你专门寻找操纵与异常迹象：来源是否可疑、报价是否明显偏离市场、有无拉高/砸盘痕迹。宁可错杀，对可疑数据保持警惕。",
        0.4,
    ),
    (
        "市场常识官",
        "你用市场常识判断 claim 是否落在合理区间。考虑该资产近期正常波动范围，避免把正常波动误判为造假。",
        0.7,
    ),
]

SYSTEM = """你是 Vouch 信任层验证网络中的一名独立验证者（Verifier）。
你的人格与判断风格：{persona}

任务：判断一条 Provider 提交的 claim 是否【准确可信】。
- 资产：{topic}
- Provider 声称价格：{claimed}
- 你独立抓到的真实多源价格：{evidence}

只输出 JSON：{{"accurate": true 或 false, "confidence": 0-100 的整数, "reasoning": "简短中文理由"}}
confidence 表示你对自己这次判断的把握程度。"""


def _client(model: str | None):
    model = model or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
    )
    return client, model


def _one_vote(client, model, name, persona, temperature, topic, claimed, evidence) -> VerifierVote:
    prompt = SYSTEM.format(persona=persona, topic=topic, claimed=claimed, evidence=evidence)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请独立投票（仅 JSON）。"},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    # 容错：LLM 可能漏字段或给出越界置信度，用 .get + 裁剪，避免崩溃或把非法值传上链。
    confidence = max(0, min(100, int(data.get("confidence", 0))))
    return VerifierVote(
        name=name,
        accurate=bool(data.get("accurate", False)),
        confidence=confidence,
        reasoning=str(data.get("reasoning", "")),
    )


def _paid_evidence_enabled(allow_paid: bool | None) -> bool:
    if allow_paid is not None:
        return allow_paid
    return os.environ.get("X402_PAID_EVIDENCE", "").strip() in ("1", "true", "yes")


def gather_evidence(
    topic: str,
    min_sources: int = 2,
    allow_paid: bool | None = None,
    verbose: bool = True,
) -> tuple[str, int, str | None]:
    """独立取证：先免费多源抓取；来源不足且开启付费时，x402 付费补一份 premium 证据。

    返回 (证据字符串, 付费成本, 付费结算tx)。验证网络【不信 Provider 自报值】。
    """
    readings = fetch_asset(topic)
    parts = [f"{r.source}={r.price:.4f}" for r in readings]
    cost, tx = 0, None

    if len(readings) < min_sources and _paid_evidence_enabled(allow_paid):
        if verbose:
            print(f"  💸 免费来源仅 {len(readings)} 个（<{min_sources}），x402 付费补 premium 证据…")
        buy = x402_buyer.buy_premium_evidence()
        if buy.success:
            cost, tx = buy.cost, buy.settlement_tx
            parts.append(f"premium(付费)={json.dumps(buy.data, ensure_ascii=False)[:120]}")
            if verbose:
                print(f"  💸 已付费拉到 premium 证据（成本 {cost}, tx {buy.tx_url}）")
        elif verbose:
            print(f"  ⚠️  付费证据获取失败，回退到免费证据（{buy.raw[:80]}）")

    evidence = ", ".join(parts) or "（无法取证）"
    return evidence, cost, tx


def verify_claim(topic: str, claimed_value: float, model: str | None = None,
                 verbose: bool = True, allow_paid: bool | None = None) -> Verdict:
    """对一条 claim 做对抗式验证：独立取证 → N 个 verifier 独立投票 → 加权收敛。"""
    client, model = _client(model)

    # 1. 独立取证：验证网络不信 Provider，自己重新抓多源价格（必要时 x402 付费补证据）
    evidence, paid_cost, paid_tx = gather_evidence(
        topic, allow_paid=allow_paid, verbose=verbose
    )

    # 2. N 个人格互异的 verifier 独立投票
    votes: list[VerifierVote] = []
    for name, persona, temp in VERIFIER_PERSONAS:
        try:
            v = _one_vote(client, model, name, persona, temp, topic, claimed_value, evidence)
            votes.append(v)
            if verbose:
                mark = "✓准确" if v.accurate else "✗存疑"
                print(f"  🗳️  {name}: {mark} (把握 {v.confidence}) — {v.reasoning}")
        except Exception as exc:  # noqa: BLE001 — 单个 verifier 失败不影响整体投票
            print(f"  ⚠️  {name} 投票失败: {exc}")

    # 3. 加权收敛：多数票决定 accurate，置信度取与多数一致票的平均把握
    votes_for = sum(1 for v in votes if v.accurate)
    votes_against = len(votes) - votes_for
    accurate = votes_for > votes_against
    agree = [v.confidence for v in votes if v.accurate == accurate]
    confidence = round(sum(agree) / len(agree)) if agree else 0
    reasoning = "; ".join(
        f"{v.name}:{'✓' if v.accurate else '✗'}({v.confidence})" for v in votes
    )
    if verbose:
        verdict_str = "准确" if accurate else "不准确"
        split = "一致" if votes_against == 0 or votes_for == 0 else "有分歧"
        print(f"  ⚖️  收敛裁决: {verdict_str} | 票型 {votes_for}:{votes_against} ({split}) | 综合置信度 {confidence}")

    return Verdict(
        accurate=accurate,
        confidence=confidence,
        votes_for=votes_for,
        votes_against=votes_against,
        evidence=evidence,
        votes=votes,
        reasoning=reasoning,
        paid_cost=paid_cost,
        paid_tx=paid_tx,
    )
