# Calvin RAG Chatbot

존 칼빈의 『기독교 강요』(Institutes of the Christian Religion, 1559) 한국어 번역본 1,251 페이지를 대상으로 한 Hybrid RAG 챗봇.

## 모드 (v1)

| 모드 | 흐름 | 특징 |
|---|---|---|
| **Hybrid** | retrieve(BM25 + Dense + RRF) → generate | 빠른 응답, 토큰 스트리밍, dense_weight 슬라이더 |
| **Agentic** | LLM이 도구 호출 자율 결정 (`langchain.agents.create_agent`) | 도메인 외 질문 자동 거절, 단계 진행 표시, LLM 캐시 |

v2 예정: **Knowledge Graph** 모드 (Neo4j Aura + Cypher + 벡터 검색 결합 + 관계 그래프 시각화)

## 설치

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .
cp .env.example .env  # OPENAI_API_KEY 입력
```

PDF 데이터는 본인이 다음 경로에 직접 배치 (저작권):
```
data/calvin/calvin_institutes.pdf
```

또는 학습 repo와 공유하려면 `.env`에서 `CALVIN_PDF_PATH`, `INDEX_DIR`를 절대경로로 지정.

## 실행

```bash
streamlit run app/calvin_chatbot.py
```

## 구조

```
calvin-rag-chatbot/
├── app/calvin_chatbot.py     Streamlit UI
├── rag_core/                 RAG 코어 구현 (외부 학습 코드 무의존)
│   ├── tokenizer.py          KoreanTokenizer + BM25Retriever
│   ├── postprocess.py        FlashRankReranker, long-context reorder
│   ├── hybrid.py             HybridRAG (LangGraph StateGraph)
│   ├── agentic.py            AgenticRAG (langchain create_agent)
│   └── builder.py            build_calvin_rag() — 칼빈 도메인 빌더
├── infra/                    인프라 어댑터
│   ├── env.py                .env 로더
│   ├── document_loader.py    PDF 로더 (PyMuPDFLoader)
│   └── index_cache.py        FAISS 디스크 캐싱
├── data/calvin/              PDF (gitignore)
├── indexes/                  FAISS 캐시 (gitignore)
└── tests/
```

## 의존 관계

```
app/  ──►  rag_core/  ──►  infra/
                ▲
              langchain-core, langchain-openai, langgraph, faiss
```

학습 repo (`rag-study-tracks`)에 의존하지 않는다.

## 비용 (참고)

- 인덱싱 1회성 (gpt-4o-mini + text-embedding-3-small): ~₩120 / ~10분
- 운영 (질문당): Hybrid ~₩1, Agentic ~₩3
- Neo4j Aura Free 티어: $0
