from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Iterable

import requests


EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={market}{code}"
QUOTE_TIMEOUT_SECONDS = 10
QUOTE_MAX_ATTEMPTS = 2
QUOTE_RETRY_BACKOFF_SECONDS = 0.35
EASTMONEY_QUOTE_SOURCE = "东方财富实时行情"
TENCENT_QUOTE_SOURCE = "腾讯财经实时行情"


class MarketDataError(ValueError):
    """Raised when a real-time quote cannot be obtained or validated."""


@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str
    name: str
    price: float
    price_time: str
    source: str = EASTMONEY_QUOTE_SOURCE


def _normalize_symbol(symbol: str) -> tuple[str, str, int]:
    normalized = symbol.strip().upper()
    if "." not in normalized:
        raise MarketDataError(f"股票代码缺少市场后缀：{normalized or symbol}")
    code, exchange = normalized.rsplit(".", 1)
    if len(code) != 6 or not code.isdigit():
        raise MarketDataError(f"股票代码格式不正确：{normalized}")
    if exchange == "SH":
        market_id = 1
    elif exchange in {"SZ", "BJ"}:
        market_id = 0
    else:
        raise MarketDataError(f"暂不支持该交易所：{exchange}")
    return normalized, code, market_id


def _fetch_eastmoney_quote(
    normalized: str,
    code: str,
    market_id: int,
) -> RealtimeQuote:
    payload = None
    last_error: Exception | None = None
    for attempt in range(QUOTE_MAX_ATTEMPTS):
        try:
            response = requests.get(
                EASTMONEY_QUOTE_URL,
                params={
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f43,f57,f58,f59,f86",
                    "secid": f"{market_id}.{code}",
                    "_": str(int(time.time() * 1000)),
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"
                    ),
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=QUOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < QUOTE_MAX_ATTEMPTS:
                time.sleep(QUOTE_RETRY_BACKOFF_SECONDS * (attempt + 1))
    if payload is None:
        raise MarketDataError("东方财富实时行情请求失败。") from last_error

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise MarketDataError("东方财富暂无实时行情数据。")
    if str(data.get("f57") or "") != code:
        raise MarketDataError("东方财富实时行情代码校验失败。")
    try:
        price = float(data["f43"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError("东方财富暂无有效最新价。") from exc
    if price <= 0:
        raise MarketDataError("东方财富暂无有效最新价。")

    quote_timestamp = data.get("f86")
    try:
        price_time = datetime.fromtimestamp(int(quote_timestamp)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        price_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return RealtimeQuote(
        symbol=normalized,
        name=str(data.get("f58") or "").strip(),
        price=price,
        price_time=price_time,
        source=EASTMONEY_QUOTE_SOURCE,
    )


def _fetch_tencent_quote(
    normalized: str,
    code: str,
    exchange: str,
) -> RealtimeQuote:
    market_prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}[exchange]
    response = None
    last_error: Exception | None = None
    for attempt in range(QUOTE_MAX_ATTEMPTS):
        try:
            response = requests.get(
                TENCENT_QUOTE_URL.format(market=market_prefix, code=code),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"
                    ),
                    "Referer": "https://gu.qq.com/",
                },
                timeout=QUOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            response = None
            last_error = exc
            if attempt + 1 < QUOTE_MAX_ATTEMPTS:
                time.sleep(QUOTE_RETRY_BACKOFF_SECONDS * (attempt + 1))
    if response is None:
        raise MarketDataError("腾讯财经实时行情请求失败。") from last_error

    try:
        text = response.content.decode("gbk", errors="strict")
        quote_text = text.split('"', 2)[1]
        fields = quote_text.split("~")
        if fields[2] != code:
            raise ValueError("symbol mismatch")
        price = float(fields[3])
        if price <= 0:
            raise ValueError("invalid price")
        price_time = datetime.strptime(fields[30], "%Y%m%d%H%M%S").strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (IndexError, TypeError, UnicodeError, ValueError) as exc:
        raise MarketDataError("腾讯财经暂无有效实时行情数据。") from exc

    return RealtimeQuote(
        symbol=normalized,
        name=fields[1].strip(),
        price=price,
        price_time=price_time,
        source=TENCENT_QUOTE_SOURCE,
    )


def fetch_realtime_quote(symbol: str) -> RealtimeQuote:
    """Fetch the latest A-share quote with a second provider fallback.

    The returned timestamp is supplied by the market data provider. Outside
    trading hours, this is normally the last quoted price.
    """

    normalized, code, market_id = _normalize_symbol(symbol)
    exchange = normalized.rsplit(".", 1)[1]
    try:
        return _fetch_eastmoney_quote(normalized, code, market_id)
    except MarketDataError as eastmoney_error:
        try:
            return _fetch_tencent_quote(normalized, code, exchange)
        except MarketDataError as tencent_error:
            raise MarketDataError(
                f"{normalized} 实时行情请求失败，请稍后重试。"
            ) from ExceptionGroup(
                "所有实时行情源均不可用",
                [eastmoney_error, tencent_error],
            )


def fetch_realtime_quotes(
    symbols: Iterable[str],
    *,
    max_workers: int = 4,
) -> tuple[dict[str, RealtimeQuote], dict[str, str]]:
    """Fetch several quotes concurrently while keeping per-symbol errors."""

    unique_symbols = list(dict.fromkeys(symbols))
    if not unique_symbols:
        return {}, {}
    quotes: dict[str, RealtimeQuote] = {}
    failures: dict[str, str] = {}
    worker_count = max(1, min(max_workers, len(unique_symbols)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_realtime_quote, symbol): symbol
            for symbol in unique_symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                quote = future.result()
            except MarketDataError as exc:
                failures[symbol] = str(exc)
            except Exception:
                failures[symbol] = f"{symbol} 实时行情请求发生未知错误。"
            else:
                quotes[symbol] = quote
    return quotes, failures
