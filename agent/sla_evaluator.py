"""SLA 履约评估 —— Vouch 雇佣托管的客观裁决核心。

雇佣单的 SLA = "价格准确率 ≥ 阈值 且 在线率达标"。验证网络在雇佣期内按里程碑
周期性采集 Provider 的实际产出（每个里程碑一次报价），对每次产出跑【对抗式投票】
判准确与否；Provider 在某周期未产出（quote 为 None）记为掉线、该里程碑不通过。

最终把"通过的里程碑数"交给 keeper 写上链（record_hire_verdict），决定按里程碑放款
还是退款罚没。这样履约判定完全客观、由验证网络自动完成，杜绝"Consumer 白嫖不付钱"
和"Provider 摆烂照拿钱"两头作弊。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from verifier_network import verify_claim


@dataclass
class MilestoneResult:
    index: int
    claimed: float | None  # None 表示该周期 Provider 掉线、无产出
    accurate: bool
    votes_for: int
    votes_against: int
    note: str = ""


@dataclass
class SLAReport:
    topic: str
    milestones_total: int
    milestones_passed: int
    accuracy: float  # 通过里程碑 / 总里程碑
    passed_sla: bool  # accuracy >= threshold
    threshold: float
    results: list[MilestoneResult] = field(default_factory=list)


def evaluate_sla(
    topic: str,
    quotes: list[float | None],
    threshold: float = 0.6,
    verbose: bool = True,
) -> SLAReport:
    """对一张雇佣单做 SLA 履约评估。

    quotes: Provider 在各里程碑周期内的产出报价（None = 掉线未产出）。
    threshold: 达标所需的最低通过率（默认 0.6，即 3 个里程碑过 2 个即达标）。
    """
    milestones_total = len(quotes)
    if milestones_total == 0:
        raise ValueError("雇佣单至少要有一个里程碑")

    results: list[MilestoneResult] = []
    for i, claimed in enumerate(quotes):
        if verbose:
            print(f"  — 里程碑 {i + 1}/{milestones_total}：", end="")
        if claimed is None:
            if verbose:
                print("Provider 掉线（无产出）→ 不通过")
            results.append(
                MilestoneResult(i, None, False, 0, 0, note="掉线")
            )
            continue
        if verbose:
            print(f"Provider 产出 {claimed}，验证网络对抗裁决：")
        verdict = verify_claim(topic, claimed, verbose=verbose)
        results.append(
            MilestoneResult(
                index=i,
                claimed=claimed,
                accurate=verdict.accurate,
                votes_for=verdict.votes_for,
                votes_against=verdict.votes_against,
                note=verdict.reasoning,
            )
        )

    passed = sum(1 for r in results if r.accurate)
    accuracy = passed / milestones_total
    passed_sla = accuracy >= threshold

    if verbose:
        verdict_str = "达标 ✅" if passed_sla else "不达标 ❌"
        print(
            f"  ⚖️  SLA 评估：通过 {passed}/{milestones_total} 里程碑"
            f"（准确率 {accuracy:.0%}，阈值 {threshold:.0%}）→ {verdict_str}"
        )

    return SLAReport(
        topic=topic,
        milestones_total=milestones_total,
        milestones_passed=passed,
        accuracy=accuracy,
        passed_sla=passed_sla,
        threshold=threshold,
        results=results,
    )
