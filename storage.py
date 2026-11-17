"""Histórico de preços em SQLite."""
from __future__ import annotations

import sqlite3
import statistics
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    pid TEXT PRIMARY KEY, name TEXT, url TEXT, first_seen REAL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS prices (
    pid TEXT, ts REAL, price REAL, old_price REAL
);
CREATE INDEX IF NOT EXISTS ix_prices_pid ON prices(pid, ts);
CREATE TABLE IF NOT EXISTS alerts (
    pid TEXT, price REAL, ts REAL
);
CREATE TABLE IF NOT EXISTS watch_urls (url TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS scans (
    ts REAL, n_products INTEGER, n_alerts INTEGER, n_errors INTEGER
);
"""


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    # ── histórico ──
    def history(self, pid: str, limit: int = 30) -> list[float]:
        rows = self.db.execute(
            "SELECT price FROM prices WHERE pid=? ORDER BY ts DESC LIMIT ?",
            (pid, limit)).fetchall()
        return [r[0] for r in rows]

    def median(self, pid: str, limit: int = 30) -> tuple[float | None, int]:
        h = self.history(pid, limit)
        return (statistics.median(h) if h else None), len(h)

    def record(self, p) -> None:
        now = time.time()
        self.db.execute(
            "INSERT INTO products VALUES (?,?,?,?,?) ON CONFLICT(pid) DO UPDATE "
            "SET name=excluded.name, url=excluded.url, last_seen=excluded.last_seen",
            (p.pid, p.name, p.url, now, now))
        last = self.history(p.pid, 1)
        # só grava se o preço mudou ou passaram 6 h (mantém a BD pequena)
        last_ts = self.db.execute(
            "SELECT MAX(ts) FROM prices WHERE pid=?", (p.pid,)).fetchone()[0]
        if not last or last[0] != p.price or (now - (last_ts or 0)) > 6 * 3600:
            self.db.execute("INSERT INTO prices VALUES (?,?,?,?)",
                            (p.pid, now, p.price, p.old_price))

    # ── alertas ──
    def recently_alerted(self, pid: str, price: float, hours: float) -> bool:
        since = time.time() - hours * 3600
        return self.db.execute(
            "SELECT 1 FROM alerts WHERE pid=? AND price=? AND ts>?",
            (pid, price, since)).fetchone() is not None

    def mark_alerted(self, pid: str, price: float) -> None:
        self.db.execute("INSERT INTO alerts VALUES (?,?,?)", (pid, price, time.time()))

    # ── URLs vigiadas ──
    def seed_urls(self, urls: list[str]) -> None:
        if not self.db.execute("SELECT 1 FROM watch_urls").fetchone():
            self.db.executemany("INSERT OR IGNORE INTO watch_urls VALUES (?)",
                                [(u,) for u in urls])
            self.commit()

    def urls(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT url FROM watch_urls")]

    def add_url(self, u: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO watch_urls VALUES (?)", (u,))
        self.commit()

    def remove_url(self, u: str) -> bool:
        cur = self.db.execute("DELETE FROM watch_urls WHERE url=?", (u,))
        self.commit()
        return cur.rowcount > 0

    # ── estatísticas ──
    def log_scan(self, n_products: int, n_alerts: int, n_errors: int) -> None:
        self.db.execute("INSERT INTO scans VALUES (?,?,?,?)",
                        (time.time(), n_products, n_alerts, n_errors))

    def stats(self) -> dict:
        q = self.db.execute
        last = q("SELECT ts, n_products, n_alerts, n_errors FROM scans "
                 "ORDER BY ts DESC LIMIT 1").fetchone()
        return {
            "products": q("SELECT COUNT(*) FROM products").fetchone()[0],
            "readings": q("SELECT COUNT(*) FROM prices").fetchone()[0],
            "alerts_24h": q("SELECT COUNT(*) FROM alerts WHERE ts>?",
                            (time.time() - 86400,)).fetchone()[0],
            "last_scan": last,
        }

    def commit(self) -> None:
        self.db.commit()
