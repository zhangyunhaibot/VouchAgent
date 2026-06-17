"""Judge Agent —— LLM 数据可信度判断（使用 DeepSeek）。

接收某资产来自多个【相互独立】数据源的报价，用 DeepSeek 交叉核对：
- 各源是否相互吻合？偏差多大？
- 是否存在明显异常值（某个源被污染 / 延迟）？
据此给出共识价格、0-100 的置信度，以及判断理由。

这是整个预言机"可信"的核心——单一来源无法判断数据真假，
多来源交叉验证 + LLM 推理，才能给出有依据的置信度。

DeepSeek 提供 OpenAI 兼容接口，故用 openai SDK，指向 https://api.deepseek.com。
"""
from __future__ import annotations

import json
import os

from openai import OpenAI
from pydantic import BaseModel, Field

from fetcher import PriceReading, fetch_asset


class Judgement(BaseModel):
    """Judge Agent 对一组报价的可信度判断结果。"""

    consensus_value: float = Field(description="综合多个数据源后认定的共识价格（美元）")
    confidence: int = Field(description="数据可信度，0-100 的整数", ge=0, le=100)
    is_reliable: bool = Field(description="该数据是否足够可信、可以上链")
    reasoning: str = Field(description="一句话说明判断依据（中文）")


# 注意：DeepSeek 的 JSON 模式要求 prompt 中出现 "json" 字样并给出输出示例。
SYSTEM_PROMPT = """你是一个 RWA（真实世界资产）链上预言机的数据质检员（Judge Agent）。
你会收到同一资产来自多个【相互独立】数据源的报价，你的职责是交叉核对，判断数据是否可信。

判断原则：
- 多个独立来源高度吻合（偏差很小）→ 高置信度。
- 来源之间存在明显偏差 → 按偏差大小相应降低置信度。
- 出现明显异常值（某个源远离其他源）→ 视为可疑，显著降低置信度。
- 只有单一来源、无法交叉验证 → 置信度不应过高。

confidence 取值参考：相对偏差 <0.5% 给 90-100；0.5%-2% 给 70-90；2%-5% 给 40-70；>5% 给 0-40。
is_reliable：confidence >= 70 时为 true，否则为 false。
consensus_value：取各可信来源的中位数或均值。

请只输出一个 JSON 对象，字段如下：
- consensus_value (number)：共识价格（美元）
- confidence (integer, 0-100)：数据可信度
- is_reliable (boolean)：是否可上链
- reasoning (string)：一句话中文理由

JSON 输出示例：
{"consensus_value": 4330.5, "confidence": 95, "is_reliable": true, "reasoning": "两个独立来源偏差仅0.3%，高度吻合"}"""


def _client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
    )


def judge_readings(readings: list[PriceReading], model: str | None = None) -> Judgement:
    """对一组报价做可信度判断，返回结构化结果。需要 DEEPSEEK_API_KEY。"""
    if not readings:
        raise ValueError("没有任何数据源报价，无法判断")

    model = model or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    quote_lines = "\n".join(
        f"- 来源 {r.source}：{r.asset} = ${r.price:,.4f}" for r in readings
    )
    user_msg = (
        f"资产：{readings[0].asset}\n"
        f"各数据源报价：\n{quote_lines}\n\n"
        f"请交叉核对这些报价并按要求输出 JSON 判断。"
    )

    response = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        max_tokens=1024,
    )
    data = json.loads(response.choices[0].message.content)
    return Judgement(**data)


def judge_asset(asset: str, model: str | None = None) -> tuple[list[PriceReading], Judgement]:
    """抓取某资产的多源报价并做判断，返回 (报价列表, 判断结果)。"""
    readings = fetch_asset(asset)
    return readings, judge_readings(readings, model)


if __name__ == "__main__":
    from dotenv import load_dotenv

    from fetcher import list_assets

    load_dotenv()
    for a in list_assets():
        readings, result = judge_asset(a)
        srcs = ", ".join(f"{r.source}=${r.price:,.2f}" for r in readings)
        print(f"\n{a}: {srcs}")
        print(
            f"  → 共识 ${result.consensus_value:,.2f} | 置信度 {result.confidence} "
            f"| {'可上链' if result.is_reliable else '不可上链'} | {result.reasoning}"
        )
