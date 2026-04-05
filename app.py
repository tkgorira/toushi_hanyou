import math
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from datetime import datetime, timezone
from sqlalchemy import text
from werkzeug.security import check_password_hash

from config import Config
from models import db, Holding, Setting
from services import price_service

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)


def _is_authenticated() -> bool:
    return session.get("authenticated") is True


def _verify_login(username: str, password: str) -> bool:
    if username != app.config["AUTH_USERNAME"]:
        return False
    plain = app.config.get("AUTH_PASSWORD")
    if plain:
        return password == plain
    return check_password_hash(app.config["AUTH_PASSWORD_HASH"], password)


@app.before_request
def require_login():
    if request.endpoint in {"login", "static"}:
        return
    if request.endpoint is None:
        return
    if _is_authenticated():
        return
    return redirect(url_for("login", next=request.path))


def _ensure_schema_columns():
    """既存DBに不足カラムがあれば追加する。"""
    inspector = db.inspect(db.engine)
    columns = {col["name"] for col in inspector.get_columns("holdings")}
    if "account_type" not in columns:
        db.session.execute(
            text("ALTER TABLE holdings ADD COLUMN account_type VARCHAR(20) DEFAULT 'TOKUTEI'")
        )
        db.session.execute(
            text("UPDATE holdings SET account_type = 'TOKUTEI' WHERE account_type IS NULL")
        )
        db.session.commit()


with app.app_context():
    db.create_all()
    _ensure_schema_columns()


@app.context_processor
def inject_cache_bust():
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        mtime = int(os.path.getmtime(css_path))
    except OSError:
        mtime = 0
    return dict(cache_bust=mtime)


