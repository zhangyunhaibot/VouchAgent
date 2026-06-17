"""Risk Agent —— 评估数据风险并决定信誉分调整（使用 DeepSeek）。

独立于 Judge Agent 的第二个 LLM 智能体：在 Judge 给出置信度后，
Risk Agent 从"信誉管理"角度再判一次——这个数据源本轮表现是否可靠，
据此决定该资产在链上的信誉分应该 +1 还是 -1，并给出风险等级。

这体现了多智能体分工：Judge 负责"数据可信吗"，Risk 负责"要不要奖惩这个源"。
"""
from __future__ import annotations

import json
import os

from openai import OpenAI
from pydantic import BaseModel, Field

from fetcher import PriceReading
from judge import Judgement


class RiskAssessment(BaseModel):
    """Risk Agent 的风险评估结果。"""

    accurate: bool = Field(description="本轮数据是否判定为可靠（true→信誉分+1，false→-1）")
    risk_level: str = Field(description="风险等级：low / medium / high")
    reasoning: str = Field(description="一句话说明评估依据（中文）")


SYSTEM_PROMPT = """你是 RWA 链上预言机的风险评估官（Risk Agent）。
Judge Agent 已经对某资产本轮的多源报价做了可信度判断，现在你从"信誉管理"角度再评一次：
这个预言机数据源本轮的表现，是否值得给它的链上信誉分加分？

判断原则：
- 多源高度吻合、置信度高（>=90）、无异常 → accurate=true，风险 low。
- 置信度中等（70-90）、轻微偏差 → accurate=true，风险 medium。
- 置信度低（<70）、有异常源、偏差大 → accurate=false，风险 high。

请只输出一个 JSON 对象，字段如下：
- accurate (boolean)：本轮是否可靠（决定信誉分增减）
- risk_level (string)：low / medium / high
- reasoning (string)：一句话中文理由

JSON 输出示例：
{"accurate": true, "risk_level": "low", "reasoning": "两源偏差0.3%、置信度95，数据源表现可靠"}"""


def assess_risk(
    asset: str,
    readings: list[PriceReading],
    judgement: Judgement,
    reputation: int | None = None,
    model: str | None = None,
) -> RiskAssessment:
    """评估某资产本轮数据的风险，决定信誉分调整方向。需要 DEEPSEEK_API_KEY。"""
    model = model or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
    )

    quote_lines = "\n".join(f"- {r.source}：${r.price:,.4f}" for r in readings)
    rep_line = f"该资产当前链上信誉分：{reputation}\n" if reputation is not None else ""
    user_msg = (
        f"资产：{asset}\n"
        f"本轮多源报价：\n{quote_lines}\n"
        f"Judge 判断：共识 ${judgement.consensus_value:,.4f}，置信度 {judgement.confidence}，"
        f"{'可上链' if judgement.is_reliable else '不可上链'}\n"
        f"{rep_line}\n"
        f"请按要求输出 JSON 风险评估。"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        max_tokens=512,
    )
    data = json.loads(response.choices[0].message.content)
    return RiskAssessment(**data)
