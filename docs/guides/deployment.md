# 배포 가이드 — Vercel + Fly.io

초대 코드 운영 단계 배포. 사용자 ~10~30명 가정.

## 아키텍처

```
사용자 브라우저
   │ HTTPS
   ▼
Vercel (web)              ← Next.js 15, 정적 + SSR
   │ HTTPS (CORS_ORIGINS 검증)
   │ X-Invite-Code 헤더
   ▼
Fly.io (api)              ← FastAPI, FAISS in-memory, audit_log SQLite (volume)
   ├─→ OpenAI API
   └─→ Neo4j Aura Free    ← (선택) KG 모드
```

## 사전 준비

| 항목 | 가입 / 액션 |
|---|---|
| Vercel | https://vercel.com — GitHub 연결 무료 |
| Fly.io | https://fly.io — flyctl 설치 + `fly auth login` |
| Neo4j Aura Free (선택) | https://console.neo4j.io — KG 시연 시만 |
| OpenAI API key | 기존 .env 의 `OPENAI_API_KEY` 그대로 |

## 1. API 배포 (Fly.io)

### 1-1. Fly 앱 생성

```bash
cd /Users/naseunghoo/project/4_education/python/AI/web_video/calvin-rag-chatbot
fly launch --no-deploy
# 프롬프트:
#   App Name: calvin-rag-api (또는 본인 이름)
#   Region: nrt (Tokyo)
#   PostgreSQL? No
#   Redis? No
#   Deploy now? No
```

생성된 `fly.toml` 의 `app` 이름을 본인 것으로 수정 (이미 만들어둔 템플릿 위에 덮어쓰기 됨 → git diff 로 확인).

### 1-2. PDF 업로드 (volume 사용)

저작권상 git 추적 X — Fly volume 에 직접 SCP 또는 `fly ssh sftp`:

```bash
# volume 생성 (mounts.source = "calvin_data" 와 일치)
fly volumes create calvin_data --region nrt --size 1

# PDF 업로드 (1차 배포 후)
fly ssh sftp shell
> put /Users/naseunghoo/project/4_education/python/AI/web_video/rag-study-tracks/data/calvin/calvin_institutes.pdf /app/data/calvin/calvin_institutes.pdf
> exit
```

### 1-3. 환경변수 (secrets) 주입

```bash
fly secrets set \
  OPENAI_API_KEY=sk-... \
  INVITE_CODES=portfolio2026,demo-friend,interview-abc \
  CORS_ORIGINS=https://your-vercel-app.vercel.app \
  VISION_ENABLED=true

# (선택) KG 사용 시
fly secrets set \
  NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io \
  NEO4J_USERNAME=neo4j \
  NEO4J_PASSWORD=...

# (선택) 알림
fly secrets set SENTRY_DSN=https://...
```

### 1-4. 배포

```bash
fly deploy
```

배포 후 health check:

```bash
fly logs                  # 부팅 로그 (CORS / INVITE_CODES count 확인)
curl https://calvin-rag-api.fly.dev/health/ready | jq
```

## 2. Web 배포 (Vercel)

### 2-1. Vercel 프로젝트 생성

```bash
cd web
npx vercel  # 또는 GitHub 연결
```

또는 Vercel 웹 대시보드에서 GitHub 저장소 import → `web/` 디렉토리를 root 로 지정.

### 2-2. 환경변수

Vercel 대시보드 → Project Settings → Environment Variables:

| 변수 | 값 |
|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://calvin-rag-api.fly.dev` (1-1 의 fly 도메인) |

Production / Preview 모두 적용.

### 2-3. 배포 + Fly CORS 갱신

Vercel 배포 도메인 (예: `https://calvin-rag-chatbot-web.vercel.app`) 확정 후:

```bash
fly secrets set CORS_ORIGINS=https://calvin-rag-chatbot-web.vercel.app
fly deploy   # 또는 secrets set 만으로 재시작
```

## 3. Neo4j Aura Free (선택, KG 시연 시)

### 3-1. 인스턴스 생성

https://console.neo4j.io → New Instance → Free → 비번 다운로드 (1회만 가능).

### 3-2. KG 인덱싱

로컬에서 한 번 인덱싱 후 Aura 로 push:

```bash
# 로컬 .env 의 NEO4J_URI 를 Aura URI 로 임시 변경
NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io \
NEO4J_USERNAME=neo4j \
NEO4J_PASSWORD=... \
python scripts/index_kg.py --balanced 30 --no-confirm
```

비용 약 $0.18 (1회). 200K 노드 한도 안에 들어옴 (5단원 ~수백 노드).

### 3-3. Fly secrets 갱신

```bash
fly secrets set \
  NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io \
  NEO4J_USERNAME=neo4j \
  NEO4J_PASSWORD=...
```

## 4. 검증 체크리스트

### API
- [ ] `curl https://api/health/live` → 200
- [ ] `curl https://api/health/ready` → 의존성 ping (openai/neo4j/supabase)
- [ ] `curl https://api/modes` → kg.available 확인 (Aura 활성 시 true)
- [ ] `curl -X POST https://api/invite/verify -d '{"code":"portfolio2026"}'` → 200

### Web
- [ ] Vercel URL 접속 → 초대 코드 입력 화면
- [ ] 코드 입력 → 채팅 화면 진입
- [ ] 첫 답변 정상 수신 (skeleton → fade-in)
- [ ] 사이드패널 (📖) → 글로서리 60개 + KG graph (활성 시)
- [ ] DevTools Network → CORS 에러 없음

### 보안
- [ ] `/robots.txt` → `Disallow: /`
- [ ] `/terms` `/privacy` `/license` 페이지 정상
- [ ] 초대 코드 없는 요청 → 401
- [ ] `Cmd+R` 강력 새로고침 — meta robots noindex 확인

## 5. 운영 모니터링

### 부팅 로그
```
[boot] .env loaded=False ... INVITE_CODES count=3 CALVIN_PDF_PATH=...
[boot] CORS allow_origins=['https://...'] credentials=True
```

### audit_log 조회
```bash
fly ssh console -C "sqlite3 /root/.calvin-rag-chatbot/audit.db \
  'SELECT timestamp, ip, mode, invite_code, tokens_in+tokens_out AS tokens FROM audit_log ORDER BY id DESC LIMIT 20;'"
```

### 비용 추적
- OpenAI 대시보드 → Usage
- Fly.io 대시보드 → Free tier ($5 credit) 안에 들어가는지

### 알림 (선택)
- Sentry DSN 설정 시 5xx / 의존성 다운 자동 알림
- Slack webhook 설정 시 circuit breaker open 알림

## 6. 비용 추정 (월)

| 항목 | 월 |
|---|---|
| Fly.io shared-cpu-1024MB + 1GB volume | ~$2~5 (Free credit $5 흡수 가능) |
| Vercel Hobby | $0 (개인 프로젝트 무료) |
| Neo4j Aura Free | $0 (200K 노드, 50K 관계 한도) |
| OpenAI (사용자 30명 × 일 5질문 × 2K 토큰) | ~$10~30 |
| **합계** | **약 $10~35 / 월** |

## 7. 롤백 / 종료

```bash
# 일시 중단 (요금 0)
fly scale count 0

# 영구 종료
fly apps destroy calvin-rag-api
fly volumes destroy calvin_data
# Vercel: 대시보드 → Settings → Delete Project
# Neo4j Aura: 대시보드 → Pause/Destroy
```

저작권 분쟁 등 긴급 차단 필요 시:

```bash
fly secrets set INVITE_CODES=
fly deploy
# → 모든 사용자 401 → 자동 종료 (24h 응답 약속 충족)
```
