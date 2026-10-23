"""Process-safe local cost ledger. Monetary values are integer nanodollars.

Reservations survive crashes and count against total and allocation caps.
Do not delete or reset the ledger to resume an interrupted experiment.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import hashlib
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
            fractions = {k: Decimal(v) for k, v in (DEFAULT_SHARES if shares is None else shares).items()}
            if not fractions or any(not isinstance(k,str) or not k.replace("_","").isalnum() for k in fractions) or any(not v.is_finite() or v < 0 for v in fractions.values()) or sum(fractions.values()) > 1 or not any(fractions.values()):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise BudgetError("Allocation shares must be non-negative, named, and sum to at most one.") from None
        self.limits = {k: int(self.cap * v * Decimal("0.90")) for k, v in fractions.items()}
        policy = json.dumps({"cap": self.cap, "limits": self.limits}, sort_keys=True)
        with self.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, share TEXT NOT NULL, experiment TEXT NOT NULL, reserved INTEGER NOT NULL, charged INTEGER, status TEXT NOT NULL, created TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS claims (cache_key TEXT PRIMARY KEY, status TEXT NOT NULL, created TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM settings WHERE name='policy'").fetchone()
            if row is not None:
                current = self._policy(conn)
                if current["cap"] != self.cap or (shares is not None and row[0] != policy):
                    raise BudgetError("Explicit budget cap or shares differ from the authoritative ledger.")
                self.limits = current["limits"]
            conn.execute("INSERT OR IGNORE INTO settings VALUES ('policy', ?)", (policy,))


    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()

    def _policy(self, conn):
        row=conn.execute("SELECT value FROM settings WHERE name='policy'").fetchone()
        try:
            policy=json.loads(row[0])
            cap=policy["cap"];limits=policy["limits"]
            if type(cap) is not int or cap<=0 or cap!=self.cap or not limits or any(not isinstance(k,str) or not k.replace("_","").isalnum() for k in limits):
                raise ValueError
            if any(type(v)is not int or v<0 for v in limits.values()) or sum(limits.values())>int(cap*Decimal("0.90")):
                raise ValueError
        except (TypeError,ValueError,KeyError):
            raise BudgetError("Authoritative ledger policy is invalid or its hard cap changed.") from None
        return policy

    def policy(self):
        with self.transaction() as conn:
            policy=self._policy(conn)
        return {"policy":policy,"sha256":self._hash(policy)}

    @classmethod
    def _table_audit(cls,conn,table,order):
        rows=[list(row) for row in conn.execute("SELECT * FROM "+table+" ORDER BY "+order)]
        return {"count":len(rows),"sha256":cls._hash(rows)}

    def migrate_unused_wp7_to_wp5(self, *, expected_policy_sha256, amendment_sha256, expected_table_audits=None):
        """One explicit transfer; cap and all other allocation limits remain fixed.

        Refuses unfinished reservations or claims, including unknown work that
        has not been charged. Migration is append-only evidence in the same
        transaction as the new policy. Existing Budget objects read this policy
        on every reserve, so a stale object cannot spend the disabled share.
        """
        if any(not isinstance(v,str) or len(v)!=64 or any(c not in "0123456789abcdef" for c in v)
               for v in (expected_policy_sha256,amendment_sha256)):
            raise BudgetError("Migration requires exact lowercase SHA256 identifiers.")
        with self.transaction() as conn:
            old=self._policy(conn)
            if set(old["limits"])!=set(DEFAULT_SHARES):
                raise BudgetError("This migration requires the named mission allocations.")
            if self._hash(old)!=expected_policy_sha256:
                raise BudgetError("Policy changed since migration review.")
            if conn.execute("SELECT 1 FROM settings WHERE name='halted'").fetchone():
                raise BudgetError("Halted ledgers cannot migrate policy.")
            if conn.execute("SELECT 1 FROM reservations WHERE charged IS NULL LIMIT 1").fetchone():
                raise BudgetError("In-flight reservations prohibit policy migration.")
            if conn.execute("SELECT 1 FROM claims WHERE status='pending' LIMIT 1").fetchone():
                raise BudgetError("Pending request claims prohibit policy migration.")
            spent=conn.execute("SELECT COALESCE(SUM(charged),0) FROM reservations WHERE share='WP7'").fetchone()[0]
            if spent or old["limits"]["WP7"]<=0:
                raise BudgetError("WP7 must be unused and enabled before this one-time transfer.")
            audit={name:self._table_audit(conn,name,key) for name,key in
                   (("reservations","id"),("claims","cache_key"),("events","id"))}
            if expected_table_audits is not None and audit!=expected_table_audits:
                raise BudgetError("Ledger changed since the retained migration backup.")
            new=json.loads(json.dumps(old))
            new["limits"]["WP5"]+=new["limits"]["WP7"]
            new["limits"]["WP7"]=0
            record={"timestamp":utc_now(),"status":"BUDGET_POLICY_MIGRATION","kind":"unused_wp7_to_wp5",
                    "amendment_sha256":amendment_sha256,"previous_policy":old,"new_policy":new,
                    "previous_policy_sha256":self._hash(old),"new_policy_sha256":self._hash(new),
                    "preserved_tables":audit,"global_cap_unchanged":True}
            # Database-level defense also covers a process still running the old
            # Budget implementation, whose Python self.limits may be stale.
            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS authoritative_budget_insert
            BEFORE INSERT ON reservations BEGIN
              SELECT CASE WHEN typeof(NEW.reserved) != 'integer' OR NEW.reserved < 0
                THEN RAISE(ABORT, 'Invalid budget reservation') END;
              SELECT CASE WHEN COALESCE(json_extract(
                  (SELECT value FROM settings WHERE name='policy'),
                  '$.limits.' || NEW.share), 0) <= 0
                THEN RAISE(ABORT, 'Authoritative allocation disabled') END;
              SELECT CASE WHEN
                (SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM reservations)
                   + NEW.reserved >
                json_extract((SELECT value FROM settings WHERE name='policy'),'$.cap')
                THEN RAISE(ABORT, 'Authoritative total cap exceeded') END;
              SELECT CASE WHEN
                (SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM reservations WHERE share=NEW.share)
                   + NEW.reserved >
                json_extract((SELECT value FROM settings WHERE name='policy'),'$.limits.' || NEW.share)
                THEN RAISE(ABORT, 'Authoritative share limit exceeded') END;
            END
            """)
            record["database_reservation_trigger"]="authoritative_budget_insert"
            conn.execute("UPDATE settings SET value=? WHERE name='policy'",(json.dumps(new,sort_keys=True),))
            conn.execute("INSERT INTO events(record) VALUES (?)",(json.dumps(record,sort_keys=True),))
            for name,key in (("reservations","id"),("claims","cache_key")):
                if self._table_audit(conn,name,key)!=audit[name]:
                    raise BudgetError("Migration unexpectedly changed retained accounting data.")
        return record

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
        if type(amount_nanos) is not int or amount_nanos < 0:
            raise BudgetError("Invalid budget allocation or reservation.")
        with self.transaction() as conn:
            policy = self._policy(conn)
            if share not in policy["limits"] or policy["limits"][share] <= 0:
                raise BudgetError("Budget allocation is unknown or disabled.")
            if conn.execute("SELECT 1 FROM settings WHERE name='halted'").fetchone():
                raise BudgetError("Budget ledger halted after an accounting anomaly; reconcile before resuming.")
            total = conn.execute("SELECT COALESCE(SUM(COALESCE(charged, reserved)), 0) FROM reservations").fetchone()[0]
            subtotal = conn.execute("SELECT COALESCE(SUM(COALESCE(charged, reserved)), 0) FROM reservations WHERE share=?", (share,)).fetchone()[0]
            if total + amount_nanos > policy["cap"]:
                raise BudgetError("Total API budget exhausted (including in-flight reservations).")
            if subtotal + amount_nanos > policy["limits"][share]:
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
            policy = self._policy(conn)
            rows = conn.execute("SELECT share, SUM(COALESCE(charged,reserved)), SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END) FROM reservations GROUP BY share").fetchall()
            halted = bool(conn.execute("SELECT 1 FROM settings WHERE name='halted'").fetchone())
        return {"cap_usd": nanos_to_usd(policy["cap"]), "accounted_usd": nanos_to_usd(sum(r[1] for r in rows)), "in_flight_usd": nanos_to_usd(sum(r[2] for r in rows)), "halted": halted,
                "allocations": {name: {"stop_usd": nanos_to_usd(limit), "accounted_usd": nanos_to_usd(next((r[1] for r in rows if r[0] == name), 0))} for name, limit in policy["limits"].items()}}

