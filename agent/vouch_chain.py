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
        raise RuntimeError(f"vouch[{step}] 链上调用失败：\n{result.stderr.strip()}")
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
    return {"claim_id": int(m.group(1)) if m else None, "tx": _tx_url(out)}


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
    """读取某 agent 的链上状态（信誉/质押/状态）。"""
    out = _run("agent", secret_key, {"AGENT_ID": agent_id})
    rep = re.search(r"reputation=(\d+)", out)
    stake = re.search(r"stake=(\d+)", out)
    status = re.search(r"status=(\d+)", out)
    return {
        "reputation": int(rep.group(1)) if rep else None,
        "stake": int(stake.group(1)) if stake else None,
        "status": int(status.group(1)) if status else None,
    }
