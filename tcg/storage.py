"""Persistent submission history (the explicitly-requested feature).

Every analyzed card can be saved to a local SQLite database with its image,
identification, generated listing, valuation, and the comp snapshot that backed
it. The History tab reads from here so the user can revisit, export, or delete
past submissions.

Design notes
------------
* One row per submission; structured payloads stored as JSON text columns.
* Images are written to ``<data_dir>/images/`` and referenced by path, keeping
  the DB small and the originals viewable.
* Connections are opened per-call (``check_same_thread=False``) so this is safe
  under Streamlit's threaded reruns without a global connection.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .models import CardIdentity, GeneratedListing, PriceReport, now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    query         TEXT,
    player        TEXT,
    title         TEXT,
    description   TEXT,
    condition     TEXT,
    estimate      REAL,
    low           REAL,
    high          REAL,
    currency      TEXT,
    confidence    TEXT,
    n_comps       INTEGER,
    sources       TEXT,
    image_path    TEXT,
    thumb_path    TEXT,
    identity_json TEXT,
    listing_json  TEXT,
    report_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_submissions_created ON submissions(created_at DESC);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_submission(
    *,
    db_path: Path,
    images_dir: Path,
    identity: CardIdentity,
    listing: GeneratedListing,
    report: PriceReport,
    image_jpeg: Optional[bytes] = None,
    thumb_jpeg: Optional[bytes] = None,
) -> str:
    """Persist one submission and return its id."""
    init_db(db_path)
    sub_id = uuid.uuid4().hex[:12]

    image_path = thumb_path = ""
    if image_jpeg or thumb_jpeg:
        images_dir.mkdir(parents=True, exist_ok=True)
    if image_jpeg:
        image_path = str(images_dir / f"{sub_id}.jpg")
        Path(image_path).write_bytes(image_jpeg)
    if thumb_jpeg:
        thumb_path = str(images_dir / f"{sub_id}_thumb.jpg")
        Path(thumb_path).write_bytes(thumb_jpeg)

    v = report.valuation
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO submissions
               (id, created_at, query, player, title, description, condition,
                estimate, low, high, currency, confidence, n_comps, sources,
                image_path, thumb_path, identity_json, listing_json, report_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sub_id,
                now_iso(),
                report.query,
                identity.player,
                listing.ebay_title,
                listing.description,
                listing.suggested_condition,
                v.estimate,
                v.low,
                v.high,
                v.currency,
                v.confidence,
                v.n,
                json.dumps(report.sources_used),
                image_path,
                thumb_path,
                json.dumps(identity.to_dict()),
                json.dumps(listing.to_dict()),
                json.dumps(report.to_dict()),
            ),
        )
    return sub_id


def list_submissions(db_path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, created_at, query, player, title, condition, estimate,
                      low, high, currency, confidence, n_comps, sources,
                      image_path, thumb_path
               FROM submissions ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_submission(db_path: Path, sub_id: str) -> Optional[dict[str, Any]]:
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE id = ?", (sub_id,)
        ).fetchone()
    if row is None:
        return None
    rec = dict(row)
    for key in ("identity_json", "listing_json", "report_json", "sources"):
        if rec.get(key):
            try:
                rec[key.replace("_json", "")] = json.loads(rec[key])
            except (ValueError, TypeError):
                rec[key.replace("_json", "")] = None
    return rec


def delete_submission(db_path: Path, sub_id: str) -> bool:
    rec = get_submission(db_path, sub_id)
    if rec is None:
        return False
    for key in ("image_path", "thumb_path"):
        p = rec.get(key)
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
    return True


def count_submissions(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]


def _csv_safe(val: Any) -> Any:
    """Neutralize spreadsheet formula injection (=, +, -, @, tab, CR leading chars)."""
    if isinstance(val, str) and val[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + val
    return val


def export_csv(db_path: Path) -> str:
    rows = list_submissions(db_path, limit=100_000)
    cols = [
        "id", "created_at", "player", "title", "condition", "estimate",
        "low", "high", "currency", "confidence", "n_comps", "query", "sources",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: _csv_safe(v) for k, v in r.items()})
    return buf.getvalue()
