from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import requests

import market_data


class MarketDataTest(unittest.TestCase):
    @staticmethod
    def _response(payload: dict) -> Mock:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @patch("market_data.requests.get")
    def test_fetch_realtime_quote_parses_latest_price(self, get: Mock) -> None:
        timestamp = 1_786_952_097
        get.return_value = self._response(
            {
                "rc": 0,
                "data": {
                    "f43": 12.33,
                    "f57": "300945",
                    "f58": "曼卡龙",
                    "f59": 2,
                    "f86": timestamp,
                },
            }
        )

        quote = market_data.fetch_realtime_quote("300945.SZ")

        self.assertEqual(quote.symbol, "300945.SZ")
        self.assertEqual(quote.name, "曼卡龙")
        self.assertEqual(quote.price, 12.33)
        self.assertEqual(
            quote.price_time,
            datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.assertEqual(quote.source, "东方财富实时行情")
        self.assertEqual(get.call_args.kwargs["params"]["secid"], "0.300945")
        self.assertEqual(
            get.call_args.kwargs["timeout"], market_data.QUOTE_TIMEOUT_SECONDS
        )

    @patch("market_data.requests.get")
    def test_fetch_realtime_quote_maps_shanghai_market(self, get: Mock) -> None:
        get.return_value = self._response(
            {
                "rc": 0,
                "data": {
                    "f43": 10.55,
                    "f57": "600000",
                    "f58": "浦发银行",
                    "f86": 1_786_952_097,
                },
            }
        )

        market_data.fetch_realtime_quote("600000.SH")

        self.assertEqual(get.call_args.kwargs["params"]["secid"], "1.600000")

    @patch("market_data.requests.get")
    def test_fetch_realtime_quote_accepts_ss_as_shanghai_alias(
        self, get: Mock
    ) -> None:
        get.return_value = self._response(
            {
                "rc": 0,
                "data": {
                    "f43": 10.55,
                    "f57": "600000",
                    "f58": "浦发银行",
                    "f86": 1_786_952_097,
                },
            }
        )

        quote = market_data.fetch_realtime_quote("600000.SS")

        self.assertEqual(quote.symbol, "600000.SH")
        self.assertEqual(get.call_args.kwargs["params"]["secid"], "1.600000")

    @patch("market_data.requests.get")
    def test_fetch_realtime_quote_reports_provider_failure(self, get: Mock) -> None:
        get.side_effect = requests.Timeout("timeout")

        with patch("market_data.time.sleep") as sleep:
            with self.assertRaisesRegex(market_data.MarketDataError, "请稍后重试"):
                market_data.fetch_realtime_quote("300945.SZ")

        self.assertEqual(get.call_count, market_data.QUOTE_MAX_ATTEMPTS * 2)
        self.assertEqual(sleep.call_count, (market_data.QUOTE_MAX_ATTEMPTS - 1) * 2)

    @patch("market_data._fetch_eastmoney_quote")
    @patch("market_data.requests.get")
    def test_fetch_realtime_quote_falls_back_to_tencent(
        self,
        get: Mock,
        eastmoney: Mock,
    ) -> None:
        eastmoney.side_effect = market_data.MarketDataError("eastmoney down")
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = (
            'v_sz300945="51~曼卡龙~300945~12.33~11.79~12.08~157592~'
            '82695~74898~12.33~195~12.32~8~12.31~260~12.30~125~12.29~12~'
            '12.34~142~12.35~178~12.36~83~12.37~52~12.38~120~~'
            '20260817161457~0.54~4.58~";'
        ).encode("gbk")
        get.return_value = response

        quote = market_data.fetch_realtime_quote("300945.SZ")

        self.assertEqual(quote.price, 12.33)
        self.assertEqual(quote.price_time, "2026-08-17 16:14:57")
        self.assertEqual(quote.source, "腾讯财经实时行情")
        self.assertEqual(get.call_args.args[0], "https://qt.gtimg.cn/q=sz300945")

    @patch("market_data.fetch_realtime_quote")
    def test_fetch_realtime_quotes_keeps_partial_results(self, fetch: Mock) -> None:
        def side_effect(symbol: str) -> market_data.RealtimeQuote:
            if symbol == "000001.SZ":
                raise market_data.MarketDataError("000001.SZ 行情失败")
            return market_data.RealtimeQuote(
                symbol=symbol,
                name="浦发银行",
                price=10.55,
                price_time="2026-08-17 15:00:00",
            )

        fetch.side_effect = side_effect

        quotes, failures = market_data.fetch_realtime_quotes(
            ["600000.SH", "000001.SZ"]
        )

        self.assertEqual(quotes["600000.SH"].price, 10.55)
        self.assertEqual(failures, {"000001.SZ": "000001.SZ 行情失败"})


if __name__ == "__main__":
    unittest.main()
