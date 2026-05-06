#!/usr/bin/env python3
"""SQLite-backed per-issuer pattern store and client/counterparty matcher.

Stores extraction recipes per invoice "class" (issuer/template fingerprint),
plus per-client identifier records (legal name, EIK, VAT-id) used to verify
that a routed invoice's buyer block matches the expected client. Counterparty
history allows suggesting an expense account / VAT term automatically when a
known supplier reappears.

All operations degrade gracefully: a missing or unreadable DB file simply
returns empty results; callers must treat this module as best-effort.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Confidence threshold above which `learn_from` will materialise a new
# class / counterparty. Locked in plan to 0.95.
LEARN_THRESHOLD = 0.95


SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT UNIQUE NOT NULL,
    legal_name TEXT NOT NULL,
    eik TEXT,
    vat_id TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS issuer_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    fingerprint_json TEXT NOT NULL,
    language TEXT,
    country TEXT,
    samples_seen INTEGER NOT NULL DEFAULT 0,
    pending_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS class_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    kind TEXT NOT NULL,
    pattern TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    FOREIGN KEY (class_id) REFERENCES issuer_classes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_class_patterns_class_field
    ON class_patterns(class_id, field);

CREATE TABLE IF NOT EXISTS counterparties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    supplier_name TEXT NOT NULL,
    supplier_eik TEXT,
    supplier_vat TEXT,
    suggested_account TEXT,
    suggested_vat_term TEXT,
    seen_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
    UNIQUE (client_id, supplier_vat),
    UNIQUE (client_id, supplier_name)
);

CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER,
    file_name TEXT NOT NULL,
    class_id INTEGER,
    fields_json TEXT NOT NULL,
    status TEXT NOT NULL,
    run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

@contextmanager
def _connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Create tables if missing. Idempotent."""
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_clients(db_path: Path, clients_json: Path) -> int:
    """Upsert clients from a JSON file. Returns number of rows touched."""
    if not clients_json.exists():
        return 0
    with clients_json.open("r", encoding="utf-8") as fh:
        rows = json.load(fh)
    touched = 0
    with _connect(db_path) as conn:
        for r in rows:
            conn.execute(
                """INSERT INTO clients (folder, legal_name, eik, vat_id, aliases_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(folder) DO UPDATE SET
                       legal_name=excluded.legal_name,
                       eik=excluded.eik,
                       vat_id=excluded.vat_id,
                       aliases_json=excluded.aliases_json""",
                (
                    r["folder"],
                    r.get("legal_name", r["folder"]),
                    r.get("eik"),
                    r.get("vat_id"),
                    json.dumps(r.get("aliases", []), ensure_ascii=False),
                ),
            )
            touched += 1
    return touched


