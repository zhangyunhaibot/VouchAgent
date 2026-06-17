"""Coordinator Agent —— 多智能体预言机网络的大脑。

用 DeepSeek 的 function calling，让 LLM【自主编排】整个工作流：
查资产 → 抓多源价格 + Judge 交叉验证 → 可靠则上链 → Risk 评估 → 更新链上信誉分。

这是"真·Agentic"的体现：控制流由 LLM 自己决定（调哪个工具、什么顺序、
是否跳过不可靠数据、何时奖惩信誉），而不是写死的 if-else 流水线。

工具背后是三个独立智能体的分工：
- Judge Agent（judge.py）：数据可信吗？
- Risk Agent（risk.py）：要不要奖惩这个源？
- Coordinator（本文件）：统筹决策 + 调用链上动作。
"""
from __future__ import annotations

import json
import os
import re

from openai import OpenAI


def _extract_tx_url(output: str) -> str | None:
    """从合约 bin 输出里提取 cspr.live 交易链接。"""
    m = re.search(r"https://testnet\.cspr\.live/transaction/[0-9a-fA-F]+", output)
    return m.group(0) if m else None

from chain import submit_on_chain, update_reputation_on_chain
from fetcher import list_assets
from judge import judge_asset
from risk import assess_risk as run_risk_agent


