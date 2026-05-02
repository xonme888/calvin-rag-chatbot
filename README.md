# Calvin RAG Chatbot

존 칼빈의 『기독교 강요』(Institutes of the Christian Religion, 1559) 한국어 번역본 1,251 페이지를 대상으로 한 다중 모드 RAG 챗봇.

## 모드 (v1)

| 모드 | 흐름 | 특징 |
|---|---|---|
| **Hybrid** | retrieve(BM25 + Dense + RRF) → generate | 빠른 응답, 토큰 스트리밍, dense_weight 슬라이더 |
| **Agentic** | LLM이 도구 호출 자율 결정 (`langchain.agents.create_agent`) | 도메인 외 질문 자동 거절, 단계 진행 표시, LLM 캐시 |
| **Knowledge Graph** | 엔티티 추출 → Cypher 부분 그래프 + 벡터 검색 결합 | Neo4j 인물/개념 관계 그래프 시각화 (`streamlit-agraph`) |

KG 모드 백엔드는 **Hexagonal Port/Adapter** 로 추상화 — 로컬 Docker / Neo4j Aura를 `.env` 의 `NEO4J_URI` 한 줄 변경으로 전환.

## 설치

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e '.[kg,dev]'  # KG 모드 + 테스트 의존성 포함
cp .env.example .env             # OPENAI_API_KEY 입력
```

PDF 데이터는 본인이 다음 경로에 직접 배치 (저작권):
```
data/calvin/calvin_institutes.pdf
```

또는 학습 repo와 공유하려면 `.env`에서 `CALVIN_PDF_PATH`, `INDEX_DIR`를 절대경로로 지정.

### KG 모드 사용 (선택)

```bash
docker compose up -d           # 로컬 Neo4j 가동 (또는 Aura URI를 .env에 입력)
python scripts/index_kg.py --balanced 30 --no-confirm   # 5단원 × 30청크 인덱싱 (~₩52, ~19분)
```

확장: `--full` (전체 5단원 ~₩180), `--clear` (그래프 초기화).

### 테스트

```bash
python -m pytest tests/ -v   # KG Port + Mock 어댑터 단위 테스트 (LLM/DB 호출 0회)
```

## 실행

```bash
streamlit run app/calvin_chatbot.py
```

## 시연 시나리오

면접/포트폴리오 데모용 큐레이션 질문 + 모드별 강점 매핑은 [`docs/demo-questions.md`](docs/demo-questions.md) 참고. 5분 데모 흐름 포함.

## 구조

```
calvin-rag-chatbot/
├── app/calvin_chatbot.py        Streamlit UI (3 모드 토글)
├── rag_core/                    RAG 코어 (외부 학습 코드 무의존)
│   ├── tokenizer.py             KoreanTokenizer + BM25Retriever
│   ├── postprocess.py           FlashRankReranker, long-context reorder
│   ├── hybrid.py                HybridRAG (LangGraph StateGraph)
│   ├── agentic.py               AgenticRAG (langchain create_agent)
│   ├── builder.py               build_calvin_rag() — 칼빈 도메인 빌더
│   └── kg/                      KG 모드 서브패키지 (Hexagonal)
│       ├── port.py              KnowledgeGraphPort (Protocol)
│       ├── config.py            Neo4jConfig (URI scheme으로 local/aura 자동 감지)
│       ├── neo4j_adapter.py     단일 Adapter (langchain-neo4j)
│       ├── factory.py           get_kg_adapter() 싱글톤
│       ├── extractor.py         5단원 정의 + 청크 필터 + 비용 추정
│       ├── visualization.py     SubgraphData → streamlit-agraph 변환
│       └── rag.py               KnowledgeGraphRAG (Cypher + 벡터 결합)
├── infra/                       인프라 어댑터
│   ├── env.py                   .env 로더
│   ├── document_loader.py       PDF 로더 (PyMuPDFLoader)
│   └── index_cache.py           FAISS 디스크 캐싱
├── scripts/index_kg.py          KG 인덱싱 CLI (--sample/--balanced/--full/--clear)
├── tests/test_kg_port.py        Mock 어댑터 단위 테스트 (LLM/DB 0회)
├── docs/
│   ├── demo-questions.md        시연 시나리오 + 모드별 강점 매핑
│   └── me/                      의사결정 기록 (방법론·관점)
├── docker-compose.yml           로컬 Neo4j 1줄 셋업
├── data/calvin/                 PDF (gitignore)
└── indexes/                     FAISS 캐시 (gitignore)
```

## 의존 관계

```
app/  ──►  rag_core/  ──►  infra/
                ▲              ▲
                │       langchain-core, langchain-openai, langgraph, faiss
                │
        rag_core/kg/  (KG 모드)
                │
                └──►  KnowledgeGraphPort (Protocol)
                            │
                ┌───────────┴────────────┐
        Neo4jAdapter             InMemoryKGAdapter (테스트용)
        (langchain-neo4j)
```

- 학습 repo (`rag-study-tracks`)에 import 의존 0
- 도메인(`rag_core/kg/`)은 Port만 알고 어댑터를 모름 — Hexagonal
- Mock 어댑터(`tests/test_kg_port.py`)로 LLM/DB 호출 없이 RAG 로직 검증 가능

## 비용 (실측)

| 항목 | 비용 | 시간 |
|---|---|---|
| FAISS 임베딩 (5,657청크, 1회성) | ~₩120 | ~10분 |
| KG 인덱싱 — 5단원 150청크 (단원별 균등 30) | **~₩52** | **~19분** |
| 운영 (질문당) — Hybrid | ~₩1 | ~3초 |
| 운영 (질문당) — Agentic | ~₩3 | ~5~7초 |
| 운영 (질문당) — KG | ~₩2 | ~3~5초 |
| Neo4j (로컬 Docker) | $0 | — |
| Neo4j Aura Free | $0 | — |

### 확장 가능성

KG 인덱싱은 비용 의식을 위해 **5단원 균형안 ~150청크**만 선택 인덱싱했다. 동일 파이프라인으로 확장 시:

| 범위 | 청크 | 비용 추정 | 시간 추정 |
|---|---|---|---|
| 균형안 5단원 (현재) | ~150 | ~₩52 | ~19분 |
| 5단원 전체 | ~530 | ~₩180 | ~1시간 |
| 칼빈 강요 전체 | ~5,657 | ~₩1,920 | ~3시간 |

확장은 `python scripts/index_kg.py --full` 한 줄로 가능. 누적 인덱싱이라 기존 그래프 위에 누적된다 (재추출 없음).
