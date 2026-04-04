# toushi_hanyou — 汎用投資管理Webアプリ (MVP)

Flask + SQLite + yfinance で動く、シンプルな株式保有管理アプリです。

## 機能

- 保有銘柄の追加 / 編集 / 削除
- yfinance による現在価格の自動取得（一覧表示時）
- 評価額・損益額・損益率の自動計算
- 価格取得失敗時のエラー表示（画面崩壊なし）
- USD / JPY など複数通貨対応（為替換算は将来実装）
- メモ欄（口座区分・NISA区分などの将来拡張用）

## 必要な環境

- Python 3.11 以上

## セットアップ（ローカル）

```bash
# 1. リポジトリをクローン
git clone https://github.com/tkgorira/toushi_hanyou.git
cd toushi_hanyou

# 2. 仮想環境を作成・有効化
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. 依存パッケージをインストール
pip install -r requirements.txt

# 4. アプリを起動
python app.py
```

ブラウザで http://localhost:5000 にアクセスしてください。

## 動作確認（flask shell）

```bash
flask shell
>>> from models import Holding, db
>>> db.session.add(Holding(ticker="AAPL", quantity=10, average_cost=150.0, currency="USD"))
>>> db.session.commit()
>>> Holding.query.all()
```

## プロジェクト構成

```
toushi_hanyou/
├── app.py                    # Flaskアプリ本体・ルーティング
├── config.py                 # 環境設定
├── models.py                 # SQLAlchemy モデル
├── requirements.txt
├── README.md
├── .gitignore
├── instance/                 # SQLite DB（gitignore）
├── services/
│   └── price_service.py      # 価格取得サービス層
├── providers/
│   └── yfinance_provider.py  # yfinance 実装
├── templates/
│   ├── base.html
│   ├── index.html
│   └── holding_form.html
└── static/
    └── style.css
```

## 価格プロバイダーの差し替え方法

`services/price_service.py` の先頭部分でプロバイダーを切り替えます。

```python
# 例: Finnhub に差し替える場合
from providers.finnhub_provider import FinnhubProvider
_provider = FinnhubProvider()
```

新しいプロバイダーは `get_price(ticker)` と `get_name(ticker)` を実装するだけです。

## Render へのデプロイ手順

1. `requirements.txt` に `gunicorn` が含まれていることを確認
2. Render で新規 Web Service を作成
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app`
5. 環境変数 `SECRET_KEY` を設定（必須）
6. SQLite は Render のエフェメラルストレージに保存される点に注意
   （本番運用では PostgreSQL への移行を推奨）

## 今後の拡張案

- [ ] 為替レート取得・JPY換算表示
- [ ] NISA/特定口座などの口座区分フィールド追加
- [ ] 価格の定期自動更新（APScheduler）
- [ ] ポートフォリオ比率グラフ（Chart.js）
- [ ] 配当金・分配金の記録
- [ ] 取引履歴の管理（買付・売却）
- [ ] PostgreSQL 対応（Render 本番用）
- [ ] ユーザー認証（Flask-Login）
- [ ] CSV インポート / エクスポート
- [ ] 価格プロバイダーの設定画面（Finnhub / Alpha Vantage）
