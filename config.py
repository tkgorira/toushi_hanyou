import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _normalize_postgres_driver(database_url: str) -> str:
    """Render の接続URLを SQLAlchemy の psycopg 方言へ寄せる。"""
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _resolve_database_url() -> str:
    """環境変数 DATABASE_URL を優先し、未設定時はローカルSQLiteを使う。"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'holdings.db')}"

    # 一部PaaSは postgres:// を渡すため SQLAlchemy 互換形式へ補正する。
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return _normalize_postgres_driver(database_url)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = _resolve_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }
    # 価格プロバイダー切り替え用 ("yfinance" | "finnhub" | "alphavantage")
    PRICE_PROVIDER = os.environ.get("PRICE_PROVIDER", "yfinance")
