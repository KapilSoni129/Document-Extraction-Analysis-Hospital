"""SQLite persistent storage for claims, decisions, and traces."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger("service.storage")

DB_PATH = Path(__file__).parent.parent.parent / "claims.db"

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        logger.info("Opening SQLite database: %s", DB_PATH)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            member_id TEXT NOT NULL,
            policy_id TEXT NOT NULL,
            claim_category TEXT NOT NULL,
            treatment_date TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            claimed_amount REAL NOT NULL,
            hospital_name TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL REFERENCES claims(claim_id),
            decision TEXT NOT NULL,
            approved_amount REAL NOT NULL DEFAULT 0,
            confidence_score REAL NOT NULL,
            message TEXT,
            rejection_reasons TEXT,
            amount_breakdown TEXT,
            policy_checks TEXT,
            fraud_signals TEXT,
            trace TEXT,
            component_failures TEXT,
            processing_time_ms INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_decisions_claim_id ON decisions(claim_id);
        CREATE INDEX IF NOT EXISTS idx_claims_member_id ON claims(member_id);
    """)
    conn.commit()


def save_claim(state: dict) -> str:
    conn = _get_conn()
    claim_id = state["claim_id"]
    logger.debug("Saving claim: %s", claim_id)
    now = datetime.now(UTC).isoformat()

    conn.execute(
        """INSERT OR REPLACE INTO claims
           (claim_id, member_id, policy_id, claim_category, treatment_date,
            submission_date, claimed_amount, hospital_name, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_id,
            state["member_id"],
            state.get("policy_id", "PLUM_GHI_2024"),
            state["claim_category"],
            state["treatment_date"],
            state.get("submission_date", state["treatment_date"]),
            state["claimed_amount"],
            state.get("hospital_name"),
            now,
        ),
    )
    conn.commit()
    return claim_id


def save_decision(claim_id: str, result: dict, processing_time_ms: int = 0):
    logger.debug("Saving decision: %s | decision=%s time=%dms", claim_id, result.get("decision"), processing_time_ms)
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()

    conn.execute(
        """INSERT INTO decisions
           (claim_id, decision, approved_amount, confidence_score, message,
            rejection_reasons, amount_breakdown, policy_checks, fraud_signals,
            trace, component_failures, processing_time_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_id,
            result.get("decision", "MANUAL_REVIEW"),
            result.get("approved_amount", 0),
            result.get("confidence_score", 0),
            result.get("message", ""),
            json.dumps(result.get("rejection_reasons", [])),
            json.dumps(result.get("amount_breakdown")),
            json.dumps(result.get("policy_checks", [])),
            json.dumps(result.get("fraud_signals", [])),
            json.dumps(result.get("trace", [])),
            json.dumps(result.get("component_failures", [])),
            processing_time_ms,
            now,
        ),
    )
    conn.commit()


def get_claim(claim_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    if not row:
        return None
    return dict(row)


def get_decision(claim_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM decisions WHERE claim_id = ? ORDER BY created_at DESC LIMIT 1",
        (claim_id,),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    for field in (
        "rejection_reasons",
        "amount_breakdown",
        "policy_checks",
        "fraud_signals",
        "trace",
        "component_failures",
    ):
        if result.get(field):
            result[field] = json.loads(result[field])
    return result


def list_claims(member_id: str | None = None, limit: int = 50) -> list[dict]:
    conn = _get_conn()
    if member_id:
        rows = conn.execute(
            "SELECT c.*, d.decision, d.approved_amount FROM claims c LEFT JOIN decisions d ON c.claim_id = d.claim_id WHERE c.member_id = ? ORDER BY c.created_at DESC LIMIT ?",
            (member_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT c.*, d.decision, d.approved_amount FROM claims c LEFT JOIN decisions d ON c.claim_id = d.claim_id ORDER BY c.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
