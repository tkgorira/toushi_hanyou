"""
Yahoo Finance の内部 API を直接使った価格・配当取得プロバイダー。

1ティッカーあたり1リクエストで価格・配当を両方取得する設計。
米国株・日本株（7203.T など）どちらも対応。

将来的に Finnhub や Alpha Vantage に差し替える場合は、
同じインターフェースを持つクラスを作成して
services/price_service.py の _provider を切り替えるだけでよい。
"""

import datetime
import time
import requests

_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9",
}
# リクエスト間の最小待機時間（秒）。短くしすぎるとレート制限を受ける
_REQUEST_INTERVAL = 0.3


def _fetch_chart(ticker: str, range_: str = "2y", events: str = "dividends") -> dict | None:
    """
    Yahoo Finance v8 API からチャートデータを取得する。
    range_=2y + events=dividends で価格・配当を1リクエストで取得。
    失敗時は None を返す。
    """
    try:
        time.sleep(_REQUEST_INTERVAL)
        url = _YAHOO_CHART_URL.format(ticker=ticker)
        params = {"range": range_, "interval": "1d", "events": events}
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"]
        return result[0] if result else None
    except Exception:
        return None


def _parse_dividends(chart: dict) -> dict:
    """
    チャートデータから配当情報を抽出する。
    {
        "annual_dividend": float | None,
        "per_payment": float | None,
        "payments": [{"date": str, "amount": float}, ...],
        "frequency": int | None,
    }
    """
    empty = {
        "annual_dividend": None,
        "per_payment": None,
        "payments": [],
        "payments_last_year": [],
        "frequency": None,
    }
    raw_divs = chart.get("events", {}).get("dividends", {})
    if not raw_divs:
        return empty

    all_payments = sorted(
        [
            {
                "date": datetime.datetime.fromtimestamp(v["date"]).strftime("%Y-%m-%d"),
                "amount": float(v["amount"]),
            }
            for v in raw_divs.values()
        ],
        key=lambda x: x["date"],
        reverse=True,
    )

    cutoff = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
    last_year = [p for p in all_payments if p["date"] >= cutoff]
    annual_dividend = sum(p["amount"] for p in last_year) or None
    frequency = len(last_year) or None

    return {
        "annual_dividend": annual_dividend,
        "per_payment": all_payments[0]["amount"] if all_payments else None,
        "payments": all_payments[:4],
        "payments_last_year": last_year,
        "frequency": frequency,
    }


class YfinanceProvider:
    def get_full_info(self, ticker: str) -> dict:
        """
        価格・銘柄名・配当情報を1リクエストで取得する。
        取得失敗フィールドは None / 空リスト。
        """
        chart = _fetch_chart(ticker)
        if chart is None:
            return {
                "price": None, "name": None,
                "annual_dividend": None, "per_payment": None,
                "payments": [], "payments_last_year": [], "frequency": None,
            }

        meta = chart["meta"]
        return {
            "price": float(meta["regularMarketPrice"]) if meta.get("regularMarketPrice") else None,
            "name": meta.get("longName") or meta.get("shortName"),
            **_parse_dividends(chart),
        }

    def get_price(self, ticker: str) -> float | None:
        """現在の株価のみ取得（単独呼び出し用）。"""
        chart = _fetch_chart(ticker, range_="1d", events="")
        if chart is None:
            return None
        price = chart["meta"].get("regularMarketPrice")
        return float(price) if price is not None else None

    def get_name(self, ticker: str) -> str | None:
        """銘柄名のみ取得（追加フォーム用）。"""
        chart = _fetch_chart(ticker, range_="1d", events="")
        if chart is None:
            return None
        meta = chart["meta"]
        return meta.get("longName") or meta.get("shortName")
