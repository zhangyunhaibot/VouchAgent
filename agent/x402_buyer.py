"""x402 买方 —— 验证网络付费拉 premium 证据，补齐自给自足闭环的成本侧。

验证网络默认用 fetcher 免费多源取证。但当免费来源不足（某些源缺失/被限流，
取到的独立来源 < 阈值）时，单凭一两个源难以做可信的对抗裁决。此时验证网络
通过 x402 微支付从【付费数据端点】买一份 premium 证据补齐 —— 这正是 agent
经济的"花钱"一侧：Vouch 既靠佣金/查询费赚钱，也会为高质量证据付费，
净利润（赚−花）随时间增长是核心卖点。

实现复用官方 casper-x402 Go client（/tmp/casper-x402）+ 预置买方账户（keys-buyer），
链上 CEP-18 结算。每次支出金额记入 Treasury 成本侧。服务未起/失败时返回
success=False，调用方据此回退到免费证据，不影响主流程。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
X402_REPO = os.environ.get("X402_REPO", "/tmp/casper-x402")
BUYER_KEY = os.environ.get(
    "X402_BUYER_KEY", str(PROJECT / "x402" / "keys-buyer" / "secret_key.pem")
)
SERVER_URL = os.environ.get("X402_SERVER_URL", "http://localhost:4021")


@dataclass
class EvidencePurchase:
    success: bool
    data: dict | None
    settlement_tx: str | None
    cost: int  # 本次支付的 X402 最小单位（成本侧）
    raw: str = ""

    @property
    def tx_url(self) -> str | None:
        return (
            f"https://testnet.cspr.live/transaction/{self.settlement_tx}"
            if self.settlement_tx
            else None
        )


def buy_premium_evidence(
    server_url: str | None = None, timeout: int = 240
) -> EvidencePurchase:
    """通过 x402 付费从数据端点拉一份 premium 证据。

    走 402→签名→链上 CEP-18 结算→取数据 全流程（官方 Go client + 买方账户）。
    返回结构化结果；失败（服务未起/超时/未结算）时 success=False，由调用方回退。
    """
    server_url = server_url or SERVER_URL
    env = {
        **os.environ,
        "CLIENT_PRIVATE_KEY_PATH": BUYER_KEY,
        "CLIENT_KEY_ALGO": "ed25519",
        "CAIP2_CHAIN_ID": "casper:casper-test",
        "SERVER_URL": server_url,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""),
    }
    try:
        result = subprocess.run(
            ["go", "run", "./examples/client"],
            cwd=X402_REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return EvidencePurchase(False, None, None, 0, raw=f"{type(exc).__name__}: {exc}")

    out = result.stdout + result.stderr
    tx = re.search(r'"transaction":"([0-9a-fA-F]+)"', out)
    # x402 的 402 响应里 maxAmountRequired = 本次应付金额（最小单位）。
    cost_m = re.search(r'maxAmountRequired"?\s*[:=]\s*"?(\d+)', out)
    data = None
    if "===" in out:
        tail = out.split("===")[-1]
        start = tail.find("{")
        if start >= 0:
            try:
                data = json.loads(tail[start:])
            except json.JSONDecodeError:
                data = None
    return EvidencePurchase(
        success=tx is not None,
        data=data,
        settlement_tx=tx.group(1) if tx else None,
        cost=int(cost_m.group(1)) if cost_m else 0,
        raw=out[-500:],
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    print(f"向 {SERVER_URL} 付费拉 premium 证据…")
    res = buy_premium_evidence()
    print(f"success={res.success} cost={res.cost} tx={res.tx_url}")
    print(f"data={res.data}")
    if not res.success:
        print(f"raw tail:\n{res.raw}")
