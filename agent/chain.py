"""链上交互：调用已部署的 RwaOracle 合约（提交数据 / 更新信誉分）。

复用合约工程里已验证的 Odra livenet 通道（Rust bin），通过 subprocess 调用，
避免在 Python 侧重复实现 Casper 交易签名/序列化。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# 价格放大倍数：合约用整数存价格，约定乘以 1e6。
PRICE_SCALE = 1_000_000

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contract"
CARGO_BIN = str(Path.home() / ".cargo" / "bin")


def _livenet_env(extra: dict) -> dict:
    """构造调用合约 bin 所需的环境变量（livenet 配置 + 合约地址 + bin 参数）。"""
    return {
        **os.environ,
        "ODRA_CASPER_LIVENET_SECRET_KEY_PATH": os.environ.get("ORACLE_SECRET_KEY", "keys/secret_key.pem"),
        "ODRA_CASPER_LIVENET_NODE_ADDRESS": os.environ.get("NODE_ADDRESS", "https://node.testnet.casper.network"),
        "ODRA_CASPER_LIVENET_EVENTS_URL": os.environ.get("EVENTS_URL", "https://node.testnet.casper.network/events"),
        "ODRA_CASPER_LIVENET_CHAIN_NAME": os.environ.get("CHAIN_NAME", "casper-test"),
        "ORACLE_CONTRACT_HASH": os.environ["CONTRACT_HASH"],
        "PATH": CARGO_BIN + os.pathsep + os.environ.get("PATH", ""),
        **extra,
    }


def _run_bin(bin_name: str, extra_env: dict) -> str:
    """运行某个合约 bin，返回其标准输出。"""
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--bin", bin_name, "--features", "livenet"],
        cwd=CONTRACT_DIR,
        env=_livenet_env(extra_env),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"链上调用 {bin_name} 失败（returncode={result.returncode}）：\n{result.stderr}"
        )
    return result.stdout.strip()


def submit_on_chain(asset: str, price_usd: float, confidence: int, source_count: int = 2) -> str:
    """把一条数据提交上链。需要环境变量 CONTRACT_HASH 等。"""
    value_scaled = int(round(price_usd * PRICE_SCALE))
    return _run_bin(
        "submit",
        {
            "SUBMIT_ASSET": asset,
            "SUBMIT_VALUE": str(value_scaled),
            "SUBMIT_CONFIDENCE": str(confidence),
            "SUBMIT_SOURCE_COUNT": str(source_count),
        },
    )


def update_reputation_on_chain(asset: str, accurate: bool) -> str:
    """调整某资产链上信誉分（accurate=True→+1，False→-1）。"""
    return _run_bin(
        "score",
        {
            "SCORE_ASSET": asset,
            "SCORE_ACCURATE": "true" if accurate else "false",
        },
    )
