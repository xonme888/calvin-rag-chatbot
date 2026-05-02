# Calvin RAG Chatbot — Next.js 프론트

`docs/me/010` Step 4 산출물. FastAPI 백엔드(`../api/`)와 통신.

## 구조

```
web/
├── app/                        Next.js 15 App Router
│   ├── layout.tsx
│   ├── page.tsx                ChatPanel 진입점
│   └── globals.css             Tailwind 기본 스타일
├── components/
│   ├── ChatPanel.tsx           메인 챗 UI (모드 셀렉터 + 메시지 + 입력)
│   ├── ModeSelector.tsx        Hybrid/Agentic/KG 토글
│   └── SourceCard.tsx          출처 청크 expander
├── lib/
│   └── api.ts                  FastAPI 클라이언트 (fetch + SSE 자체 파싱)
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.mjs
└── .env.local.example          NEXT_PUBLIC_API_BASE 설정
```

## 핵심 결정

- **`useChat` 사용 안 함** — Vercel AI SDK 의 stream protocol 호환성 검증 비용이 커서 자체 fetch + ReadableStream 파싱으로 단순화. SSE 표준 사용 (`text/event-stream`)
- **Hybrid 모드만 SSE 스트리밍** — Agentic/KG 는 sync 호출 (출력 가드 풀 패스 + 그래프 메타 전체 받기 위함)
- **모드 가용성 자동 감지** — `/modes` 응답의 `available` 따라 KG 비활성화 시 버튼 disabled

## 설치 + 실행

```bash
cd web
npm install   # 또는 pnpm install
cp .env.local.example .env.local
# (필요 시 NEXT_PUBLIC_API_BASE 수정)

npm run dev
# → http://localhost:3000
```

별도 터미널에서 FastAPI 백엔드도 띄워야:

```bash
# 다른 터미널에서
cd ..
source .venv/bin/activate
uvicorn api.main:app --port 8000
```

## 검증

```bash
npm run typecheck    # TypeScript 컴파일 검증
npm run lint         # ESLint
npm run build        # 프로덕션 빌드 (배포 전 검증)
```

## 다음 단계

- Phase 2 Step 5: Cloudflare Access 인증 (요청 헤더 자동 추가)
- Phase 2 Step 6: Vercel 배포 — `npm run build` + `vercel deploy`
