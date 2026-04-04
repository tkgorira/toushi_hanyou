"""
yfinance を使った価格取得プロバイダー。
将来的に Finnhub や Alpha Vantage に差し替える場合は、
同じインターフェース (get_price / get_name) を持つクラスを作成して
services/price_service.py の provider を切り替えるだけでよい。
"""

import yfinance as yf


class YfinanceProvider:
    def get_price(self, ticker: str) -> float | None:
        """現在の株価を返す。取得失敗時は None を返す。"""
        try:
            info = yf.Ticker(ticker).fast_info
            price = info.last_price
            if price is None or price != price:  # NaN チェック
                return None
            return float(price)
        except Exception:
            return None

    def get_name(self, ticker: str) -> str | None:
        """銘柄名を返す。取得失敗時は None を返す。"""
        try:
            info = yf.Ticker(ticker).info
            return info.get("longName") or info.get("shortName")
        except Exception:
            return None
