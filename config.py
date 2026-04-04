import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'holdings.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 価格プロバイダー切り替え用 ("yfinance" | "finnhub" | "alphavantage")
    PRICE_PROVIDER = os.environ.get("PRICE_PROVIDER", "yfinance")
