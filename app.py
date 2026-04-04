import math
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timezone

from config import Config
from models import db, Holding, Setting
from services import price_service

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

with app.app_context():
    db.create_all()


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
        # 目標（追加必要株数のみ・切り上げ整数）
        "shares_to_add_display": f"+{math.ceil(add)}株" if add and add > 0 else ("達成" if add == 0.0 else "---"),
        "goal_achieved": add == 0.0 if add is not None else False,
    }


# ── ルーティング ──────────────────────────────────────────

@app.route("/")
def index():
    holdings = Holding.query.order_by(Holding.created_at).all()

    # 月次目標額を設定から読み込む
    monthly_goal_str = Setting.get("monthly_goal")
    monthly_goal = float(monthly_goal_str) if monthly_goal_str else None
    monthly_goal_currency = Setting.get("monthly_goal_currency", "JPY")

    usdjpy = price_service.get_usdjpy()
    rows = [_build_row(h) for h in price_service.enrich_holdings(
        holdings,
        monthly_goal=monthly_goal,
        goal_currency=monthly_goal_currency,
        usdjpy=usdjpy,
    )]
    return render_template(
        "index.html",
        rows=rows,
        monthly_goal=monthly_goal,
        monthly_goal_currency=monthly_goal_currency,
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

        holding = Holding(
            ticker=ticker,
            name=name,
            market=request.form.get("market", "").strip() or None,
            quantity=float(request.form.get("quantity", 0)),
            average_cost=float(request.form.get("average_cost", 0)),
            currency=request.form.get("currency", "USD"),
            memo=request.form.get("memo", "").strip() or None,
        )
        db.session.add(holding)
        db.session.commit()
        flash(f"{ticker} を追加しました。", "success")
        return redirect(url_for("index"), 303)

    return render_template("holding_form.html", holding=None, action="add")


@app.route("/holding/<int:holding_id>/edit", methods=["GET", "POST"])
def holding_edit(holding_id):
    holding = db.get_or_404(Holding, holding_id)

    if request.method == "POST":
        holding.ticker = _normalize_ticker(request.form.get("ticker", "").strip().upper())
        holding.name = request.form.get("name", "").strip() or None
        holding.market = request.form.get("market", "").strip() or None
        holding.quantity = float(request.form.get("quantity", 0))
        holding.average_cost = float(request.form.get("average_cost", 0))
        holding.currency = request.form.get("currency", "USD")
        holding.memo = request.form.get("memo", "").strip() or None
        holding.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f"{holding.ticker} を更新しました。", "success")
        return redirect(url_for("index"), 303)

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
