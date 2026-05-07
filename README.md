---
title: Calvin RAG API
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-mode RAG over Calvin's Institutes (Korean translation)
---

# Calvin RAG Chatbot

존 칼빈 『기독교 강요』(1559) 한국어 번역본 1,251 페이지를 대상으로 하는 **대화형 RAG 챗봇**.
4 가지 검색 전략을 한 오케스트레이터에서 자동 선택하며, 멀티턴 대화·Magic Link 로그인·Supabase 영속화를 갖춘 production-leaning 시연 작품이다.

> **Demo**: 운영 URL 은 배포 시 추가. 시연 흐름은 [`docs/demo-questions.md`](docs/demo-questions.md) 참고.

> HF Space frontmatter 안내: 위 YAML 블록은 Hugging Face Spaces 가 빌드 메타로 사용한다. GitHub 에서는 일반 README, HF 에서는 Docker Space 설정으로 이중 동작.

---

## 무엇을 하는가

| 모드 | 검색 전략 | 강점 |
|---|---|---|
| **Hybrid** | BM25 + Dense + RRF + FlashRank rerank | 빠른 응답, 토큰 스트리밍 |
| **Agentic** | LLM 도구 호출 자율 결정 (`langchain.agents.create_agent`) | 도메인 외 자동 거절, 단계 진행 표시 |
| **Knowledge Graph** | 엔티티 추출 → Cypher 부분그래프 + 벡터 결합 | Neo4j 인물/개념 관계 |
| **Vision** | GPT-4o vision + 이미지 첨부 | 책 사진/필사 이미지 질문 |

사용자는 모드를 *직접 고르지 않는다*. 대화 입력이 들어오면 LangGraph 오케스트레이터가
의도를 분류하고(`NEW_QUESTION` / `FOLLOWUP` / `META_RECAP` / `IRRELEVANT`),
첨부와 도메인 적합도를 보고 4 전략 중 하나를 선택한다. 사용자는 결과만 본다.

### 대표 기능

- **멀티턴 대화 + META 질문** — "방금 무슨 얘기 했지?" 같은 회상도 본문 인용 강요 없이 처리
- **Magic Link 인증** — 비밀번호 없는 이메일 로그인 (Supabase Auth)
- **사이드바 진실원천** — 로그인 시 다른 브라우저에서도 같은 대화 목록 복원
- **익명 → 계정 마이그레이션** — 비로그인 시절 IndexedDB 대화를 1회 모달로 옮길 수 있음
- **출처 페이지 표시** — 답변 하단에 PDF 페이지 인용

---

## 기술 스택

```
[ Next.js 15 (App Router, RSC) ]   ← 프론트, Tailwind, Supabase JS
            │ HTTPS + Bearer JWT
            ▼
[ FastAPI + LangGraph ]            ← 대화 우선 오케스트레이터
            │
   ┌────────┼─────────┬─────────┐
   ▼        ▼         ▼         ▼
 Hybrid  Agentic   KG (Neo4j)  Vision   ← RetrievalStrategy 어댑터 4종
   │        │         │
   └────────┴─────────┘
            │
[ Supabase Postgres + RLS ]        ← conversations(JSONB) 1테이블
[ FAISS · OpenAI · LangChain ]
```

- **백엔드**: Python 3.11, FastAPI, LangGraph, LangChain, FAISS, pydantic v2, structlog
- **프론트**: Next.js 15, React 19, TypeScript strict, Tailwind, idb-keyval
- **저장소**: Supabase (Postgres + Auth + RLS), Neo4j Aura(또는 로컬 Docker), FAISS 디스크 캐시
- **모델**: OpenAI GPT-4o / GPT-4o-mini, text-embedding-3-small
- **CI/CD**: GitHub Actions → HF Spaces (Docker), Vercel (프론트)

---

## 아키텍처 결정 사항

### 1. 대화 우선 오케스트레이터 — 모드 디스패치를 폐기

