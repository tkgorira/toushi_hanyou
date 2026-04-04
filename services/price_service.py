"""
価格・配当取得サービス層。
プロバイダーを直接呼び出さず、この層を経由することで差し替えを容易にする。
"""

from providers.yfinance_provider import YfinanceProvider

# プロバイダーはここで切り替える（将来: FinnhubProvider など）
_provider = YfinanceProvider()


def get_price(ticker: str) -> float | None:
    """指定 ticker の現在価格を返す。取得失敗時は None。"""
    return _provider.get_price(ticker)


def get_name(ticker: str) -> str | None:
    """指定 ticker の銘柄名を返す。取得失敗時は None。"""
    return _provider.get_name(ticker)


def get_dividend_info(ticker: str) -> dict:
    """指定 ticker の配当情報を返す。"""
    return _provider.get_dividend_info(ticker)


def get_usdjpy() -> float | None:
    """USD/JPY レートを返す。取得失敗時は None。"""
    return _provider.get_price("JPY=X")


def _convert_div(annual_div: float, stock_currency: str,
                 goal_currency: str, usdjpy: float | None) -> float | None:
    """
    配当額を目標通貨に換算する。
    USD↔JPY 以外の組み合わせ、または為替レート未取得の場合は None を返す。
    """
    if stock_currency == goal_currency:
        return annual_div
    if usdjpy is None:
        return None  # 為替レート未取得のため換算不可
    if stock_currency == "USD" and goal_currency == "JPY":
        return annual_div * usdjpy
    if stock_currency == "JPY" and goal_currency == "USD":
        return annual_div / usdjpy
    return None  # その他の通貨ペアは未対応


def enrich_holdings(
    holdings: list,
    monthly_goal: float | None = None,
    goal_currency: str = "JPY",
    usdjpy: float | None = None,
) -> list[dict]:
    """
    Holding モデルのリストに現在価格・損益・配当情報を付加して返す。
    1ティッカーあたり1リクエストで全情報を取得する。
    monthly_goal が指定された場合、為替換算した上で買い増し株数を計算する。
    """
    results = []
    for h in holdings:
        info = _provider.get_full_info(h.ticker)
        price = info["price"]
        annual_div = info["annual_dividend"]

        # 損益計算
        if price is not None:
            market_value = price * h.quantity
            cost_basis = h.average_cost * h.quantity
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis != 0 else None
        else:
            market_value = pnl = pnl_pct = None

        # 配当利回り
        div_yield = (annual_div / price * 100) if (price and annual_div) else None

        # 買い増し株数（目標通貨に為替換算してから計算）
        shares_to_add = None
        fx_converted = False
        if monthly_goal and annual_div and annual_div > 0:
            div_in_goal_currency = _convert_div(
                annual_div, h.currency, goal_currency, usdjpy
            )
            if div_in_goal_currency and div_in_goal_currency > 0:
                required_shares = (monthly_goal * 12) / div_in_goal_currency
                shares_to_add = max(0.0, required_shares - h.quantity)
                fx_converted = (h.currency != goal_currency)

        results.append({
            "id": h.id,
            "ticker": h.ticker,
            "name": h.name or info.get("name") or h.ticker,
            "market": h.market,
            "quantity": h.quantity,
            "average_cost": h.average_cost,
            "currency": h.currency,
            "memo": h.memo,
            # 価格・損益
            "price": price,
            "market_value": market_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            # 配当
            "annual_dividend": annual_div,
            "per_payment": info["per_payment"],
            "payments": info["payments"],
            "frequency": info["frequency"],
            "div_yield": div_yield,
            # 目標計算
            "shares_to_add": shares_to_add,
            "fx_converted": fx_converted,   # 為替換算が行われたか
        })
    return results
