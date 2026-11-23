# -*- coding: utf-8 -*-
"""Read-only MySQL helper for assertion-side SQL (lsp_scp verification queries).

Credentials come from config/base.yaml ``database`` block; the password is
injected through the environment variable named by ``password_env``.
If host/user/name/password are incomplete, ``from_config`` returns None and
callers (fixtures) skip the DB-dependent cases instead of failing.
"""

from __future__ import annotations

import os
from typing import Any

import pymysql
import pymysql.cursors


class Database:
    """Thin read-only wrapper: query helpers returning dict rows."""

    def __init__(self, conn: pymysql.connections.Connection):
        self._conn = conn

    @classmethod
    def from_config(cls, cfg: dict) -> "Database | None":
        db = cfg.get("database") or {}
        required = ("host", "port", "user", "name")
        if not all(db.get(key) for key in required):
            return None
        password = os.getenv(str(db.get("password_env", "")), "")
        if not password:
            return None
        conn = pymysql.connect(
            host=str(db["host"]),
            port=int(db["port"]),
            user=str(db["user"]),
            password=password,
            database=str(db["name"]),
            charset=str(db.get("charset", "utf8mb4")),
            connect_timeout=int(db.get("connect_timeout", 5)),
            read_timeout=int(db.get("read_timeout", 10)),
            cursorclass=pymysql.cursors.DictCursor,
            # 只读断言连接必须开自动提交，否则 REPEATABLE READ 下模块级连接
            # 会沿用首次查询的快照，读不到后续用例新落库的任务行
            autocommit=True,
        )
        return cls(conn)

    def query_all(self, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params or {})
            return list(cursor.fetchall())

    def query_one(self, sql: str, params: dict | None = None) -> dict[str, Any] | None:
        rows = self.query_all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: dict | None = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()))

    def close(self) -> None:
        self._conn.close()