초기 설계는 사용자가 모드를 고르고 백엔드가 `mode` 파라미터로 분기했다.
이 구조에서는 "예정론 그래프 보여줘" → "그거 요약해줘" 같은 후속 질문이
*다른 모드로 분기하면서 대화 맥락이 끊어지는* 문제가 있었다.

해결: `chatbot/` 패키지에 LangGraph `StateGraph` 기반 오케스트레이터를 두고,
검색 전략 4종은 `RetrievalStrategy` Port 의 어댑터로 *아래에* 배치했다. 의도 분류
→ 전략 선택 → 답변 생성 흐름이 **대화 단위**로 흘러가, 멀티턴이 모드 경계를 넘어도 깨지지 않는다.

### 2. Hexagonal Architecture

```
chatbot/domain/        ← Conversation, Turn, Message, Intent (frozen Pydantic)
chatbot/application/   ← orchestrator graph, strategy selector
chatbot/infrastructure/ ← Supabase, OpenAI, Neo4j 어댑터
api/                   ← FastAPI 라우트 (Presentation)
```

도메인은 어떤 프레임워크에도 의존하지 않는다. 검색 전략·영속화·인증을 *Protocol* 로
선언하고 인프라가 구현 — 테스트는 `FakeStore`/`FakeIdentifier` 로 LLM·DB 호출 0회.

### 3. Supabase JSONB 1테이블 영속화

```sql
create table conversations (
    id uuid primary key,
    user_id uuid references auth.users(id),
    state jsonb not null,           -- domain Conversation 전체 직렬화
    title text, updated_at timestamptz, created_at timestamptz
);
alter table conversations enable row level security;
create policy "본인만" on conversations
    for all using (auth.uid() = user_id);
```

- *왜 1테이블 JSONB?* — 도메인 모델 변경 시 마이그레이션 비용 0. 멀티턴 회상에는 부분 컬럼이 필요 없다.
- *왜 자체 구현?* — `langgraph-checkpoint-postgres` 는 graph 내부 상태용이라 사이드바 표시·삭제 같은 *사용자 관점* 작업에 어울리지 않았다.
- *RLS + `.eq("user_id")` 이중 방어* — 정책 실수 시에도 격리 유지.

### 4. 사이드바

원천 = 서버,
IndexedDB = 익명 캐시

로그인 사용자는 Supabase 가 원천. 미로그인 사용자는 IndexedDB(idb-keyval).
로그인 시점에 이전 익명 데이터가 있으면 *일회성 모달* 이 떠 "옮기기 / 보관 / 삭제" 를 묻는다.
부분 실패 시 서버 응답의 `skipped_ids` 항목만 IndexedDB 에 잔존시켜 데이터 손실을 막는다.

다기기 *실시간* 동기화(Realtime postgres_changes)는 의도적으로 미구현 — 로그인 마운트 시 한 번 fetch 로 동기화되며 시연 핵심이 아니다.

### 5. KG 모드의 환경 추상화

```
KnowledgeGraphPort (Protocol)
  ├── Neo4jAdapter        (langchain-neo4j) — Aura/Local 자동 감지
  └── InMemoryKGAdapter   (테스트용)
```

`.env` 의 `NEO4J_URI` 한 줄로 로컬 Docker ↔ Aura 전환. 로컬 LLM/DB 호출 없이 Mock 으로
RAG 로직 단위 테스트 가능.

### 6. 인증 흐름의 점진적 도입

기존 `INVITE_CODES` (단순 해시 비교) 는 그대로 유지하면서 `AuthGate (Magic Link)` 를 *위에* 얹었다.
Supabase 미설정 환경에서도 InviteGate 만으로 동작하므로, 시연 스테이징 / 프로덕션 분리가 자연스럽다.

---

## 빠른 시작

