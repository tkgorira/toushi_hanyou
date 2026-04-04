from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Holding(db.Model):
    __tablename__ = "holdings"

    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    market = db.Column(db.String(20), nullable=True)          # "US", "JP" など
    quantity = db.Column(db.Float, nullable=False)
    average_cost = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="USD")
    memo = db.Column(db.Text, nullable=True)                  # 口座区分など将来用
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<Holding {self.ticker} qty={self.quantity}>"


class Setting(db.Model):
    """アプリ設定をキーバリューで保持する。"""
    __tablename__ = "settings"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)

    @staticmethod
    def get(key: str, default=None):
        row = Setting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key: str, value: str):
        row = Setting.query.get(key)
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))
        db.session.commit()
