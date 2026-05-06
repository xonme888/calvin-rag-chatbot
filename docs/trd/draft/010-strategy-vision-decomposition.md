---
status: draft
group: A
created: 2026-05-06
related_prd: docs/prd/draft/006-conversation-first-orchestrator.md, docs/prd/draft/001-tools-input-extension.md
related_trd: docs/trd/draft/006-conversation-first-orchestrator.md
---

# TRD-010: Vision 모드 분해 + 보안 게이팅 (VisionRAG → VisionStrategy)

Vision 은 4개 모드 중 *가장 작고 단순한* 모드다 (`rag_core/vision_rag.py` 122줄, 메서드 2개). 그러나 *retrieval 없는 strategy* 라는 이질성과 *보안·비용 게이팅 부재* 라는 두 가지 분해 결정을 가진다. 본 TRD 는 이 둘을 함께 다룬다.

## 1. AS-IS 분석

### 1.1 VisionRAG.query 책임 (vision_rag.py, 122줄)

| 책임 | 라인 | 비고 |
|---|---|---|
| Attachments → OpenAI multimodal format 변환 | 79-94 | `image_url` 배열, `detail="low"` 고정 |
| Prompt 조립 | 96-99 | SystemMessage (칼빈 신학 context) + HumanMessage |
| LLM 호출 | 104 | `self.llm.invoke()` (gpt-4o-mini, temp=0) |
| 응답 정리 + envelope | 105-122 | `final_answer`, 빈 `source_documents`, metadata |

검색 단계 없음 — `source_documents=[]`, `source_pages=[]` 항상 빈 리스트 (line 110, 115). 1단계 구현 주석 (line 1-4) 이 명시: "RAG 결합 없음, 2단계에서 hybrid 검색 결합 가능".

### 1.2 첨부 흐름 (계층 정합)

| 계층 | 위치 | 형식 | 검증 |
|---|---|---|---|
| 클라이언트 | `web/components/AttachmentInput.tsx:37-73` | 원본 ≤ 25MB, 리사이즈 후 ≤ 2MB (Canvas) | ✓ 클라이언트만 |
| Web 타입 | `web/lib/api.ts:19-23` | `Attachment {type:"image", data_url, name}` | 타입만 |
| API 스키마 | `api/schemas.py:18-28` | `data_url` max_length=10M (base64 ~7MB) | ✗ MIME 화이트리스트 없음 |
| Vision 처리 | `vision_rag.py:84-94` | `att.get("data_url")` | ✗ 형식 검증 없음 |

**결함**: 서버측 MIME 검증 없음, 크기 재검증 없음. PRD-001 §6 의 결정 ("Vision 게이팅은 PRD-2 + PRD-4 도입 후로 게이팅") 이 본 TRD 에서 **부분 해소**.

### 1.3 라우팅 강제

`api/routes/chat.py:_resolve_mode` (line 92-111) — `req.attachments` 가 비어있지 않으면 *사용자가 명시한 mode 보다 우선* 으로 vision 강제. vision 비활성 시 hybrid 로 silent fallback (line 101-108).

### 1.4 Cache / Observability

| 기능 | 위치 |
|---|---|
| LLM cache snapshot | vision_rag.py:74-76 (`cache_snapshot/cache_delta`) |
| trace_event | chat.py:93-98 |
| callbacks (UsageTracker, LangChainTracer) | vision_rag.py:100-102 |

## 2. TO-BE 설계 — 두 가지 분해 결정

### 결정 — Vision 의 도메인 위치

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| A. RetrievalStrategy 로 유지 (`Retriever=None`) | 작음 | 기존 동작 보존 | 비자연스러운 추상 (검색 없는 검색 전략) | |
| B. `Tool` (vision_describe) 로 흡수 → Agentic 안에서 사용 | 중간 | 추상 자연스러움, 도구로 합류 | 첨부 라우팅 흐름 재설계, 라우터가 attachments 를 인식하지 못함 | |
| C. RetrievalStrategy 로 유지하되 *선택적 corpus 검색 통합* | 중간 | 인용 가능 답변 + 추상 자연 | LLM 호출 추가, 비용 증가 | ★ |

