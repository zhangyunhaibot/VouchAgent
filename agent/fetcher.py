"""多源资产价格抓取。

从多个相互独立的公开数据源抓取同一资产（目前是黄金 XAU/USD）的价格，
供后续 LLM 交叉核对、判断数据可信度使用。所有数据源均免密钥。

设计要点：用多个独立来源的报价做"交叉验证"，是这个预言机能给出
可信度判断的基础——单一来源无法判断数据是否被污染，多来源才能。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

REQUEST_TIMEOUT = 10


@dataclass
class PriceReading:
    """单个数据源的一次报价。"""

    source: str  # 数据源名称
    asset: str  # 资产标识，如 "XAU/USD"
    price: float  # 美元价格
    timestamp: int  # 抓取时的 Unix 秒级时间戳


def fetch_gold_api() -> PriceReading:
    """从 gold-api.com 抓取黄金现货价（XAU/USD）。"""
    resp = requests.get("https://api.gold-api.com/price/XAU", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return PriceReading(
        source="gold-api.com",
        asset="XAU/USD",
        price=float(data["price"]),
        timestamp=int(time.time()),
    )


def fetch_coingecko_paxg() -> PriceReading:
    """从 CoinGecko 抓取 PAX Gold（锚定实物黄金的 RWA 代币）价格。"""
    resp = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "pax-gold", "vs_currencies": "usd"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return PriceReading(
        source="coingecko-paxg",
        asset="XAU/USD",
        price=float(data["pax-gold"]["usd"]),
        timestamp=int(time.time()),
    )


# 所有数据源抓取函数。新增数据源只需在此登记。
SOURCES = [fetch_gold_api, fetch_coingecko_paxg]


def fetch_all() -> list[PriceReading]:
    """抓取所有数据源；单个源失败不影响其他源。"""
    readings: list[PriceReading] = []
    for fn in SOURCES:
        try:
            readings.append(fn())
        except Exception as exc:  # noqa: BLE001 — 单源失败需容错，不能中断整体
            print(f"[fetcher] 数据源 {fn.__name__} 抓取失败: {exc}")
    return readings


if __name__ == "__main__":
    for r in fetch_all():
        print(f"{r.source:18} {r.asset}  ${r.price:,.2f}  @{r.timestamp}")
