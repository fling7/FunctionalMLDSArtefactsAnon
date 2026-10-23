"""Process-safe local cost ledger. Monetary values are integer nanodollars.

Reservations survive crashes and count against total and allocation caps.
Do not delete or reset the ledger to resume an interrupted experiment.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import os
from pathlib import Path
import sqlite3
import uuid

NANODOLLARS = 1_000_000_000
DEFAULT_SHARES = {"WP4": "0.35", "WP5": "0.30", "WP7": "0.10", "judges": "0.10", "reserve": "0.15"}

class BudgetError(RuntimeError):
    """Safe diagnostic with no credentials."""

def usd_to_nanos(value) -> int:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError
        return int((number * NANODOLLARS).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, OverflowError):
        raise BudgetError("Invalid monetary amount; supply a finite non-negative decimal.") from None

def nanos_to_usd(value: int) -> str:
    return format(Decimal(value) / NANODOLLARS, ".9f")

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

class Budget:
    def __init__(self, path: Path, max_usd="100", shares=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap = usd_to_nanos(max_usd)
        if self.cap <= 0:
            raise BudgetError("The API budget must be positive.")
        try:
            fractions = {k: Decimal(v) for k, v in (shares or DEFAULT_SHARES).items()}
            if any(not v.is_finite() or v <= 0 for v in fractions.values()) or sum(fractions.values()) > 1:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise BudgetError("Allocation shares must be positive and sum to at most one.") from None
        self.limits = {k: int(self.cap * v * Decimal("0.90")) for k, v in fractions.items()}
        policy = json.dumps({"cap": self.cap, "limits": self.limits}, sort_keys=True)
        with self.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, share TEXT NOT NULL, experiment TEXT NOT NULL, reserved INTEGER NOT NULL, charged INTEGER, status TEXT NOT NULL, created TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS claims (cache_key TEXT PRIMARY KEY, status TEXT NOT NULL, created TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM settings WHERE name='policy'").fetchone()
            if row is not None and row[0] != policy:
                raise BudgetError("Budget policy differs from existing ledger; preserve it and reconcile policy explicitly.")
            conn.execute("INSERT OR IGNORE INTO settings VALUES ('policy', ?)", (policy,))

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=60000")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def reserve(self, share: str, experiment: str, amount_nanos: int) -> str:
        if share not in self.limits or type(amount_nanos) is not int or amount_nanos < 0:
            raise BudgetError("Invalid budget allocation or reservation.")
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM settings WHERE name='halted'").fetchone():
                raise BudgetError("Budget ledger halted after an accounting anomaly; reconcile before resuming.")
            total = conn.execute("SELECT COALESCE(SUM(COALESCE(charged, reserved)), 0) FROM reservations").fetchone()[0]
            subtotal = conn.execute("SELECT COALESCE(SUM(COALESCE(charged, reserved)), 0) FROM reservations WHERE share=?", (share,)).fetchone()[0]
            if total + amount_nanos > self.cap:
                raise BudgetError("Total API budget exhausted (including in-flight reservations).")
            if subtotal + amount_nanos > self.limits[share]:
                raise BudgetError("Allocation stopped at its 90-percent threshold (including reservations).")
            reservation = uuid.uuid4().hex
            conn.execute("INSERT INTO reservations VALUES (?, ?, ?, ?, NULL, 'reserved', ?)", (reservation, share, experiment, amount_nanos, utc_now()))
        return reservation

    def settle(self, reservation: str, actual_nanos: int | None, *, status="completed") -> int:
        """None means unknown outcome: charge the full reservation, never zero."""
        anomaly = False
        with self.transaction() as conn:
            row = conn.execute("SELECT reserved, charged FROM reservations WHERE id=?", (reservation,)).fetchone()
            if row is None or row[1] is not None:
                raise BudgetError("Unknown or already settled budget reservation.")
            charged = row[0] if actual_nanos is None else actual_nanos
            if type(charged) is not int or charged < 0:
                raise BudgetError("Invalid actual cost.")
            anomaly = charged > row[0]
            if anomaly:
                conn.execute("INSERT OR REPLACE INTO settings VALUES ('halted', 'actual_cost_exceeded_reservation')")
            conn.execute("UPDATE reservations SET charged=?, status=? WHERE id=?", (charged, status, reservation))
        if anomaly:
            raise BudgetError("Actual cost exceeded reservation; ledger halted, actual cost retained.")
        return charged

    def halt(self, reason="accounting_anomaly"):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('halted', ?)", (reason,))

    def claim(self, cache_key: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO claims VALUES (?, 'pending', ?)", (cache_key, utc_now()))
            return cursor.rowcount == 1

    def finish_claim(self, cache_key: str, status: str):
        with self.transaction() as conn:
            conn.execute("UPDATE claims SET status=? WHERE cache_key=?", (status, cache_key))

    def record(self, sanitized_record: dict, log_path: Path):
        """SQLite is authoritative; rebuild JSONL atomically under the same mutex."""
        record = json.dumps(sanitized_record, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self.transaction() as conn:
            conn.execute("INSERT INTO events(record) VALUES (?)", (record,))
        self.export_log(log_path)

    def export_log(self, log_path: Path):
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            rows = conn.execute("SELECT record FROM events ORDER BY id").fetchall()
            temporary = log_path.with_name(log_path.name + "." + uuid.uuid4().hex + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for (record,) in rows:
                    handle.write(record + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, log_path)

    def summary(self) -> dict:
        with self.transaction() as conn:
            rows = conn.execute("SELECT share, SUM(COALESCE(charged,reserved)), SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END) FROM reservations GROUP BY share").fetchall()
            halted = bool(conn.execute("SELECT 1 FROM settings WHERE name='halted'").fetchone())
        return {"cap_usd": nanos_to_usd(self.cap), "accounted_usd": nanos_to_usd(sum(r[1] for r in rows)), "in_flight_usd": nanos_to_usd(sum(r[2] for r in rows)), "halted": halted,
                "allocations": {name: {"stop_usd": nanos_to_usd(limit), "accounted_usd": nanos_to_usd(next((r[1] for r in rows if r[0] == name), 0))} for name, limit in self.limits.items()}}