def seed_issuer_classes(db_path: Path, classes_json: Path) -> int:
    """Upsert issuer classes + their seed patterns from a JSON file."""
    if not classes_json.exists():
        return 0
    with classes_json.open("r", encoding="utf-8") as fh:
        rows = json.load(fh)
    touched = 0
    with _connect(db_path) as conn:
        for r in rows:
            cur = conn.execute(
                """INSERT INTO issuer_classes
                   (slug, display_name, fingerprint_json, language, country, pending_review)
                   VALUES (?, ?, ?, ?, ?, 0)
                   ON CONFLICT(slug) DO UPDATE SET
                       display_name=excluded.display_name,
                       fingerprint_json=excluded.fingerprint_json,
                       language=excluded.language,
                       country=excluded.country
                   RETURNING id""",
                (
                    r["slug"],
                    r.get("display_name", r["slug"]),
                    json.dumps(r.get("fingerprint", {}), ensure_ascii=False),
                    r.get("language"),
                    r.get("country"),
                ),
            )
            class_id = cur.fetchone()[0]
            # Replace seed patterns wholesale on re-seed.
            conn.execute("DELETE FROM class_patterns WHERE class_id = ?", (class_id,))
            for p in r.get("patterns", []):
                conn.execute(
                    """INSERT INTO class_patterns
                       (class_id, field, kind, pattern, priority)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        class_id,
                        p["field"],
                        p.get("kind", "regex"),
                        p["pattern"],
                        int(p.get("priority", 100)),
                    ),
                )
            touched += 1
    return touched


# ---------------------------------------------------------------------------
# Class fingerprint matching
# ---------------------------------------------------------------------------

def _fingerprint_score(text_lc: str, fingerprint: dict) -> int:
    """Score a class fingerprint against lowercased text.

    Fingerprint schema:
      {
        "must_contain_any": ["microinvest invoice pro", "..."],
        "must_contain_all": ["...", "..."],
        "boost_tokens": [["token", weight], ...]
      }
    """
    must_any = fingerprint.get("must_contain_any") or []
    must_all = fingerprint.get("must_contain_all") or []
    boosts = fingerprint.get("boost_tokens") or []

    if must_all and not all(tok.lower() in text_lc for tok in must_all):
        return 0
    if must_any and not any(tok.lower() in text_lc for tok in must_any):
        return 0

    score = 50 if (must_any or must_all) else 0
    for entry in boosts:
        if isinstance(entry, list) and len(entry) == 2:
            tok, weight = entry
        else:
            tok, weight = entry, 10
        if tok.lower() in text_lc:
            score += int(weight)
    return score


def match_class(db_path: Path, text: str) -> tuple[int | None, int]:
    """Return (class_id, score). class_id may be None."""
    if not text or not db_path.exists():
        return None, 0
    text_lc = text.lower()
    best_id = None
    best_score = 0
    with _connect(db_path) as conn:
        for row in conn.execute("SELECT id, fingerprint_json FROM issuer_classes"):
            try:
                fp = json.loads(row["fingerprint_json"])
            except json.JSONDecodeError:
                continue
            s = _fingerprint_score(text_lc, fp)
            if s > best_score:
                best_score = s
                best_id = row["id"]
        if best_id is not None:
            conn.execute(
                "UPDATE issuer_classes SET samples_seen = samples_seen + 1 WHERE id = ?",
                (best_id,),
            )
    return best_id, best_score


def apply_class_patterns(db_path: Path, class_id: int, text: str) -> dict[str, str]:
    """Apply stored regex patterns for the given class. First match per field wins."""
    if class_id is None or not text or not db_path.exists():
        return {}
    out: dict[str, str] = {}
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, field, kind, pattern, priority FROM class_patterns
               WHERE class_id = ? ORDER BY field, priority DESC, id""",
            (class_id,),
        ).fetchall()
        for row in rows:
            field = row["field"]
            if field in out:
                continue
            kind = row["kind"]
            pattern = row["pattern"]
            value = ""
            try:
                if kind == "regex":
                    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.UNICODE)
                    if m:
                        value = (m.group(1) if m.lastindex else m.group(0)).strip()
                elif kind == "fixed_value":
                    value = pattern
                # Other kinds (label_anchor, line_offset) reserved for future.
            except re.error:
                conn.execute(
                    "UPDATE class_patterns SET fail_count = fail_count + 1 WHERE id = ?",
                    (row["id"],),
                )
                continue
            if value:
                out[field] = value
                conn.execute(
                    """UPDATE class_patterns
                       SET success_count = success_count + 1, last_used_at = ?
                       WHERE id = ?""",
                    (datetime.utcnow().isoformat(timespec="seconds"), row["id"]),
                )
    return out


# ---------------------------------------------------------------------------
# Client / buyer verification
# ---------------------------------------------------------------------------

def get_client(db_path: Path, folder: str) -> dict | None:
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE folder = ?", (folder,)
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "folder": row["folder"],
            "legal_name": row["legal_name"],
            "eik": row["eik"],
            "vat_id": row["vat_id"],
            "aliases": json.loads(row["aliases_json"] or "[]"),
        }