추천: **C** — Vision 도 *질문 텍스트에 대해 hybrid 검색을 수행* 하고, 그 결과를 vision LLM 의 context 로 함께 전달. 첨부 1장 + 본문 인용 둘 다 답변에 포함 가능. Vision 1단계 주석이 예고한 "2단계" 합류와 동일. supports() 가 `attachments != ()` 이라는 *본질적* 조건으로 자연스러워진다.

### 2.1 신규/이전 모듈

```
chatbot/infrastructure/
├── strategies/
│   └── vision_strategy.py              RetrievalStrategy 어댑터
├── tools/
│   └── vision/
│       └── vision_describe.py          (선택, 추후 Agentic 흡수용 — 본 TRD 에서 stub)
├── stages/
│   └── prepare_image_payload_stage.py  Attachment → OpenAI multimodal payload
├── validation/
│   └── attachment_validator.py         서버측 MIME/크기 재검증
└── prompts/
    └── vision_prompt.py                vision 시스템 프롬프트 (line 96-99 흡수)
```

### 2.2 책임 매핑

| 기존 (vision_rag.py) | 새 위치 | 비고 |
|---|---|---|
| `__init__` (43-58) — LLM 초기화 | `vision_strategy.py:__init__` | 동일 |
| Attachments 변환 (79-94) | `prepare_image_payload_stage.py` | Stage 단독 |
| Prompt 조립 (96-99) | `prompts/vision_prompt.py` | 동일 |
| LLM 호출 (104) | `vision_strategy.py:run` 안의 단순 호출 | - |
| Envelope (105-122) | `vision_strategy.py:run` 의 RetrievalResult 변환 | citations 는 *Hybrid retriever 결과* 로 채움 |

### 2.3 인터페이스 (Python sketch)

```python
# chatbot/infrastructure/strategies/vision_strategy.py
class VisionStrategy:
    name = "vision"
    label = "Vision"

    def __init__(
        self,
        *,
        vision_llm: BaseChatModel,                  # gpt-4o-mini (vision 지원)
        text_retriever: Retriever | None,           # None 이면 본문 인용 없음
        prepare_payload: Stage[list[Attachment], list[dict]],
        validator: AttachmentValidator,
        config: VisionConfig,
    ) -> None: ...

    def is_available(self) -> tuple[bool, str | None]:
        if not os.getenv("VISION_ENABLED", "").lower() in ("1", "true", "yes"):
            return (False, "VISION_ENABLED 환경변수 비활성")
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        return bool(request.attachments)

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        # 1. 서버측 검증
        for att in request.attachments:
            self._validator.validate(att)  # 실패 시 ValidationError → ToolResult is_error
        # 2. 본문 검색 (선택)
        documents = (
            self._text_retriever.retrieve(request) if self._text_retriever else []
        )
        # 3. multimodal payload 조립
        payload = self._prepare.run(list(request.attachments))
        # 4. LLM 호출 + 응답 합성
        ...
```

### 2.4 AttachmentValidator (보안 게이팅)

```python
# chatbot/infrastructure/validation/attachment_validator.py
class AttachmentValidator:
    """서버측 1차 방어선. PRD-001 의 vision 게이팅 부분 충족."""

    ALLOWED_MIME: frozenset[str] = frozenset({
        "image/jpeg", "image/png", "image/webp", "image/gif",
    })
    MAX_DATA_URL_BYTES: int = 10 * 1024 * 1024  # ~7MB base64
    MAX_ATTACHMENTS: int = 4

    def validate(self, att: Attachment) -> None:
        """위반 시 AttachmentValidationError raise."""
```

### 2.5 라우터 정합

`_resolve_mode` (chat.py:75-124) 의 *attachments 비어있지 않으면 vision 강제* 로직은 본 TRD 의 라우터(application/nodes/select_strategy.py)로 이동:

