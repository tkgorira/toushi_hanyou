"""
価格取得サービス層。
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


def enrich_holdings(holdings: list) -> list[dict]:
    """
    Holding モデルのリストに現在価格・損益情報を付加して返す。
    価格取得失敗時は price=None として呼び出し元で N/A 表示する。
    """
    results = []
    for h in holdings:
        price = get_price(h.ticker)

        if price is not None:
            market_value = price * h.quantity
            cost_basis = h.average_cost * h.quantity
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis != 0 else None
        else:
            market_value = None
            pnl = None
            pnl_pct = None

        results.append({
            "id": h.id,
            "ticker": h.ticker,
            "name": h.name or h.ticker,
            "market": h.market,
            "quantity": h.quantity,
            "average_cost": h.average_cost,
            "currency": h.currency,
            "memo": h.memo,
            "price": price,
            "market_value": market_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })
    return results
