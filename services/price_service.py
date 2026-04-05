"""
価格・配当取得サービス層。
プロバイダーを直接呼び出さず、この層を経由することで差し替えを容易にする。
"""

import math
import time

from providers.yfinance_provider import YfinanceProvider

# プロバイダーはここで切り替える（将来: FinnhubProvider など）
_provider = YfinanceProvider()

_ACCOUNT_TAX_RATES = {
    # 要望に合わせて NISA は受取配当を 10% 減算
    "NISA": 0.10,
    # 特定口座は一般的な源泉徴収税率
    "TOKUTEI": 0.20315,
}

_RECOMMENDATION_CANDIDATES = [
    {"ticker": "JEPI", "currency": "USD"},
    {"ticker": "JEPQ", "currency": "USD"},
    {"ticker": "QYLD", "currency": "USD"},
    {"ticker": "XYLD", "currency": "USD"},
    {"ticker": "SPYD", "currency": "USD"},
    {"ticker": "VYM", "currency": "USD"},
    {"ticker": "HDV", "currency": "USD"},
    {"ticker": "DVY", "currency": "USD"},
    {"ticker": "8306.T", "currency": "JPY"},
    {"ticker": "2914.T", "currency": "JPY"},
    {"ticker": "9434.T", "currency": "JPY"},
    {"ticker": "8591.T", "currency": "JPY"},
]

# 楽天証券でのNISA想定候補（運用上ここを増減して管理）
_RAKUTEN_NISA_ELIGIBLE_TICKERS = {
    "SPYD", "VYM", "HDV", "DVY",
    "8306.T", "2914.T", "9434.T", "8591.T",
}

_RECOMMENDATION_CACHE = {
    "key": None,
    "expires_at": 0.0,
    "value": [],
}


def _tax_rate_for_account(account_type: str | None) -> float:
    if not account_type:
        return _ACCOUNT_TAX_RATES["TOKUTEI"]
    return _ACCOUNT_TAX_RATES.get(account_type.upper(), _ACCOUNT_TAX_RATES["TOKUTEI"])


def _months_from_payments(payments: list[dict]) -> list[int]:
    months = sorted({int(p["date"][5:7]) for p in payments if p.get("date")})
    return months


def _short_name(name: str | None, max_len: int = 28) -> str:
    if not name:
        return "-"
    if len(name) <= max_len:
        return name
    return name[: max_len - 1] + "…"


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


def _convert_amount(amount: float, src_currency: str,
                    dst_currency: str, usdjpy: float | None) -> float | None:
    """金額を目標通貨へ換算する。未対応通貨ペアは None。"""
    return _convert_div(amount, src_currency, dst_currency, usdjpy)


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
        account_type = (getattr(h, "account_type", None) or "TOKUTEI").upper()
        tax_rate = _tax_rate_for_account(account_type)

        annual_div = None
        if info["annual_dividend"] is not None:
            annual_div = info["annual_dividend"] * (1 - tax_rate)

        per_payment = None
        if info["per_payment"] is not None:
            per_payment = info["per_payment"] * (1 - tax_rate)

        payments = [
            {"date": p["date"], "amount": p["amount"] * (1 - tax_rate)}
            for p in info["payments"]
        ]
        payments_last_year = [
            {"date": p["date"], "amount": p["amount"] * (1 - tax_rate)}
            for p in info.get("payments_last_year", [])
        ]

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

        annual_dividend_goal_per_share = None
        if annual_div is not None:
            annual_dividend_goal_per_share = _convert_amount(
                annual_div, h.currency, goal_currency, usdjpy
            )

        price_jpy = None
        if price is not None:
            price_jpy = _convert_amount(price, h.currency, "JPY", usdjpy)

        annual_dividend_total = (annual_div * h.quantity) if annual_div is not None else None
        annual_dividend_total_goal = None
        if annual_dividend_total is not None:
            annual_dividend_total_goal = _convert_amount(
                annual_dividend_total, h.currency, goal_currency, usdjpy
            )

        monthly_dividend_goal_by_month = {}
        for p in payments_last_year:
            month = int(p["date"][5:7])
            monthly_amount = p["amount"] * h.quantity
            monthly_amount_goal = _convert_amount(
                monthly_amount, h.currency, goal_currency, usdjpy
            )
            if monthly_amount_goal is None:
                continue
            monthly_dividend_goal_by_month[month] = (
                monthly_dividend_goal_by_month.get(month, 0.0) + monthly_amount_goal
            )

        # 買い増し株数（目標通貨に為替換算してから計算）
        shares_to_add = None
        buy_amount_to_add = None
        fx_converted = False
        if monthly_goal and annual_div and annual_div > 0:
            div_in_goal_currency = _convert_div(
                annual_div, h.currency, goal_currency, usdjpy
            )
            if div_in_goal_currency and div_in_goal_currency > 0:
                required_shares = (monthly_goal * 12) / div_in_goal_currency
                shares_to_add = max(0.0, required_shares - h.quantity)
                fx_converted = (h.currency != goal_currency)
                if price is not None and shares_to_add > 0:
                    raw_buy_amount = shares_to_add * price
                    buy_amount_to_add = _convert_amount(
                        raw_buy_amount, h.currency, "JPY", usdjpy
                    )

        results.append({
            "id": h.id,
            "ticker": h.ticker,
            "name": h.name or info.get("name") or h.ticker,
            "market": h.market,
            "quantity": h.quantity,
            "average_cost": h.average_cost,
            "currency": h.currency,
            "account_type": account_type,
            "memo": h.memo,
            # 価格・損益
            "price": price,
            "market_value": market_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            # 配当
            "annual_dividend": annual_div,
            "per_payment": per_payment,
            "payments": payments,
            "payments_last_year": payments_last_year,
            "frequency": info["frequency"],
            "div_yield": div_yield,
            "annual_dividend_goal_per_share": annual_dividend_goal_per_share,
            "price_jpy": price_jpy,
            # 目標計算
            "shares_to_add": shares_to_add,
            "buy_amount_to_add": buy_amount_to_add,
            "fx_converted": fx_converted,   # 為替換算が行われたか
            # 現在配当の合計（目標通貨換算）
            "annual_dividend_total": annual_dividend_total,
            "annual_dividend_total_goal": annual_dividend_total_goal,
            "monthly_dividend_goal_by_month": monthly_dividend_goal_by_month,
        })
    return results


