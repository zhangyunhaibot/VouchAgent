"""RWA 预言机 Agent 主流程。

一轮工作：抓多源数据 → LLM 判断可信度 →（可信则）上链提交。
当前阶段：链上提交待合约部署后接入，先打通「抓取 + 判断」两步，
光配置 ANTHROPIC_API_KEY 即可跑起来看 AI 大脑工作。
"""
from __future__ import annotations

from dotenv import load_dotenv

from chain import submit_on_chain
from fetcher import fetch_all
from judge import judge_readings


def run_once() -> None:
    """执行一轮预言机工作。"""
    load_dotenv()

    print("① 抓取多源资产数据 ...")
    readings = fetch_all()
    if not readings:
        print("   没有抓到任何数据，跳过本轮。")
        return
    for r in readings:
        print(f"   {r.source:18} {r.asset}  ${r.price:,.2f}")

    print("\n② LLM 交叉核对、判断可信度 ...")
    result = judge_readings(readings)
    print(f"   共识价格：${result.consensus_value:,.2f}")
    print(f"   置信度：  {result.confidence}/100")
    print(f"   可上链：  {'是' if result.is_reliable else '否'}")
    print(f"   理由：    {result.reasoning}")

    print("\n③ 上链提交 ...")
    if not result.is_reliable:
        print("   置信度不足，本轮不提交。")
        return
    asset = readings[0].asset
    print(f"   提交 {asset} = ${result.consensus_value:,.2f}（置信度 {result.confidence}）到 Casper 测试网 ...")
    output = submit_on_chain(asset, result.consensus_value, result.confidence)
    print(f"   ✅ 上链成功：\n   {output.replace(chr(10), chr(10) + '   ')}")


if __name__ == "__main__":
    run_once()
