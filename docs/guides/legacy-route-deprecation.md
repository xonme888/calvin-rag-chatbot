# 레거시 라우트 Deprecation 일정

> 작성일: 2026-05-06
> 관련 PR: TRD-006 §3 의 PR 6 (레거시 제거)

## 배경

PR 5 (UI 절체) 까지 두 라우트가 *공존* 한다:

| 라우트 | 구현 | 의도 |
|---|---|---|
| `/chat/sync` (동기) | `api/routes/chat.py:_invoke_sync` 의 모드별 분기 | 레거시 — Hybrid/Agentic/KG/Vision 호출 분기 |
| `/chat/stream` (SSE) | `api/routes/chat.py:_stream_chat_events` | 레거시 — 모드별 SSE 변환 |
| `/chat/v2` (동기) | `api/routes/chat_v2.py:chat_v2` | **현행** — chatbot 패키지의 LangGraph orchestrator |
| `/chat/v2/stream` (SSE) | `api/routes/chat_v2.py:chat_v2_stream` | **현행** — orchestrator 결과 청크 분할 SSE |

프론트는 ``NEXT_PUBLIC_CHAT_V2=true`` 환경변수로 두 경로 사이를 토글 (PR 5/6).

## Deprecation 단계

### Phase 1 — 공존 (현재)

- 두 라우트 모두 활성. ``NEXT_PUBLIC_CHAT_V2`` 토글로 빌드 시점 분기.
- `/chat/v2` envelope 이 `/chat/sync` 와 호환 (cited_pages, source_pages_label, suggested_followups 등 모두 노출).
- 레거시 라우트의 회귀 테스트 (`tests/test_api_endpoints.py`) 통과 유지.

### Phase 2 — 안정화 검증 (1주)

- 운영/프리뷰 환경에 ``NEXT_PUBLIC_CHAT_V2=true`` 활성. audit 로그·답변 품질 비교.
- 양 라우트의 응답 envelope 키 셋·답변 텍스트 ±5% 회귀 임계 모니터링.
- KG/Vision 환경변수 토글 (``KG_ENABLED``, ``VISION_ENABLED``) 의 부트스트랩 동작 확인.

### Phase 3 — 레거시 제거 (별도 PR)

다음 작업을 별도 PR 로 분리한다 — 데이터 손실 위험은 없으나 운영 영향 가능성 명시 후 진행.

| 작업 | 파일 | 영향 |
|---|---|---|
| `_invoke_sync` 분기 제거 | `api/routes/chat.py:147-202` | `/chat/sync` 가 chat_v2 wrapper 로 환원 |
| `/chat/sync` / `/chat/stream` 핸들러 제거 | `api/routes/chat.py` 전체 | 외부 클라이언트가 두 경로 사용 시 404 |
| `mode_dispatcher` / `mode_registry` 직접 사용처 정리 | `rag_core/mode_*.py` | KG/Agentic 모드 객체 직접 참조 코드 정리 |
| `api/dependencies.py` 의 `get_agentic_rag` / `get_kg_rag` 정리 | `api/dependencies.py` | chatbot bootstrap 단일 경로화 |
| 회귀 테스트 갱신 | `tests/test_api_endpoints.py`, `tests/test_mode_dispatcher.py` 등 | chat_v2 단일 경로 검증 |

## 절체 체크리스트

레거시 제거 PR 시작 전:

- [ ] 1주간 ``NEXT_PUBLIC_CHAT_V2=true`` 운영 환경 적용 + audit 로그 정합 확인.
- [ ] 외부 API 클라이언트가 ``/chat/sync`` 또는 ``/chat/stream`` 을 직접 호출하지 않는지 확인 (없거나 모두 절체).
- [ ] envelope 호환성 회귀 0 (스냅샷 테스트 비교).
- [ ] KG/Agentic/Vision 환경변수 토글의 bootstrap 동작 정상.
- [ ] 새 corpus 추가 가이드 (`docs/guides/adding-a-corpus.md`) 가 chat_v2 기준으로 갱신됐는지.

## 비고

- `rag_core/` 자체는 *학습 트랙* 으로 유지된다 — chat_v2 는 어댑터를 통해 재사용. 직접 참조하는 라우트만 정리.
- 영속화 (PRD-002) 합류 시점에 ``Conversation.id`` 매핑이 추가되며, 그때 chat_v2 가 *유일한* 라우트가 된다.
