"""多资产、多源价格抓取。

为每个资产从多个【相互独立】的公开数据源抓价格，供后续 LLM 交叉核对、
判断可信度使用。覆盖贵金属(黄金)、加密资产(BTC)、外汇(EUR/USD)。
所有数据源均免密钥。

设计要点：用多个独立来源做交叉验证，是这个预言机能给出可信度判断的基础——
单一来源无法判断数据是否被污染，多来源才能。
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


# ---- 各数据源的取价函数（只负责返回一个 float 价格）----


def _gold_api(symbol: str) -> float:
    """gold-api.com 贵金属现货价（XAU=黄金, XAG=白银）。"""
    r = requests.get(f"https://api.gold-api.com/price/{symbol}", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return float(r.json()["price"])


def _coingecko(coin_id: str) -> float:
    """CoinGecko 简单价格（pax-gold=锚定黄金的RWA代币, bitcoin=BTC）。"""
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return float(r.json()[coin_id]["usd"])


def _coinbase(pair: str) -> float:
    """Coinbase 现货价（如 BTC-USD）。"""
    r = requests.get(f"https://api.coinbase.com/v2/prices/{pair}/spot", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return float(r.json()["data"]["amount"])


def _frankfurter(base: str, quote: str) -> float:
    """Frankfurter（欧洲央行汇率）。"""
    r = requests.get(
        "https://api.frankfurter.dev/v1/latest",
        params={"base": base, "symbols": quote},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return float(r.json()["rates"][quote])


def _er_api(base: str, quote: str) -> float:
    """open.er-api.com 汇率。"""
    r = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return float(r.json()["rates"][quote])


# ---- 资产 → 多个独立数据源 ----
# 每个数据源是 (来源名, 取价函数)。新增资产/源只需在此登记。
_SOURCES: dict[str, list[tuple[str, callable]]] = {
    "XAU/USD": [
        ("gold-api.com", lambda: _gold_api("XAU")),
        ("coingecko-paxg", lambda: _coingecko("pax-gold")),
    ],
    "BTC/USD": [
        ("coinbase", lambda: _coinbase("BTC-USD")),
        ("coingecko", lambda: _coingecko("bitcoin")),
    ],
    "EUR/USD": [
        ("frankfurter", lambda: _frankfurter("EUR", "USD")),
        ("open-er-api", lambda: _er_api("EUR", "USD")),
    ],
}


def list_assets() -> list[str]:
    """返回所有支持的资产标识。"""
    return list(_SOURCES.keys())


def fetch_asset(asset: str) -> list[PriceReading]:
    """抓取某个资产的所有数据源；单源失败不影响其他源。"""
    readings: list[PriceReading] = []
    for source_name, price_fn in _SOURCES.get(asset, []):
        try:
            readings.append(
                PriceReading(
                    source=source_name,
                    asset=asset,
                    price=price_fn(),
                    timestamp=int(time.time()),
                )
            )
        except Exception as exc:  # noqa: BLE001 — 单源失败需容错
            print(f"[fetcher] {asset} 数据源 {source_name} 抓取失败: {exc}")
    return readings


if __name__ == "__main__":
    for asset in list_assets():
        print(f"\n{asset}:")
        for r in fetch_asset(asset):
            print(f"  {r.source:16} ${r.price:,.4f}")