def _all_clients(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM clients").fetchall()
    return [
        {
            "id": r["id"], "folder": r["folder"], "legal_name": r["legal_name"],
            "eik": r["eik"], "vat_id": r["vat_id"],
            "aliases": json.loads(r["aliases_json"] or "[]"),
        }
        for r in rows
    ]


def verify_buyer(db_path: Path, client_folder: str, text: str) -> dict:
    """Inspect text for any client identifier; report match/mismatch.

    Returns {"match": bool, "mismatch_with": [folders...], "found": [...]}.
    """
    result = {"match": False, "mismatch_with": [], "found": []}
    if not text or not db_path.exists():
        return result
    text_lc = text.lower()
    with _connect(db_path) as conn:
        clients = _all_clients(conn)

    for c in clients:
        cues = [c["legal_name"]] + (c["aliases"] or [])
        cues = [x for x in cues if x]
        if c["eik"]:
            cues.append(c["eik"])
        if c["vat_id"]:
            cues.append(c["vat_id"])
        hits = [cue for cue in cues if cue and cue.lower() in text_lc]
        if not hits:
            continue
        if c["folder"] == client_folder:
            result["match"] = True
            result["found"].extend(hits)
        else:
            result["mismatch_with"].append(c["folder"])
    return result


# ---------------------------------------------------------------------------
# Counterparty memory
# ---------------------------------------------------------------------------

def match_counterparty(
    db_path: Path,
    client_id: int | None,
    supplier_name: str = "",
    supplier_vat: str = "",
) -> dict | None:
    if client_id is None or not db_path.exists():
        return None
    if not supplier_name and not supplier_vat:
        return None
    with _connect(db_path) as conn:
        row = None
        if supplier_vat:
            row = conn.execute(
                "SELECT * FROM counterparties WHERE client_id = ? AND supplier_vat = ?",
                (client_id, supplier_vat),
            ).fetchone()
        if row is None and supplier_name:
            row = conn.execute(
                "SELECT * FROM counterparties WHERE client_id = ? AND lower(supplier_name) = lower(?)",
                (client_id, supplier_name),
            ).fetchone()
        if row is None:
            return None
        return dict(row)


def upsert_counterparty(
    db_path: Path,
    client_id: int,
    supplier_name: str,
    supplier_vat: str = "",
    supplier_eik: str = "",
    suggested_account: str = "",
    suggested_vat_term: str = "",
) -> None:
    if not supplier_name or not db_path.exists():
        return
    with _connect(db_path) as conn:
        existing = None
        if supplier_vat:
            existing = conn.execute(
                "SELECT id, seen_count FROM counterparties WHERE client_id = ? AND supplier_vat = ?",
                (client_id, supplier_vat),
            ).fetchone()
        if existing is None:
            existing = conn.execute(
                "SELECT id, seen_count FROM counterparties WHERE client_id = ? AND lower(supplier_name) = lower(?)",
                (client_id, supplier_name),
            ).fetchone()
        now = datetime.utcnow().isoformat(timespec="seconds")
        if existing is None:
            conn.execute(
                """INSERT INTO counterparties
                   (client_id, supplier_name, supplier_eik, supplier_vat,
                    suggested_account, suggested_vat_term, seen_count, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (client_id, supplier_name, supplier_eik or None, supplier_vat or None,
                 suggested_account or None, suggested_vat_term or None, now),
            )
        else:
            conn.execute(
                """UPDATE counterparties
                   SET seen_count = seen_count + 1, last_seen_at = ?
                   WHERE id = ?""",
                (now, existing["id"]),
            )


# ---------------------------------------------------------------------------
# Audit + learn
# ---------------------------------------------------------------------------

def record_extraction(
    db_path: Path,
    *,
    client_id: int | None,
    file_name: str,
    class_id: int | None,
    fields: dict,
    status: str,
) -> None:
    if not db_path.exists():
        return
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO extractions (client_id, file_name, class_id, fields_json, status)
               VALUES (?, ?, ?, ?, ?)""",
            (client_id, file_name, class_id, json.dumps(fields, ensure_ascii=False, default=str), status),
        )


def learn_from(
    db_path: Path,
    *,
    file_name: str,
    text: str,
    fields: dict,
    confidence: float,
    matched_class_id: int | None,
) -> int | None:
    """Materialise a new pending-review class when extraction is high-confidence.

    No-op when:
    - confidence below LEARN_THRESHOLD,
    - a class already matched (we don't auto-mutate seeded classes here),
    - text is empty or DB missing.

    Returns the new class_id when a class is created, else None.
    """
    if (
        not text
        or not db_path.exists()
        or confidence < LEARN_THRESHOLD
        or matched_class_id is not None
    ):
        return None
    fingerprint = _derive_fingerprint(text)
    if not fingerprint.get("must_contain_any"):
        return None
    slug = f"learned_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{abs(hash(file_name)) % 10000:04d}"
    display = fields.get("Supplier/Customer") or "Learned class"
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO issuer_classes
               (slug, display_name, fingerprint_json, language, country,
                samples_seen, pending_review)
               VALUES (?, ?, ?, ?, ?, 1, 1)""",
            (slug, str(display)[:120], json.dumps(fingerprint, ensure_ascii=False),
             None, None),
        )
        return cur.lastrowid


_FOOTER_HINTS = (
    "microinvest invoice pro", "microinvest", "e-docs.bg", "shopify",
    "hubsoft", "generated by", "fakturownia", "invoice ninja",
)


def _derive_fingerprint(text: str) -> dict:
    """Heuristic fingerprint for a learned class.

    Picks a known software/footer hint plus up to 3 relatively unique tokens
    (long words from the first 200 chars) as boost tokens.
    """
    text_lc = text.lower()
    must_any = [hint for hint in _FOOTER_HINTS if hint in text_lc]
    boosts: list[list] = []
    for tok in re.findall(r"[A-Za-zА-Яа-я0-9]{6,}", text[:200]):
        if tok.lower() not in text_lc[200:]:
            continue
        boosts.append([tok.lower(), 10])
        if len(boosts) >= 3:
            break
    return {"must_contain_any": must_any, "boost_tokens": boosts}


# ---------------------------------------------------------------------------
# Bootstrap helper used by callers
# ---------------------------------------------------------------------------

def bootstrap(rules_dir: Path) -> Path:
    """Ensure DB exists and seed clients + classes from JSON if present."""
    db_path = rules_dir / "patterns.sqlite"
    init_db(db_path)
    seed_clients(db_path, rules_dir / "clients.json")
    seed_issuer_classes(db_path, rules_dir / "issuer_classes_seed.json")
    return db_path