def build_dividend_recommendation_feed(
    weak_months: list[int],
    goal_currency: str = "JPY",
    usdjpy: float | None = None,
    account_type: str = "TOKUTEI",
) -> list[str]:
    """
    配当が薄い月を埋めるための高配当候補を作成する。
    返却値は帯表示向けの短文リスト。
    """
    if not weak_months:
        weak_months = [1, 2, 4, 5, 7, 8, 10, 11]

    key = (tuple(sorted(weak_months)), goal_currency, round(usdjpy or 0.0, 3), account_type)
    now = time.time()
    if _RECOMMENDATION_CACHE["key"] == key and _RECOMMENDATION_CACHE["expires_at"] > now:
        return list(_RECOMMENDATION_CACHE["value"])

    tax_rate = _tax_rate_for_account(account_type)
    use_rakuten_nisa_filter = account_type.upper() == "NISA"

    scored = []
    for c in _RECOMMENDATION_CANDIDATES:
        if use_rakuten_nisa_filter and c["ticker"] not in _RAKUTEN_NISA_ELIGIBLE_TICKERS:
            continue
        info = _provider.get_full_info(c["ticker"])
        price = info.get("price")
        annual_div_raw = info.get("annual_dividend")
        if price is None or annual_div_raw is None or price <= 0:
            continue

        annual_div = annual_div_raw * (1 - tax_rate)
        yield_pct = (annual_div / price) * 100

        pay_months = _months_from_payments(info.get("payments_last_year", []))
        if not pay_months:
            continue

        hit_count = len(set(pay_months) & set(weak_months))

        annual_goal = _convert_amount(annual_div, c["currency"], goal_currency, usdjpy)
        if annual_goal is None:
            continue

        scored.append({
            "ticker": c["ticker"],
            "name": _short_name(info.get("name")),
            "yield_pct": yield_pct,
            "pay_months": pay_months,
            "hit_count": hit_count,
            "annual_goal": annual_goal,
        })

    preferred = [x for x in scored if x["hit_count"] > 0]
    selected = preferred if preferred else scored
    selected.sort(key=lambda x: (x["hit_count"], x["yield_pct"], x["annual_goal"]), reverse=True)
    top = selected[:8]

    feed = [
        (
            f"{item['ticker']} {_short_name(item['name'], 22)} | 利回り{item['yield_pct']:.1f}%"
            f" | 支払月:{','.join(str(m) for m in item['pay_months'])}月"
            f" | 年受取(1株):約{math.ceil(item['annual_goal'])}{goal_currency}"
        )
        for item in top
    ]

    if not preferred and feed:
        feed.insert(0, "該当月に強い候補が少ないため、楽天NISA候補を高配当順で表示しています")

    if not feed:
        feed = ["候補データを取得できませんでした。時間をおいて再表示してください"]

    _RECOMMENDATION_CACHE["key"] = key
    _RECOMMENDATION_CACHE["expires_at"] = now + 60 * 60 * 6
    _RECOMMENDATION_CACHE["value"] = list(feed)
    return feed
