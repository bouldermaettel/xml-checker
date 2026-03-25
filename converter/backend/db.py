from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "output" / "conversions_poc.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input_filename TEXT NOT NULL,
                input_format TEXT NOT NULL,
                input_sha1 TEXT NOT NULL,
                output_filename TEXT NOT NULL,
                output_xml TEXT NOT NULL,
                status TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversions_input_sha1 ON conversions(input_sha1)"
        )


def find_by_hash(input_sha1: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, input_filename, input_format, input_sha1, output_filename, output_xml,
                   status, warnings_json, meta_json, created_at
            FROM conversions
            WHERE input_sha1 = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (input_sha1,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "inputFilename": row["input_filename"],
        "detectedFormat": row["input_format"],
        "inputSha1": row["input_sha1"],
        "filename": row["output_filename"],
        "xml": row["output_xml"],
        "status": row["status"],
        "warnings": json.loads(row["warnings_json"]),
        "meta": json.loads(row["meta_json"]),
        "createdAt": row["created_at"],
    }


def save_conversion(
    *,
    input_filename: str,
    input_format: str,
    input_sha1: str,
    output_filename: str,
    output_xml: str,
    warnings: list[str],
    meta: dict[str, str],
    status: str = "success",
) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO conversions (
                input_filename,
                input_format,
                input_sha1,
                output_filename,
                output_xml,
                status,
                warnings_json,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                input_filename,
                input_format,
                input_sha1,
                output_filename,
                output_xml,
                status,
                json.dumps(warnings),
                json.dumps(meta),
            ),
        )
        return int(cursor.lastrowid)


def list_recent(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, input_filename, input_format, input_sha1, output_filename,
                   status, warnings_json, meta_json, created_at
            FROM conversions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "inputFilename": row["input_filename"],
            "detectedFormat": row["input_format"],
            "inputSha1": row["input_sha1"],
            "filename": row["output_filename"],
            "status": row["status"],
            "warnings": json.loads(row["warnings_json"]),
            "meta": json.loads(row["meta_json"]),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def get_conversion(conversion_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, input_filename, input_format, input_sha1, output_filename, output_xml,
                   status, warnings_json, meta_json, created_at
            FROM conversions
            WHERE id = ?
            LIMIT 1
            """,
            (conversion_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "inputFilename": row["input_filename"],
        "detectedFormat": row["input_format"],
        "inputSha1": row["input_sha1"],
        "filename": row["output_filename"],
        "xml": row["output_xml"],
        "status": row["status"],
        "warnings": json.loads(row["warnings_json"]),
        "meta": json.loads(row["meta_json"]),
        "createdAt": row["created_at"],
    }
