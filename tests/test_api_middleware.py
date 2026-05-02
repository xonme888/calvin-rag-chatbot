"""API 미들웨어 단위 테스트 — audit_log / rate_limiter / token_budget.

LLM/네트워크 호출 0회. SQLite는 임시 디렉토리 사용.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.middleware.audit_log import (
    AuditRecord,
    count_records,
    fetch_recent,
    log_chat,
)
from api.middleware.token_budget import check_token_budget
from infra.usage_tracker import SessionStats


# ====================================================================
# audit_log
# ====================================================================
def test_log_chat_writes_record(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    record = AuditRecord(
        ip="127.0.0.1",
        mode="hybrid",
        question="예정론?",
        answer_preview="칼빈은...",
        tokens_in=120,
        tokens_out=300,
        cost_krw=0.42,
        guard_action="allow",
        elapsed_seconds=1.23,
    )
    log_chat(record, db_path=db)
    assert count_records(db_path=db) == 1


def test_fetch_recent_returns_in_descending_order(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    for i in range(3):
        log_chat(AuditRecord(question=f"Q{i}", mode="hybrid"), db_path=db)

    rows = fetch_recent(limit=10, db_path=db)
    assert len(rows) == 3
    # id desc — 가장 최근이 첫 항목
    assert rows[0]["question"] == "Q2"
    assert rows[2]["question"] == "Q0"


def test_log_chat_truncates_long_text(tmp_path: Path) -> None:
    """질문/답변이 너무 길면 잘라서 저장."""
    db = tmp_path / "audit.db"
    record = AuditRecord(
        question="x" * 1000,
        answer_preview="y" * 1000,
        mode="hybrid",
    )
    log_chat(record, db_path=db)
    rows = fetch_recent(db_path=db)
    assert len(rows[0]["question"]) == 500
    assert len(rows[0]["answer_preview"]) == 500


def test_audit_record_default_timestamp() -> None:
    """timestamp 미지정 시 자동으로 ISO 형식 부여."""
    r = AuditRecord(question="Q", mode="hybrid")
    assert "T" in r.timestamp  # ISO 8601


# ====================================================================
# token_budget
# ====================================================================
def test_token_budget_passes_under_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_TOKEN_CAP", "1000")
    stats = SessionStats()
    stats.record(mode="Hybrid", input_tokens=100, output_tokens=50, model="gpt-4o-mini")
    # 누적 150 < 1000 → 통과
    check_token_budget(stats)  # raises 없음


def test_token_budget_blocks_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_TOKEN_CAP", "100")
    stats = SessionStats()
    stats.record(mode="Hybrid", input_tokens=80, output_tokens=30, model="gpt-4o-mini")
    # 누적 110 >= 100 → 429
    with pytest.raises(HTTPException) as exc:
        check_token_budget(stats)
    assert exc.value.status_code == 429
    assert "한도 초과" in exc.value.detail


def test_token_budget_default_cap_is_high() -> None:
    """기본 cap 은 1,000,000 — 일상 사용 차단 안 됨."""
    os.environ.pop("DAILY_TOKEN_CAP", None)
    stats = SessionStats()
    stats.record(mode="Hybrid", input_tokens=500_000, output_tokens=400_000, model="gpt-4o-mini")
    # 누적 900,000 < 1,000,000 → 통과
    check_token_budget(stats)


# ====================================================================
# Rate limiter — slowapi 통합은 main app 단위 테스트로 대체
# (단위 테스트로는 slowapi 의 Limiter 인스턴스만 검증)
# ====================================================================
def test_rate_limiter_instance_configured() -> None:
    from api.middleware.rate_limiter import limiter

    assert limiter is not None
    # limit 데코레이터가 callable
    assert callable(limiter.limit)
    # key_func 설정
    assert limiter._key_func is not None