class OracleTools:
    """协调器可调用的工具集合，内部维护每个资产的中间状态，避免 LLM 传错值。"""

    def __init__(self, max_assets: int | None = None, verbose: bool = True):
        self.state: dict[str, dict] = {}  # asset -> {readings, judgement, risk}
        self.actions: list[dict] = []  # 链上动作日志（供 Dashboard / 演示）
        self.max_assets = max_assets
        self.verbose = verbose

    # ---- 工具实现 ----

    def get_assets(self) -> dict:
        assets = list_assets()
        if self.max_assets is not None:
            assets = assets[: self.max_assets]
        return {"assets": assets}

    def fetch_and_judge(self, asset: str) -> dict:
        readings, judgement = judge_asset(asset)
        self.state[asset] = {"readings": readings, "judgement": judgement}
        return {
            "asset": asset,
            "prices": [{"source": r.source, "price": round(r.price, 4)} for r in readings],
            "consensus_value": round(judgement.consensus_value, 4),
            "confidence": judgement.confidence,
            "is_reliable": judgement.is_reliable,
            "reasoning": judgement.reasoning,
        }

    def assess_risk(self, asset: str) -> dict:
        st = self.state.get(asset)
        if not st:
            return {"error": f"请先对 {asset} 调用 fetch_and_judge"}
        risk = run_risk_agent(asset, st["readings"], st["judgement"])
        st["risk"] = risk
        return {
            "asset": asset,
            "accurate": risk.accurate,
            "risk_level": risk.risk_level,
            "reasoning": risk.reasoning,
        }

    def submit_to_chain(self, asset: str) -> dict:
        st = self.state.get(asset)
        if not st or "judgement" not in st:
            return {"error": f"请先对 {asset} 调用 fetch_and_judge"}
        j = st["judgement"]
        if not j.is_reliable:
            return {"asset": asset, "submitted": False, "reason": "数据不可靠，按规则不上链"}
        output = submit_on_chain(asset, j.consensus_value, j.confidence, len(st["readings"]))
        tx_url = _extract_tx_url(output)
        st["submit_tx"] = tx_url
        self.actions.append({"action": "submit", "asset": asset, "tx": tx_url})
        return {"asset": asset, "submitted": True, "tx": tx_url}

    def update_reputation(self, asset: str) -> dict:
        st = self.state.get(asset)
        if not st or "risk" not in st:
            return {"error": f"请先对 {asset} 调用 assess_risk"}
        output = update_reputation_on_chain(asset, st["risk"].accurate)
        tx_url = _extract_tx_url(output)
        st["score_tx"] = tx_url
        # 解析链上返回的最新信誉分。
        m = re.search(r"reputation=(\d+)", output)
        if m:
            st["reputation"] = int(m.group(1))
        self.actions.append({"action": "score", "asset": asset, "tx": tx_url})
        return {"asset": asset, "scored": True, "tx": tx_url}

    # ---- 快照（供 Dashboard / API 读取）----

    def snapshot(self) -> dict:
        """把本轮各资产的最新状态导出为可序列化的字典。"""
        assets = []
        for asset, st in self.state.items():
            j = st.get("judgement")
            risk = st.get("risk")
            assets.append({
                "asset": asset,
                "prices": [{"source": r.source, "price": round(r.price, 4)} for r in st.get("readings", [])],
                "consensus_value": round(j.consensus_value, 4) if j else None,
                "confidence": j.confidence if j else None,
                "is_reliable": j.is_reliable if j else None,
                "reasoning": j.reasoning if j else None,
                "risk_level": risk.risk_level if risk else None,
                "risk_reasoning": risk.reasoning if risk else None,
                "reputation": st.get("reputation"),
                "submit_tx": st.get("submit_tx"),
                "score_tx": st.get("score_tx"),
            })
        return {"assets": assets, "actions": self.actions}

    # ---- 分发 ----

    def dispatch(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if fn is None:
            return {"error": f"未知工具 {name}"}
        try:
            return fn(**args)
        except Exception as exc:  # noqa: BLE001 — 工具失败要回传给 LLM 让它应对
            return {"error": f"{name} 执行失败: {exc}"}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_assets",
            "description": "获取当前需要监控的所有资产标识列表。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_and_judge",
            "description": "抓取某资产的多源价格，并由 Judge Agent 交叉验证，返回共识价、置信度、是否可靠。",
            "parameters": {
                "type": "object",
                "properties": {"asset": {"type": "string", "description": "资产标识，如 XAU/USD"}},
                "required": ["asset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_risk",
            "description": "由 Risk Agent 评估某资产本轮数据的风险，决定其链上信誉分应加还是减（需先 fetch_and_judge）。",
            "parameters": {
                "type": "object",
                "properties": {"asset": {"type": "string"}},
                "required": ["asset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_to_chain",
            "description": "把某资产的共识数据提交到 Casper 链上的 RwaOracle 合约（数据不可靠会自动跳过；需先 fetch_and_judge）。",
            "parameters": {
                "type": "object",
                "properties": {"asset": {"type": "string"}},
                "required": ["asset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_reputation",
            "description": "按 Risk Agent 的判定，更新某资产在链上的信誉分（需先 assess_risk）。",
            "parameters": {
                "type": "object",
                "properties": {"asset": {"type": "string"}},
                "required": ["asset"],
            },
        },
    },
]


COORDINATOR_SYSTEM = """你是一个自主运行的 RWA（真实世界资产）链上预言机网络的协调器（Coordinator Agent）。
你管理多个真实资产的价格数据源，目标是让链上数据保持新鲜、可信。

你可以调用这些工具：
- get_assets：获取要监控的资产列表
- fetch_and_judge：抓某资产多源价格 + Judge 交叉验证（给出置信度、是否可靠）
- submit_to_chain：把可靠数据提交上链
- assess_risk：让 Risk Agent 评估该源本轮表现
- update_reputation：按 Risk 判定更新链上信誉分

每轮工作流程（你自己决定调用顺序）：
1. get_assets 看有哪些资产。
2. 对每个资产 fetch_and_judge。
3. 若数据可靠（is_reliable=true）就 submit_to_chain；不可靠则跳过、不上链。
4. assess_risk 评估，再 update_reputation 更新信誉分。
5. 全部处理完后，用中文简要总结本轮：每个资产做了什么、为什么。

请高效行动，不要重复调用。最后给出总结即可。"""


def run_cycle(model: str | None = None, max_assets: int | None = None,
              max_steps: int = 40, verbose: bool = True) -> OracleTools:
    """运行协调器一轮，返回工具状态（含链上动作日志）。需要 DEEPSEEK_API_KEY。"""
    model = model or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
    )
    tools = OracleTools(max_assets=max_assets, verbose=verbose)
    messages = [
        {"role": "system", "content": COORDINATOR_SYSTEM},
        {"role": "user", "content": "开始本轮监控。"},
    ]

    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=TOOL_SCHEMAS
        )
        msg = resp.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            if verbose and msg.content:
                print(f"\n🧠 [Coordinator 总结]\n{msg.content}")
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            if verbose:
                print(f"  🔧 {name}({', '.join(f'{k}={v}' for k, v in args.items())})")
            result = tools.dispatch(name, args)
            if verbose and result.get("error"):
                print(f"     ⚠️  {result['error']}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    return tools
