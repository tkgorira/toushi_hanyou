from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timezone

from config import Config
from models import db, Holding
from services import price_service

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

with app.app_context():
    db.create_all()


# ── ヘルパー ──────────────────────────────────────────────

def _fmt_float(value, decimals=2):
    """数値を小数点以下 decimals 桁で文字列化。None なら '---' を返す。"""
    if value is None:
        return "---"
    return f"{value:,.{decimals}f}"


def _fmt_pct(value):
    """損益率を '±XX.XX%' 形式に整形。None なら '---'。"""
    if value is None:
        return "---"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _build_row(h: dict) -> dict:
    """テンプレートに渡す表示用データを構築する。"""
    pnl = h["pnl"]
    return {
        **h,
        "price_display": _fmt_float(h["price"]),
        "average_cost_display": _fmt_float(h["average_cost"]),
        "market_value_display": _fmt_float(h["market_value"]),
        "pnl_display": ("+" if pnl and pnl >= 0 else "") + _fmt_float(pnl) if pnl is not None else "---",
        "pnl_pct_display": _fmt_pct(h["pnl_pct"]),
        "pnl_sign": "positive" if pnl and pnl >= 0 else ("negative" if pnl is not None else "neutral"),
    }


# ── ルーティング ──────────────────────────────────────────

@app.route("/")
def index():
    holdings = Holding.query.order_by(Holding.created_at).all()
    rows = [_build_row(h) for h in price_service.enrich_holdings(holdings)]
    return render_template("index.html", rows=rows)


@app.route("/holding/add", methods=["GET", "POST"])
def holding_add():
    if request.method == "POST":
        ticker = request.form.get("ticker", "").strip().upper()
        if not ticker:
            flash("ティッカーを入力してください。", "error")
            return render_template("holding_form.html", holding=None, action="add")

        name = request.form.get("name", "").strip() or None
        # 銘柄名が未入力なら yfinance から取得を試みる
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
        return redirect(url_for("index"))

    return render_template("holding_form.html", holding=None, action="add")


@app.route("/holding/<int:holding_id>/edit", methods=["GET", "POST"])
def holding_edit(holding_id):
    holding = db.get_or_404(Holding, holding_id)

    if request.method == "POST":
        holding.ticker = request.form.get("ticker", "").strip().upper()
        holding.name = request.form.get("name", "").strip() or None
        holding.market = request.form.get("market", "").strip() or None
        holding.quantity = float(request.form.get("quantity", 0))
        holding.average_cost = float(request.form.get("average_cost", 0))
        holding.currency = request.form.get("currency", "USD")
        holding.memo = request.form.get("memo", "").strip() or None
        holding.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f"{holding.ticker} を更新しました。", "success")
        return redirect(url_for("index"))

    return render_template("holding_form.html", holding=holding, action="edit")


@app.route("/holding/<int:holding_id>/delete", methods=["POST"])
def holding_delete(holding_id):
    holding = db.get_or_404(Holding, holding_id)
    ticker = holding.ticker
    db.session.delete(holding)
    db.session.commit()
    flash(f"{ticker} を削除しました。", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
