"""Vouch 信任层 Dashboard 后端（FastAPI）。

看板数据来自 agent 合成的 web/vouch_state.json（链上信誉榜+雇佣单 + 本地账本事件流/Treasury）。

页面/接口：
  GET  /                       → Vouch 看板页面
  GET  /api/vouch-state        → 完整信任层快照（信誉榜/雇佣单/事件流/Treasury）
  GET  /api/reputation/{agent} → 某 Provider 的信誉（免费只读，付费版见 x402 卖方）
  GET  /api/verdict/{claim}    → 某 claim 的对抗投票裁决（从账本事件流切片）
  POST /api/refresh            → 触发从链上重新拉取快照（agent/vouch_state.py）
  POST /api/x402-buy           → 通过 x402 微支付购买信任层 feed（应用代付，链上 CEP-18 结算）
  GET  /api/state              → 旧 RWA 预言机快照（首个入驻 Provider 的数据，保留兼容）

运行：cd web && uvicorn server:app --port 4020
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
STATE_FILE = BASE / "oracle_state.json"  # 旧预言机快照（首个入驻 Provider）
VOUCH_STATE_FILE = BASE / "vouch_state.json"  # 信任层快照
STATIC = BASE / "static"
AGENT_DIR = BASE.parent / "agent"

# x402 买方（官方 Go client + 预置买方密钥）配置，均可用环境变量覆盖。
X402_REPO = os.environ.get("X402_REPO", "/tmp/casper-x402")
BUYER_KEY = os.environ.get("X402_BUYER_KEY", str(BASE.parent / "x402" / "keys-buyer" / "secret_key.pem"))

app = FastAPI(title="Vouch Trust Layer Dashboard")


def _read_vouch_state() -> dict:
    if VOUCH_STATE_FILE.exists():
        return json.loads(VOUCH_STATE_FILE.read_text())
    return {"agents": [], "hires": [], "events": [], "treasury": {}, "updated_at": None}


@app.get("/api/vouch-state")
def get_vouch_state() -> JSONResponse:
    """返回完整信任层快照。"""
    return JSONResponse(_read_vouch_state())


@app.get("/api/reputation/{agent_id}")
def get_reputation(agent_id: int) -> JSONResponse:
    """某 Provider 的信誉（免费只读）。"""
    state = _read_vouch_state()
    for a in state.get("agents", []):
        if a["id"] == agent_id:
            return JSONResponse(a)
    return JSONResponse({"error": f"agent#{agent_id} 不存在"}, status_code=404)


@app.get("/api/verdict/{claim_id}")
def get_verdict(claim_id: int) -> JSONResponse:
    """某 claim 的对抗投票裁决（从账本事件流切片）。"""
    state = _read_vouch_state()
    for e in state.get("events", []):
        if e.get("kind") == "verdict" and e.get("claim_id") == claim_id:
            return JSONResponse(e)
    return JSONResponse({"error": f"claim#{claim_id} 暂无裁决"}, status_code=404)


@app.post("/api/refresh")
def refresh_state() -> JSONResponse:
    """触发 agent 从链上重新拉取快照（会发若干只读查询，约数十秒）。"""
    env = {
        **os.environ,
        "PATH": str(Path.home() / ".cargo" / "bin") + os.pathsep
        + "/opt/homebrew/bin:" + os.environ.get("PATH", ""),
    }
    try:
        result = subprocess.run(
            ["venv/bin/python", "vouch_state.py"],
            cwd=AGENT_DIR, env=env, capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"success": False, "error": "刷新超时"}, status_code=504)
    ok = result.returncode == 0
    return JSONResponse({"success": ok, "log": (result.stdout + result.stderr)[-300:]})


@app.post("/api/x402-buy")
def x402_buy() -> JSONResponse:
    """通过 x402 微支付购买信任层 feed（应用代付，链上 CEP-18 结算）。

    运行官方 Go client，用预置买方账户完成 402→签名→链上结算→取数据。
    资源服务器（:4021）的付费端点现服务信任层 feed（vouch_state.json）。
    """
    env = {
        **os.environ,
        "CLIENT_PRIVATE_KEY_PATH": BUYER_KEY,
        "CLIENT_KEY_ALGO": "ed25519",
        "CAIP2_CHAIN_ID": "casper:casper-test",
        "SERVER_URL": "http://localhost:4021",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""),
    }
    try:
        result = subprocess.run(
            ["go", "run", "./examples/client"],
            cwd=X402_REPO, env=env, capture_output=True, text=True, timeout=240,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"success": False, "error": "结算超时"}, status_code=504)

    out = result.stdout + result.stderr
    tx_match = re.search(r'"transaction":"([0-9a-fA-F]+)"', out)
    settlement_tx = tx_match.group(1) if tx_match else None
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


@app.get("/api/state")
def get_state() -> JSONResponse:
    """旧 RWA 预言机快照（首个入驻 Provider 的产出），保留兼容。"""
    if STATE_FILE.exists():
        return JSONResponse(json.loads(STATE_FILE.read_text()))
    return JSONResponse({"assets": [], "actions": [], "updated_at": None, "contract_hash": ""})


@app.get("/")
def index() -> FileResponse:
    """返回 Vouch 看板页面。"""
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