### 1. 백엔드

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e '.[all]'
cp .env.example .env  # OPENAI_API_KEY, SUPABASE_*, NEO4J_* 채움
uvicorn api.main:app --reload --port 8000
```

PDF 는 직접 배치 (저작권):
```
data/calvin/calvin_institutes.pdf
```

### 2. 프론트

```bash
cd web
npm install
echo "NEXT_PUBLIC_API_BASE=http://localhost:8000" > .env.local
echo "NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co" >> .env.local
echo "NEXT_PUBLIC_SUPABASE_ANON_KEY=..." >> .env.local
npm run dev
```

`http://localhost:3000` 접속 → Magic Link 또는 InviteCode 로 진입.

### 3. (선택) KG 모드

```bash
docker compose up -d                                    # 로컬 Neo4j (또는 Aura URI)
python scripts/index_kg.py --balanced 30 --no-confirm   # 5단원 × 30청크 (~₩52, ~19분)
```

### 4. 테스트

```bash
pytest -q          # 백엔드 457 케이스
cd web && npm run typecheck
```

---

## 디렉토리

```
calvin-rag-chatbot/
├── api/                    FastAPI 라우트 (Presentation)
│   └── routes/             chat_v2, conversations, health, glossary, ...
├── chatbot/                대화 우선 오케스트레이터 (PR 11–16 산출물)
│   ├── domain/             frozen Pydantic — Conversation, Turn, Intent
│   ├── application/        LangGraph StateGraph + bootstrap
│   └── infrastructure/     Supabase Auth/Store, RetrievalStrategy 어댑터
├── rag_core/               RAG 엔진 (Hybrid, Agentic, KG, Vision)
├── infra/                  공통 어댑터 (PDF 로더, FAISS 캐시, usage_tracker)
├── web/                    Next.js 15 프론트
│   ├── app/                App Router 페이지
│   ├── components/         AuthGate, ChatPanel, SessionSidebar, MigrationPrompt
│   └── lib/                supabase, sessionStore, serverSessions, api
├── sql/migrations/         Postgres 스키마 (RLS 포함)
├── docs/
│   ├── prd/, trd/          요구사항·기술 명세
│   ├── me/                 의사결정 기록 (시계열)
│   ├── plans/              감사 보고서
│   ├── guides/             배포·운영 가이드
│   └── demo-questions.md   시연 시나리오 (5분 데모)
├── tests/                  pytest (LLM/DB 호출 0회 — Fake/Mock)
└── scripts/                KG 인덱싱, 데이터 준비 CLI
```

---

## 비용 (실측)

| 항목 | 비용 | 비고 |
|---|---|---|
| FAISS 임베딩 1회성 (5,657청크) | ~₩120 | 디스크 캐시 |
| KG 인덱싱 5단원 × 30청크 | ~₩52 | ~19분 |
| Hybrid 질문당 | ~₩1 | ~3초 |
| Agentic 질문당 | ~₩3 | ~5–7초 |
| KG 질문당 | ~₩2 | ~3–5초 |
| Neo4j Aura Free / 로컬 Docker | $0 | — |
| Supabase Free | $0 | conversations 1테이블 |

확장 — `python scripts/index_kg.py --full` 으로 5단원 전체 ~₩180 / 1시간.

---

## 관련 자료

- [`docs/demo-questions.md`](docs/demo-questions.md) — 5분 시연 시나리오, 모드별 강점 매핑
- [`docs/guides/deployment.md`](docs/guides/deployment.md) — HF Spaces / Vercel / Fly.io 배포 가이드
- [`docs/prd/`](docs/prd/) — 제품 요구사항 (대화 우선 설계, Supabase 영속화 4결정)
- [`docs/trd/`](docs/trd/) — 기술 요구사항 (Hexagonal, Port/Adapter)
- 학습 repo `rag-study-tracks` — 23 RAG 패턴 학습 + 파라미터 sweep + RAGAS 평가. 본 챗봇은 거기서 시작해 운영형으로 분리됐다.

---

## 데이터 / 권리

- 칼빈 강요 한국어 번역본은 출판사 저작권. 본 repo 는 *개인 학습 / 포트폴리오* 용도로만 사용하며 PDF·인덱스는 커밋하지 않는다 (`.gitignore` 보호).
- 코드 인용·기여는 사전 문의 부탁드립니다.
