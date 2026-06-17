"""Casper RWA 预言机 Dashboard 后端（FastAPI）。

- GET /            → Dashboard 页面
- GET /api/state   → 最新预言机状态快照（由 agent/main.py 每轮写入 oracle_state.json）

x402 付费数据端点将在 Phase 3 加入（消费方按次付费读取预言机数据）。

运行：
  cd web && uvicorn server:app --port 4020 --reload
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "oracle_state.json"
STATIC = BASE / "static"

# x402 买方（官方 Go client + 预置买方密钥）配置。
X402_REPO = "/tmp/casper-x402"
BUYER_KEY = "/Users/yunhai/Projects/casper-rwa-oracle-agent/x402/keys-buyer/secret_key.pem"

app = FastAPI(title="Casper RWA Oracle Dashboard")


@app.get("/api/state")
def get_state() -> JSONResponse:
    """返回最新预言机状态快照。"""
    if STATE_FILE.exists():
        return JSONResponse(json.loads(STATE_FILE.read_text()))
    return JSONResponse({"assets": [], "actions": [], "updated_at": None, "contract_hash": ""})


@app.post("/api/x402-buy")
def x402_buy() -> JSONResponse:
    """通过 x402 微支付购买完整预言机数据（应用代付，链上结算）。

    运行官方 Go client，用预置买方账户完成 402→签名→链上 CEP-18 结算→取数据。
    """
    env = {
        **os.environ,
        "CLIENT_PRIVATE_KEY_PATH": BUYER_KEY,
        "CLIENT_KEY_ALGO": "ed25519",
        "CAIP2_CHAIN_ID": "casper:casper-test",
        "SERVER_URL": "http://localhost:4021",
        "PATH": "/opt/homebrew/bin:" + os.environ.get("PATH", ""),
    }
    try:
        result = subprocess.run(
            ["go", "run", "./examples/client"],
            cwd=X402_REPO, env=env, capture_output=True, text=True, timeout=240,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"success": False, "error": "结算超时"}, status_code=504)

    out = result.stdout + result.stderr
    # 解析结算交易哈希
    tx_match = re.search(r'"transaction":"([0-9a-fA-F]+)"', out)
    settlement_tx = tx_match.group(1) if tx_match else None
    # 解析返回的预言机数据（"===" 标记之后的 JSON）
    data = None
    if "===" in out:
        tail = out.split("===")[-1]
        start = tail.find("{")
        if start >= 0:
            try:
                data = json.loads(tail[start:])
            except Exception:
                data = None
    success = settlement_tx is not None
    return JSONResponse({"success": success, "settlement_tx": settlement_tx, "data": data, "raw": out[-400:]})


@app.get("/")
def index() -> FileResponse:
    """返回 Dashboard 页面。"""
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