```python
# chatbot/application/nodes/select_strategy.py
def select_strategy(state: ConversationState, *, registry: ...) -> ConversationState:
    request = _to_request(state)
    candidates = registry.available_for(request)
    # 첨부가 있으면 vision 우선 (supports() 에서 정의됨, 다른 strategy 는 첨부에 False)
    # 라우터는 그저 supports() 결과를 신뢰.
    ...
```

`supports()` 의 *순서 정의* 만으로 자연스럽게 vision 우선이 보장된다 (Hybrid/Agentic/KG 는 `not request.attachments` 조건). _resolve_mode 의 명시 분기는 사라진다.

## 3. 마이그레이션 단계

| 단계 | 작업 | 검증 |
|---|---|---|
| 2-D.1 | `validation/attachment_validator.py` | unit: 정상 image / 큰 이미지 / 비허용 MIME / 첨부 5개 |
| 2-D.2 | `prompts/vision_prompt.py`, `stages/prepare_image_payload_stage.py` | OpenAI payload 동일 (data_url 포맷 동일) |
| 2-D.3 | `strategies/vision_strategy.py` (text_retriever=None 경로) | 기존 vision 동작과 응답 동일 |
| 2-D.4 | `vision_strategy` 의 text_retriever 통합 (Hybrid 재사용) | 인용 추가 노출, 본문 발췌가 답변에 합리적 |
| 2-D.5 | `_resolve_mode` 의 attachments 분기 제거 (PR 4 시) | supports() 만으로 vision 라우팅 |
| 2-D.6 | tests | unit + 통합 |

## 4. 테스트 계획

### 4.1 단위

| 모듈 | 케이스 |
|---|---|
| AttachmentValidator | 정상 / 비허용 MIME / 크기 초과 / 첨부 ≥ 5 / data_url 잘못된 형식 |
| prepare_image_payload_stage | 정상 1장 / 2장 / data_url vs https URL |
| VisionStrategy.supports | 첨부 있음 True / 없음 False |
| VisionStrategy.is_available | VISION_ENABLED=true / false / 미설정 |

### 4.2 통합

| 시나리오 | 검증 |
|---|---|
| 정상 이미지 + 질문 | answer 채워짐, citations 비어있을 수 있음 (text_retriever=None 경로) |
| 이미지 + text_retriever=Hybrid | citations 채워짐, source_pages_label 노출 |
| 비허용 MIME | RetrievalResult.metadata.error="invalid_attachment_mime", answer 는 사과 메시지 |
| VISION_ENABLED=false | is_available() False, 라우터가 hybrid 로 silent fallback |

### 4.3 회귀

기존 vision 응답 envelope (`source_documents=[]`, `metadata.pattern="vision"`) 보존. text_retriever 통합은 *선택적* — 환경변수 `VISION_WITH_RETRIEVAL=true` 일 때만 활성 (PRD-001 의 5번 시나리오 충족 시점은 별도 결정).

## 5. 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| AttachmentValidator 의 MIME 추론 실패 | 비허용 이미지 통과 | data_url 의 `data:image/...;base64,` prefix 파싱 + magic byte 검증 (선택) |
| text_retriever 통합 시 첫 토큰 지연 +500ms | UX 저하 | env flag 로 단계 도입, 디폴트 off |
| 첨부 1장 = 65토큰 가정 (detail="low") 변경 | 비용 추정 어긋남 | OpenAI 가격 변경 시 docs/me 에 기록, 본 TRD 추정치는 ~₩0.1/장 |
| 라우팅 흐름 변경으로 "이미지 + 단순 본문 질문" 케이스 회귀 | 답변 품질 저하 | PR 4 시 시나리오 테스트 1건 (첨부 + 본문 질문) 필수 |

## 6. 후속

- vision_describe Tool 어댑터 (Agentic 안에서 vision 도구로 사용) — 본 TRD 에선 stub.
- 이미지 캐싱 (동일 base64 해시 시 LLM 호출 스킵) — 비용 절감 PRD.
- 사용자별 daily vision cap (PRD-001 의 게이팅 후속) — PRD-004 합류 후.
- 매직 바이트 기반 MIME 검증 — `python-magic` 의존성 추가 검토.