@app.after_request
def no_cache(response):
    """ブラウザキャッシュを無効化してF5なしで最新データを表示する。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ── ヘルパー ──────────────────────────────────────────────

def _normalize_ticker(ticker: str) -> str:
    """4桁の数字のみなら日本株と判断して '.T' を付与する。"""
    if ticker.isdigit() and len(ticker) == 4:
        return ticker + ".T"
    return ticker


def _fmt_float(value, decimals=2):
    """数値を小数点以下 decimals 桁で文字列化。None なら '---'。"""
    if value is None:
        return "---"
    return f"{value:,.{decimals}f}"


def _fmt_pct(value):
    """損益率・配当利回りを '±XX.XX%' 形式に整形。None なら '---'。"""
    if value is None:
        return "---"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _build_row(h: dict) -> dict:
    """テンプレートに渡す表示用データを構築する。"""
    pnl = h["pnl"]
    add = h["shares_to_add"]
    buy_amount = h["buy_amount_to_add"]
    buy_amount_ceil = math.ceil(buy_amount) if buy_amount is not None else None

    return {
        **h,
        # 価格・損益
        "price_display": _fmt_float(h["price"]),
        "average_cost_display": _fmt_float(h["average_cost"]),
        "market_value_display": _fmt_float(h["market_value"]),
        "pnl_display": ("+" if pnl and pnl >= 0 else "") + _fmt_float(pnl) if pnl is not None else "---",
        "pnl_pct_display": _fmt_pct(h["pnl_pct"]),
        "pnl_sign": "positive" if pnl and pnl >= 0 else ("negative" if pnl is not None else "neutral"),
        # 配当
        "annual_dividend_display": _fmt_float(h["annual_dividend"]),
        "per_payment_display": _fmt_float(h["per_payment"]),
        "div_yield_display": _fmt_pct(h["div_yield"]).lstrip("+") if h["div_yield"] is not None else "---",
        "account_type_display": "NISA" if h["account_type"] == "NISA" else "特定",
        # 目標（追加必要株数のみ・切り上げ整数）
        "shares_to_add_display": f"+{math.ceil(add)}株" if add and add > 0 else ("達成" if add == 0.0 else "---"),
        "buy_amount_to_add_display": (f"{_fmt_float(buy_amount_ceil, 0)} 円" if buy_amount_ceil is not None else "---"),
        "goal_achieved": add == 0.0 if add is not None else False,
    }


def _optimize_buy_combination(enriched: list[dict], annual_shortfall: float) -> dict:
    """
    年間配当の不足額を満たすために、買い増し金額(JPY)が最小になる株数の組み合わせを返す。
    1株単位の整数制約あり。
    """
    if annual_shortfall <= 0:
        return {"rows": [], "total_buy_jpy": 0, "total_annual_add": 0}

    candidates = []
    for h in enriched:
        annual_per_share = h.get("annual_dividend_goal_per_share")
        price_jpy = h.get("price_jpy")
        if annual_per_share is None or price_jpy is None:
            continue
        if annual_per_share <= 0 or price_jpy <= 0:
            continue

        # 配当は不足を過小評価しないよう切り捨て単位で扱う
        div_unit = max(1, int(math.floor(annual_per_share)))
        candidates.append({
            "ticker": h["ticker"],
            "name": h["name"],
            "div_per_share": annual_per_share,
            "div_unit": div_unit,
            "price_jpy": price_jpy,
        })

    if not candidates:
        return {"rows": [], "total_buy_jpy": None, "total_annual_add": 0}

    target_units = max(1, int(math.ceil(annual_shortfall)))
    max_div_unit = max(c["div_unit"] for c in candidates)
    max_units = target_units + max_div_unit * 3

    inf = float("inf")
    dp = [inf] * (max_units + 1)
    prev = [None] * (max_units + 1)
    dp[0] = 0.0

    for units in range(max_units + 1):
        if dp[units] == inf:
            continue
        for idx, c in enumerate(candidates):
            nxt = min(max_units, units + c["div_unit"])
            cost = dp[units] + c["price_jpy"]
            if cost < dp[nxt]:
                dp[nxt] = cost
                prev[nxt] = (units, idx)

    best_units = None
    best_cost = inf
    for units in range(target_units, max_units + 1):
        if dp[units] < best_cost:
            best_cost = dp[units]
            best_units = units

    if best_units is None or best_cost == inf:
        return {"rows": [], "total_buy_jpy": None, "total_annual_add": 0}

    counts = [0] * len(candidates)
    cursor = best_units
    while cursor and prev[cursor] is not None:
        before, idx = prev[cursor]
        counts[idx] += 1
        cursor = before

    rows = []
    total_annual_add = 0.0
    total_buy_jpy = 0.0
    for idx, cnt in enumerate(counts):
        if cnt == 0:
            continue
        c = candidates[idx]
        annual_add = c["div_per_share"] * cnt
        buy_jpy = c["price_jpy"] * cnt
        total_annual_add += annual_add
        total_buy_jpy += buy_jpy
        rows.append({
            "ticker": c["ticker"],
            "name": c["name"],
            "shares": cnt,
            "annual_add": math.ceil(annual_add),
            "buy_jpy": math.ceil(buy_jpy),
        })

    rows.sort(key=lambda x: x["buy_jpy"], reverse=True)
    return {
        "rows": rows,
        "total_buy_jpy": math.ceil(total_buy_jpy),
        "total_annual_add": math.ceil(total_annual_add),
    }


# ── ルーティング ──────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if _is_authenticated():
        return redirect(url_for("index"), 303)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if _verify_login(username, password):
            session["authenticated"] = True
            session["username"] = username
            flash("ログインしました。", "success")
            next_path = request.args.get("next")
            if next_path and next_path.startswith("/"):
                return redirect(next_path, 303)
            return redirect(url_for("index"), 303)
        flash("ユーザー名またはパスワードが違います。", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("ログアウトしました。", "success")
    return redirect(url_for("login"), 303)


@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    return send_from_directory(app.static_folder, "apple-touch-icon.png", mimetype="image/png")

@app.route("/")
def index():
    db.session.expire_all()
    holdings = Holding.query.order_by(Holding.created_at).all()

    # 月次目標額を設定から読み込む
    monthly_goal_str = Setting.get("monthly_goal")
    monthly_goal = float(monthly_goal_str) if monthly_goal_str else None
    monthly_goal_currency = Setting.get("monthly_goal_currency", "JPY")

    usdjpy = price_service.get_usdjpy()
    enriched = price_service.enrich_holdings(
        holdings,
        monthly_goal=monthly_goal,
        goal_currency=monthly_goal_currency,
        usdjpy=usdjpy,
    )
    rows = [_build_row(h) for h in enriched]

    # 現在の配当合計（目標通貨ベース）
    annual_dividend_current_raw = sum(
        h["annual_dividend_total_goal"]
        for h in enriched
        if h["annual_dividend_total_goal"] is not None
    )
    annual_dividend_current = math.ceil(annual_dividend_current_raw) if annual_dividend_current_raw else 0
    monthly_dividend_current = math.ceil(annual_dividend_current_raw / 12) if annual_dividend_current_raw else 0

    monthly_dividend_totals = {m: 0.0 for m in range(1, 13)}
    for h in enriched:
        for month, amount in h.get("monthly_dividend_goal_by_month", {}).items():
            monthly_dividend_totals[month] += amount

    monthly_dividend_breakdown = [
        {"month": month, "amount": math.ceil(amount)}
        for month, amount in monthly_dividend_totals.items()
        if amount > 0
    ]

    if annual_dividend_current_raw > 0:
        baseline = annual_dividend_current_raw / 12
        weak_months = [m for m in range(1, 13) if monthly_dividend_totals[m] < baseline * 0.7]
    else:
        weak_months = [1, 2, 4, 5, 7, 8, 10, 11]

    if len(weak_months) == 0:
        weak_months = sorted(monthly_dividend_totals, key=lambda m: monthly_dividend_totals[m])[:4]

    recommendation_feed = price_service.build_dividend_recommendation_feed(
        weak_months=weak_months,
        goal_currency=monthly_goal_currency,
        usdjpy=usdjpy,
        account_type="NISA",
    )

    annual_shortfall = None
    recommendation = None
    if monthly_goal:
        annual_goal = monthly_goal * 12
        annual_shortfall = max(0.0, annual_goal - annual_dividend_current_raw)
        recommendation = _optimize_buy_combination(enriched, annual_shortfall)

    return render_template(
        "index.html",
        rows=rows,
        monthly_goal=monthly_goal,
        monthly_goal_currency=monthly_goal_currency,
        annual_dividend_current=annual_dividend_current,
        monthly_dividend_current=monthly_dividend_current,
        monthly_dividend_breakdown=monthly_dividend_breakdown,
        weak_months=weak_months,
        recommendation_feed=recommendation_feed,
        annual_shortfall=math.ceil(annual_shortfall) if annual_shortfall is not None else None,
        recommendation=recommendation,
        usdjpy=usdjpy,
    )


@app.route("/settings/goal", methods=["POST"])
def settings_goal():
    """月次目標額を保存する。"""
    goal = request.form.get("monthly_goal", "").strip()
    currency = request.form.get("monthly_goal_currency", "JPY")
    if goal:
        try:
            Setting.set("monthly_goal", str(float(goal)))
            Setting.set("monthly_goal_currency", currency)
            flash("月次目標額を保存しました。", "success")
        except ValueError:
            flash("金額は数値で入力してください。", "error")
    else:
        # 空欄で送信 → 目標をクリア
        Setting.set("monthly_goal", "")
        flash("月次目標額をクリアしました。", "success")
    return redirect(url_for("index"), 303)


@app.route("/holding/add", methods=["GET", "POST"])
def holding_add():
    if request.method == "POST":
        ticker = _normalize_ticker(request.form.get("ticker", "").strip().upper())
        if not ticker:
            flash("ティッカーを入力してください。", "error")
            return render_template("holding_form.html", holding=None, action="add")

        name = request.form.get("name", "").strip() or None
        if not name:
            name = price_service.get_name(ticker)

        try:
            holding = Holding(
                ticker=ticker,
                name=name,
                market=request.form.get("market", "").strip() or None,
                quantity=float(request.form.get("quantity") or 0),
                average_cost=float(request.form.get("average_cost") or 0),
                currency=request.form.get("currency", "USD"),
                account_type=request.form.get("account_type", "TOKUTEI"),
                memo=request.form.get("memo", "").strip() or None,
            )
            db.session.add(holding)
            db.session.commit()
            flash(f"{ticker} を追加しました。", "success")
            return redirect(url_for("index"), 303)
        except Exception as e:
            db.session.rollback()
            flash(f"追加に失敗しました: {e}", "error")

    return render_template("holding_form.html", holding=None, action="add")


@app.route("/holding/<int:holding_id>/edit", methods=["GET", "POST"])
def holding_edit(holding_id):
    holding = db.get_or_404(Holding, holding_id)

    if request.method == "POST":
        try:
            holding.ticker = _normalize_ticker(request.form.get("ticker", "").strip().upper())
            holding.name = request.form.get("name", "").strip() or None
            holding.market = request.form.get("market", "").strip() or None
            holding.quantity = float(request.form.get("quantity") or 0)
            holding.average_cost = float(request.form.get("average_cost") or 0)
            holding.currency = request.form.get("currency", "USD")
            holding.account_type = request.form.get("account_type", "TOKUTEI")
            holding.memo = request.form.get("memo", "").strip() or None
            holding.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            flash(f"{holding.ticker} を更新しました。", "success")
            return redirect(url_for("index"), 303)
        except Exception as e:
            db.session.rollback()
            flash(f"更新に失敗しました: {e}", "error")

    return render_template("holding_form.html", holding=holding, action="edit")


@app.route("/holding/<int:holding_id>/delete", methods=["POST"])
def holding_delete(holding_id):
    holding = db.get_or_404(Holding, holding_id)
    ticker = holding.ticker
    db.session.delete(holding)
    db.session.commit()
    flash(f"{ticker} を削除しました。", "success")
    return redirect(url_for("index"), 303)


if __name__ == "__main__":
    app.run(debug=True)
