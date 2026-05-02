# CLAUDE.md

이 파일은 Claude Code가 이 repo에서 작업할 때 자동 참조한다. "이 줄이 없으면 Claude가 실수한다" 기준만 담는다.

## Project Overview

칼빈 강요(Institutes of the Christian Religion, 1,251p) 기반 Streamlit 챗봇. 학습 repo(`rag-study-tracks`)와 분리된 production-leaning 프로젝트.

- **모드 (v1)**: Hybrid (BM25+Dense+RRF) / Agentic (`langchain.agents.create_agent`)
- **모드 (v2 예정)**: Knowledge Graph (Neo4j Aura + Cypher + 벡터 결합 + 관계 그래프 시각화)

## Folder Layout

```
calvin-rag-chatbot/
├── app/calvin_chatbot.py     Streamlit 진입점
├── rag_core/                 RAG 코어 (외부 학습 코드 무의존)
│   ├── tokenizer.py          KoreanTokenizer + BM25Retriever
│   ├── postprocess.py        FlashRankReranker, reorder_long_context
│   ├── hybrid.py             HybridRAG (LangGraph StateGraph)
│   ├── agentic.py            AgenticRAG (langchain create_agent)
│   └── builder.py            build_calvin_rag() + CALVIN_PROMPT
├── infra/                    인프라 어댑터
│   ├── env.py                load_env() — .env 자동 탐색
│   ├── document_loader.py    PDF/텍스트 로더
│   └── index_cache.py        FAISS 디스크 캐싱
├── data/calvin/              PDF (gitignore)
└── indexes/                  FAISS 캐시 (gitignore)
```

## Architecture: Hexagonal Dependency

```
app/  ──►  rag_core/  ──►  infra/
```

규칙:
- `rag_core/`는 `app/`을 import하지 않는다.
- `infra/`는 `rag_core/`를 import하지 않는다.
- **학습 repo(`rag-study-tracks`)의 어떤 모듈도 import하지 않는다.** 이 repo는 자체 완결적이어야 한다.

## Unified RAG Interface

모든 RAG 패턴은 다음 시그니처를 따른다.

```python
class XXXRAG:
    PATTERN_NAME: str

    def index_documents(self, documents: list[Document]) -> int: ...
    def query(self, question: str, ...) -> dict[str, Any]:
        # 반환 키 (필수):
        # - final_answer: str
        # - source_documents: list[str]
        # - metadata: dict (pattern, elapsed_seconds, ...)
```

Streaming도 지원: `stream_query()` (Hybrid), `stream_steps()` (Agentic).

## Data / Index Path Resolution

`.env`의 `CALVIN_PDF_PATH`와 `INDEX_DIR`이 우선. 미설정 시 이 repo의 `data/calvin/`과 `indexes/`로 fallback.

학습 repo와 공유하려면 절대경로 지정 (디스크 절약 + 인덱싱 1회만):
```
CALVIN_PDF_PATH=/Users/.../rag-study-tracks/data/calvin/calvin_institutes.pdf
INDEX_DIR=/Users/.../rag-study-tracks/indexes
```

## Code Conventions

- 타입 힌트 필수 (모든 함수의 파라미터/반환).
- 한국어 docstring과 주석. 식별자(클래스/함수명)는 영문.
- **이모지 일체 사용 금지** — 응답/코드/주석/UI 어디에도.
- 마케팅 문구 회피.
- pydantic v2 + pydantic-settings로 설정 외부 주입.
- ruff (`ruff check --fix`, `ruff format`).

## Common Pitfalls

- **Streamlit sys.path 이슈**: `streamlit run app/calvin_chatbot.py`는 프로젝트 루트를 자동 추가하지 않는다. `app/calvin_chatbot.py` 상단에서 직접 추가.
- **인덱스 캐시 키**: `make_cache_key("calvin", f"chunk{N}", f"overlap{M}")` 형식. chunk_size/overlap 변경 시 새 캐시 생성 → 임베딩 재발생.
- **PDF 페이지 인덱싱**: PyMuPDFLoader는 `metadata["page"]`를 0-indexed로 저장. 사용자 표시 시 `+1`.
- **시스템 프롬프트**: `HybridRAGConfig.system_prompt`는 `{context}` 자리표시자를 반드시 포함.
- **Agentic 모드**: `langgraph.prebuilt.create_react_agent`는 deprecated. 항상 `langchain.agents.create_agent` 사용.

## Memory Notes

- 사용자 선호: 이모지 사용 안 함. 차분한 시니어 개발자 톤.
- 사용자 배경: 자바 개발자, Spring AI 학습 목표 병행.
- 시간 제약: 일주일 안에 포트폴리오 시연 가능 상태로.
