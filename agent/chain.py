"""链上提交：调用已部署的 RwaOracle 合约 submit_data。

复用合约工程里已验证的 Odra livenet 通道（Rust 的 submit bin），
通过 subprocess 调用，避免在 Python 侧重复实现 Casper 交易签名/序列化。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# 价格放大倍数：合约用整数存价格，约定乘以 1e6。
PRICE_SCALE = 1_000_000

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contract"
CARGO_BIN = str(Path.home() / ".cargo" / "bin")


def submit_on_chain(asset: str, price_usd: float, confidence: int) -> str:
    """把一条数据提交上链，返回 submit 程序的输出文本。

    需要环境变量：CONTRACT_HASH、ORACLE_SECRET_KEY、NODE_ADDRESS、EVENTS_URL、CHAIN_NAME。
    """
    value_scaled = int(round(price_usd * PRICE_SCALE))

    env = {
        **os.environ,
        # Odra livenet 配置
        "ODRA_CASPER_LIVENET_SECRET_KEY_PATH": os.environ.get("ORACLE_SECRET_KEY", "keys/secret_key.pem"),
        "ODRA_CASPER_LIVENET_NODE_ADDRESS": os.environ.get("NODE_ADDRESS", "https://node.testnet.casper.network"),
        "ODRA_CASPER_LIVENET_EVENTS_URL": os.environ.get("EVENTS_URL", "https://node.testnet.casper.network/events"),
        "ODRA_CASPER_LIVENET_CHAIN_NAME": os.environ.get("CHAIN_NAME", "casper-test"),
        # submit bin 参数
        "ORACLE_CONTRACT_HASH": os.environ["CONTRACT_HASH"],
        "SUBMIT_ASSET": asset,
        "SUBMIT_VALUE": str(value_scaled),
        "SUBMIT_CONFIDENCE": str(confidence),
        # 确保 cargo 在 PATH 上
        "PATH": CARGO_BIN + os.pathsep + os.environ.get("PATH", ""),
    }

    result = subprocess.run(
        ["cargo", "run", "--quiet", "--bin", "submit", "--features", "livenet"],
        cwd=CONTRACT_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"上链失败（returncode={result.returncode}）：\n{result.stderr}")
    return result.stdout.strip()
