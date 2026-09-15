# -*- coding: utf-8 -*-
"""SQLAlchemy 持久层；本地默认 SQLite，Compose 中使用 PostgreSQL。"""
from __future__ import annotations

from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.sql import func

from . import config


class Base(DeclarativeBase):
    pass


class ResearchRow(Base):
    __tablename__ = "research_records"

    research_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    topic: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    document: Mapped[dict] = mapped_column(JSON)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    config.ensure_data_dir()
    Base.metadata.create_all(engine)
