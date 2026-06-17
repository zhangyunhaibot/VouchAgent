"""Vouch 信任层链上交互：调用已部署的 TrustRegistry 合约。

复用合约工程里已在 testnet 验证过的 trust_e2e Rust bin（STEP 环境变量驱动），
通过 subprocess 调用，避免在 Python 侧重复实现 Casper 交易签名/序列化。

需要环境变量：REGISTRY_HASH（TrustRegistry 地址）、NODE_ADDRESS/CHAIN_NAME 等 livenet 配置。
每个调用传入对应角色的私钥路径（provider / verifier / consumer 各自的 key）。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contract"
CARGO_BIN = str(Path.home() / ".cargo" / "bin")

# X402 代币 9 位小数；价格按 1e6 放大存入合约（与 RwaOracle 约定一致）。
PRICE_SCALE = 1_000_000


def _run(step: str, secret_key: str, extra: dict) -> str:
    """以指定角色私钥运行 trust_e2e 的某个 STEP，返回标准输出。"""
    env = {
        **os.environ,
        "ODRA_CASPER_LIVENET_SECRET_KEY_PATH": secret_key,
        "ODRA_CASPER_LIVENET_NODE_ADDRESS": os.environ.get(
            "NODE_ADDRESS", "https://node.testnet.casper.network"
        ),
        "ODRA_CASPER_LIVENET_EVENTS_URL": os.environ.get(
            "EVENTS_URL", "https://node.testnet.casper.network/events"
        ),
        "ODRA_CASPER_LIVENET_CHAIN_NAME": os.environ.get("CHAIN_NAME", "casper-test"),
        "REGISTRY_HASH": os.environ["REGISTRY_HASH"],
        "STEP": step,
        "PATH": CARGO_BIN + os.pathsep + os.environ.get("PATH", ""),
        **{k: str(v) for k, v in extra.items()},
    }
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--bin", "trust_e2e", "--features", "livenet"],
        cwd=CONTRACT_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Odra livenet 偶发：合约已在链上执行成功，但本地提取事件数据时 panic
        # （CouldntExtractEventData）。该 panic 发生在执行之后，链上状态已变更，
        # 因此不可重试（会重复记账/重复改信誉）。按"已执行"处理，仍返回已捕获的
        # stdout（含交易 URL / 返回值），交由调用方读回链上状态核验真实结果。
        if "CouldntExtractEventData" in stderr:
            print(
                f"⚠️  vouch[{step}] 链上已执行，但 Odra 本地读事件失败"
                f"（CouldntExtractEventData，节点偶发）；按已执行处理，将读回链上核验。"
            )
            return result.stdout.strip()
        raise RuntimeError(f"vouch[{step}] 链上调用失败：\n{stderr}")
    return result.stdout.strip()


def _tx_url(output: str) -> str | None:
    m = re.search(r"https://testnet\.cspr\.live/transaction/[0-9a-fA-F]+", output)
    return m.group(0) if m else None


def submit_claim(
    secret_key: str,
    agent_id: int,
    topic: str,
    value_scaled: int,
    confidence: int,
    sources: int = 2,
) -> dict:
    """Provider 提交一条可验证 claim（价格按 1e6 放大后的整数）。"""
    out = _run(
        "claim",
        secret_key,
        {
            "AGENT_ID": agent_id,
            "TOPIC": topic,
            "VALUE": value_scaled,
            "CONFIDENCE": confidence,
            "SOURCES": sources,
        },
    )
    m = re.search(r"claim_id=(\d+)", out)
    if not m:
        # 仅当 _run 容忍了 CouldntExtractEventData（claim 已上链但本地读事件 panic、
        # println 未执行）才会到这里。合约无 get_claim_count getter 无法读回 id，
        # 故失败即抛——绝不返回 None，否则下游 CLAIM_ID 会被 trust_e2e 回退成 claim#0、
        # 把裁决误打到无关 claim 上。
        raise RuntimeError(
            "submit_claim：交易可能已上链但无法从输出解析 claim_id"
            "（Odra 偶发读事件失败）。请到 cspr.live 核对该笔交易后重跑本轮。"
        )
    return {"claim_id": int(m.group(1)), "tx": _tx_url(out)}


def record_verdict(
    secret_key: str,
    claim_id: int,
    accurate: bool,
    confidence: int,
    votes_for: int,
    votes_against: int,
) -> dict:
    """验证网络把对抗式投票的最终裁决写上链（含投票分布）。"""
    out = _run(
        "verdict",
        secret_key,
        {
            "CLAIM_ID": claim_id,
            "ACCURATE": "true" if accurate else "false",
            "CONFIDENCE": confidence,
            "VOTES_FOR": votes_for,
            "VOTES_AGAINST": votes_against,
        },
    )
    return {"tx": _tx_url(out)}


def get_agent(secret_key: str, agent_id: int) -> dict:
    """读取某 agent 的链上状态（信誉/质押/状态/到期时间）。"""
    out = _run("agent", secret_key, {"AGENT_ID": agent_id})

    def _int(pattern: str) -> int | None:
        m = re.search(pattern, out)
        return int(m.group(1)) if m else None

    return {
        "reputation": _int(r"reputation=(\d+)"),
        "stake": _int(r"stake=(\d+)"),
        "price_per_day": _int(r"price=(\d+)"),
        "status": _int(r"status=(\d+)"),
        "lock_until": _int(r"lock_until=(\d+)"),
    }


# ---------- 雇佣托管（Consumer / 验证网络 / keeper） ----------


def approve(secret_key: str, amount: int) -> dict:
    """调用者对 registry 授权动用 amount（最小单位）；Consumer 托管前必须先 approve。"""
    out = _run("approve", secret_key, {"AMOUNT": amount})
    return {"tx": _tx_url(out)}


def create_hire(
    secret_key: str,
    agent_id: int,
    days: int,
    milestones: int,
    sla_hash: str = "sla-hash",
) -> dict:
    """Consumer 雇佣某 Provider：托管 price_per_day×days，按 milestones 个里程碑结算。"""
    out = _run(
        "hire",
        secret_key,
        {"AGENT_ID": agent_id, "DAYS": days, "MILESTONES": milestones, "SLA": sla_hash},
    )
    m = re.search(r"hire_id=(\d+)", out)
    if m:
        hire_id = int(m.group(1))
    else:
        # _run 容忍了 CouldntExtractEventData（hire 已上链但本地读事件 panic、println 未执行）。
        # 用链上 hire_count-1 读回刚创建的 hire_id，绝不返回 None（否则下游 HIRE_ID 会被
        # trust_e2e 回退成 hire#0、把记履约/结算误打到无关雇佣单上）。
        hire_id = get_hire_count(secret_key) - 1
        print(f"⚠️  create_hire：输出无 hire_id，读回链上 hire_count 恢复为 hire#{hire_id}")
    return {"hire_id": hire_id, "tx": _tx_url(out)}


def record_hire_verdict(
    secret_key: str,
    hire_id: int,
    milestones_passed: int,
    reason: str = "sla-eval",
) -> dict:
    """验证网络按客观 SLA 把已通过的里程碑数写上链。"""
    out = _run(
        "hverdict",
        secret_key,
        {"HIRE_ID": hire_id, "PASSED": milestones_passed, "REASON": reason},
    )
    return {"tx": _tx_url(out)}


def settle_hire(secret_key: str, hire_id: int) -> dict:
    """按已通过里程碑结算放款给 Provider（扣佣金）。仅验证网络可调。"""
    out = _run("settle", secret_key, {"HIRE_ID": hire_id})
    return {"tx": _tx_url(out)}


def refund_hire(secret_key: str, hire_id: int) -> dict:
    """不达标：退未交付托管给 Consumer + 罚没 Provider 押金赔付。仅验证网络可调。"""
    out = _run("refund", secret_key, {"HIRE_ID": hire_id})
    return {"tx": _tx_url(out)}


def release_expired_stake(secret_key: str, agent_id: int) -> dict:
    """到期返还剩余押金到原付款地址（keeper 自动触发）。"""
    out = _run("release", secret_key, {"AGENT_ID": agent_id})
    return {"tx": _tx_url(out)}


def get_hire(secret_key: str, hire_id: int) -> dict:
    """读取某雇佣单的链上状态（keeper 扫描用）。"""
    out = _run("hire_info", secret_key, {"HIRE_ID": hire_id})

    def _int(pattern: str) -> int | None:
        m = re.search(pattern, out)
        return int(m.group(1)) if m else None

    return {
        "provider": _int(r"provider=(\d+)"),
        "total": _int(r"total=(\d+)"),
        "escrow": _int(r"escrow=(\d+)"),
        "settled": _int(r"settled=(\d+)"),
        "milestones_passed": _int(r"milestones=(\d+)/"),
        "milestones_total": _int(r"milestones=\d+/(\d+)"),
        "status": _int(r"status=(\d+)"),
        "ends_at": _int(r"ends_at=(\d+)"),
    }


def get_hire_count(secret_key: str) -> int:
    out = _run("hire_count", secret_key, {})
    m = re.search(r"hire_count=(\d+)", out)
    return int(m.group(1)) if m else 0


def get_agent_count(secret_key: str) -> int:
    out = _run("agent_count", secret_key, {})
    m = re.search(r"agent_count=(\d+)", out)
    return int(m.group(1)) if m else 0
