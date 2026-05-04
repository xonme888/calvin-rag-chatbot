"""Audit log — SQLite 기반 챗 요청/응답 기록.

운영 환경에서 사고 추적/분석/비용 모니터링을 위한 1차 로그.
``BackgroundTasks`` 로 비동기 기록 — 응답 latency 영향 0.

다중 워커/인스턴스 운영 단계 (Phase 3) 에선 PostgreSQL 또는 CloudWatch Logs 로
어댑터 교체 가능 (`AuditLogPort` 추상화 시점은 트래픽 도달 시 결정).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# DB 경로 — 환경변수로 override (테스트/운영 분리)
_DEFAULT_DB_PATH = Path.home() / ".calvin-rag-chatbot" / "audit.db"


def _resolve_db_path() -> Path:
    env_path = os.getenv("AUDIT_DB_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return _DEFAULT_DB_PATH


@dataclass
class AuditRecord:
    """단일 챗 요청의 audit log 레코드."""

    ip: str = "unknown"
    mode: str = "unknown"
    question: str = ""
    answer_preview: str = ""  # 전체 답변은 길어서 첫 200자만
    tokens_in: int = 0
    tokens_out: int = 0
    cost_krw: float = 0.0
    guard_action: str = "allow"  # "allow" | "input_blocked" | "output_blocked" | "sanitized"
    guard_reason: str | None = None
    elapsed_seconds: float = 0.0
    trace_id: str | None = None  # observability.LangChainTracer 와 결합용
    routed_mode: str | None = None  # 라우터가 결정한 실제 모드
    auto_routed: bool = False
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


def _ensure_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ip TEXT,
                mode TEXT,
                question TEXT,
                answer_preview TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER,
                cost_krw REAL,
                guard_action TEXT,
                guard_reason TEXT,
                elapsed_seconds REAL
            )
            """
        )
        # 추가 컬럼 — 기존 DB 도 ALTER 로 안전하게 보강
        for col, ddl in (
            ("trace_id", "TEXT"),
            ("routed_mode", "TEXT"),
            ("auto_routed", "INTEGER DEFAULT 0"),
        ):
            try:
                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                # 이미 존재 — 무시
                pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON audit_log(trace_id)"
        )
        conn.commit()


@contextmanager
def _connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or _resolve_db_path()
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def log_chat(record: AuditRecord, db_path: Path | None = None) -> None:
    """챗 요청 audit log 기록 — 동기 함수 (BackgroundTasks 안에서 호출)."""
    path = db_path or _resolve_db_path()
    _ensure_schema(path)
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO audit_log "
            "(timestamp, ip, mode, question, answer_preview, "
            " tokens_in, tokens_out, cost_krw, "
            " guard_action, guard_reason, elapsed_seconds, "
            " trace_id, routed_mode, auto_routed) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.timestamp,
                record.ip,
                record.mode,
                record.question[:500],  # 길이 제한
                record.answer_preview[:500],
                record.tokens_in,
                record.tokens_out,
                record.cost_krw,
                record.guard_action,
                record.guard_reason,
                record.elapsed_seconds,
                record.trace_id,
                record.routed_mode,
                1 if record.auto_routed else 0,
            ),
        )
        conn.commit()


def fetch_recent(limit: int = 100, db_path: Path | None = None) -> list[dict[str, Any]]:
    """최근 N개 audit log 조회 — 디버깅/모니터링용."""
    path = db_path or _resolve_db_path()
    _ensure_schema(path)
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_records(db_path: Path | None = None) -> int:
    path = db_path or _resolve_db_path()
    _ensure_schema(path)
    with _connect(path) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM audit_log")
        return cursor.fetchone()[0]
