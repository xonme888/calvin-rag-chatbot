# 배포 가이드 — Hugging Face Spaces (메인) + Vercel + Fly.io (Fallback)

초대 코드 운영 단계 100% 무료 배포. 사용자 ~10~30명 가정. 모든 배포는 git push 만으로 자동.

## 아키텍처

```
사용자 브라우저
   │ HTTPS
   ▼
Vercel (web)                          ← Next.js 15, GitHub 연결 자동 배포
   │ HTTPS (CORS_ORIGINS 검증)
   │ X-Invite-Code 헤더
   ▼
Hugging Face Spaces (api, Docker)     ← FastAPI, FAISS in-memory, 인덱스 image 내 포함
   ├─→ OpenAI API
   └─→ Neo4j Aura Free (선택)         ← KG 모드
```

PDF 는 배포 image 에 포함하지 않는다. 로컬에서 1회 인덱싱 후 `indexes/` 디렉토리(~40MB) 만 image 에 COPY. `rag_core/calvin_builder.py` 의 `has_cache()` hit 분기가 PDF 로드를 자동 스킵한다.

## CI/CD 흐름

| 변경 경로 | 트리거 | 결과 |
|---|---|---|
| `web/**` | git push main | Vercel 자동 빌드 + 배포 (네이티브) |
| `api/**`, `rag_core/**`, `infra/**`, `Dockerfile`, `indexes/**` | git push main | `.github/workflows/deploy-api.yml` → HF Space mirror push → Docker 빌드 |
| 그 외 (`docs/`, `tests/`) | git push main | `test.yml` 만 실행, 배포 트리거 X |

## 사전 준비 (1회)

| 항목 | 가입 / 액션 |
|---|---|
| GitHub | repo push 권한 |
| Hugging Face | https://huggingface.co/join → Settings → Access Tokens → write 권한 토큰 발급 |
| Vercel | https://vercel.com → GitHub OAuth |
| Neo4j Aura Free (선택) | https://console.neo4j.io → Free Database, KG 시연 시만 |
| OpenAI API key | 기존 `.env` 의 `OPENAI_API_KEY` 그대로 |

## 1. 인덱스 사전 빌드 + Private Dataset push (로컬, 1회)

저작권 보호를 위해 인덱스(책 본문 청크 포함)는 image 에 포함하지 않고 **Private HF Dataset** 으로 분리한다. 부팅 시 컨테이너가 토큰으로 fetch.

### 1-1. 로컬 인덱싱

```bash
cd /Users/naseunghoo/project/4_education/python/AI/web_video/calvin-rag-chatbot
source .venv/bin/activate
python -c "from rag_core.calvin_builder import build_calvin_rag; build_calvin_rag()"

# indexes/calvin__chunk500__overlap50/{index.faiss,index.pkl} 생성 확인
ls -lh indexes/calvin__chunk500__overlap50/
```

### 1-2. Private Dataset 에 push

```bash
export HF_TOKEN=hf_xxxxxxxxx                     # 사전 준비 단계의 write 토큰
export HF_INDEX_REPO=<HF_USER>/calvin-rag-indexes
python scripts/push_index_to_hf.py
```

스크립트는 Dataset repo 가 없으면 자동으로 **Private** 으로 생성한 후 인덱스를 업로드한다. 이후 인덱스를 갱신할 때마다 같은 명령을 다시 실행.

확인: `https://huggingface.co/datasets/<HF_USER>/calvin-rag-indexes` 에서 Private 표시 + index.faiss/index.pkl 확인.

### 1-3. (참고) `.dockerignore` 가 indexes/ 를 제외하므로 image 에는 포함되지 않는다.

## 2. API 배포 — Hugging Face Spaces (메인)

### 2-1. HF Space 생성

https://huggingface.co/new-space 에서:

| 필드 | 값 |
|---|---|
| Owner | (HF 사용자명) |
| Space name | `calvin-rag-api` |
| License | mit |
| SDK | **Docker** |
| Hardware | CPU basic (free, 16GB RAM, 2 vCPU) |
| Visibility | Public (또는 Private) |

### 2-2. GitHub Secrets 등록

repo → Settings → Secrets and variables → Actions:

| Secret | 값 |
|---|---|
| `HF_TOKEN` | 사전 준비 단계에서 받은 write 토큰 |
| `HF_USER` | HF 사용자명 |
| `HF_SPACE` | `calvin-rag-api` |

### 2-3. HF Space Variables / Secrets 등록

HF Space 페이지 → Settings → Variables and secrets:

| 키 | 종류 | 값 |
|---|---|---|
| `OPENAI_API_KEY` | Secret | 운영 키 |
| `HF_TOKEN` | Secret | 1-2 단계의 토큰 (Private Dataset 접근) |
| `HF_INDEX_REPO` | Variable | `<HF_USER>/calvin-rag-indexes` (1-2 에서 push 한 Dataset) |
| `INVITE_CODES` | Variable | `portfolio2026,interview-abc,...` |
| `CORS_ORIGINS` | Variable | (Vercel 배포 후 갱신) `https://<your-app>.vercel.app` |
| `VISION_ENABLED` | Variable | `true` |
| `BUDGET_FREE_CAP` | Variable | `10000` |
| `DAILY_TOKEN_CAP` | Variable | `200000` |
| `LOG_SINK` | Variable | `stdout` |
| `NEO4J_URI` | Secret | (선택) `neo4j+s://xxxxx.databases.neo4j.io` |
| `NEO4J_USERNAME` | Secret | (선택) `neo4j` |
| `NEO4J_PASSWORD` | Secret | (선택) Aura 비번 |

> `HF_TOKEN` + `HF_INDEX_REPO` 두 변수가 모두 있어야 부팅 시 Dataset fetch 가 동작한다. 누락되면 컨테이너가 인덱스 없이 시작해 첫 질문에서 PDF 부재 에러가 발생한다.

### 2-4. 첫 배포 (git push)

```bash
git add .
git commit -m "feat: HF Spaces 배포 지원"
git push origin main
```

`.github/workflows/deploy-api.yml` 이 자동으로 HF Space repo 에 mirror push → HF 가 docker build 시작 (5~10 분).

진행 상황: HF Space 페이지 → Logs 탭 (Building → Running).

### 2-5. health check

```bash
curl https://<HF_USER>-calvin-rag-api.hf.space/health/live
# {"status":"alive"}

curl https://<HF_USER>-calvin-rag-api.hf.space/health/ready | jq
# 의존성 ping (openai 등)
```

## 3. Web 배포 — Vercel

### 3-1. Vercel 프로젝트 연결

1. Vercel 대시보드 → **Add New** → **Project**
2. GitHub repo (`calvin-rag-chatbot`) 선택
3. **Root Directory** = `web` 지정
4. Framework Preset = Next.js (자동 감지)

### 3-2. 환경변수

Vercel 대시보드 → Project Settings → Environment Variables:

| 변수 | 값 | Environment |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://<HF_USER>-calvin-rag-api.hf.space` | Production + Preview |

### 3-3. 배포

push 하면 자동 배포. preview URL 발급. Production 도메인 (예: `calvin-rag-chatbot-web.vercel.app`) 확정.

### 3-4. CORS 갱신

HF Space Settings → `CORS_ORIGINS` = `https://calvin-rag-chatbot-web.vercel.app` 으로 수정 → Space 자동 재시작 (~30초).

## 4. Neo4j Aura Free (선택, KG 시연 시)

### 4-1. 인스턴스 생성

https://console.neo4j.io → New Instance → Free → 비번 다운로드 (1회만 가능).

### 4-2. KG 인덱싱 (로컬에서 1회)

```bash
NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io \
NEO4J_USERNAME=neo4j \
NEO4J_PASSWORD=... \
python scripts/index_kg.py --balanced 30 --no-confirm
```

비용 ~$0.18 (1회). 200K 노드 한도 안에 들어옴 (5단원 ~수백 노드).

### 4-3. HF Space Secrets 갱신

Settings → `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` 추가 → Space 재시작.

## 5. 검증 체크리스트

### API
- [ ] `curl https://<HF_USER>-calvin-rag-api.hf.space/health/live` → 200
- [ ] `curl .../health/ready` → 의존성 ping 결과
- [ ] `curl .../modes` → kg.available 확인 (Aura 활성 시 true)
- [ ] `curl -X POST .../invite/verify -d '{"code":"portfolio2026"}'` → 200

### Web
- [ ] Vercel URL 접속 → 초대 코드 입력 화면
- [ ] 코드 입력 → 채팅 화면 진입
- [ ] 첫 답변 정상 수신 (skeleton → fade-in)
- [ ] 사이드패널 → 글로서리 60개 + KG graph (활성 시)
- [ ] DevTools Network → CORS 에러 없음

### 보안
- [ ] `/robots.txt` → `Disallow: /`
- [ ] `/terms` `/privacy` `/license` 페이지 정상
- [ ] 초대 코드 없는 요청 → 401

## 6. 운영 모니터링

### 부팅 로그

HF Space → Logs 탭. 다음 라인 확인:

```
[boot] .env loaded=False ... INVITE_CODES count=3 INDEX_DIR=/app/indexes
[boot] CORS allow_origins=['https://...'] credentials=True
캐시에서 인덱스 로드: /app/indexes/calvin__chunk500__overlap50
```

`load_calvin()` 호출 로그가 없어야 정상 (PDF 의존성 제거 검증).

### audit_log

HF Spaces 의 컨테이너 파일시스템은 재시작 시 ephemeral. SQLite 의 `~/.calvin-rag-chatbot/audit.db` 는 컨테이너 수명 동안만 유지됨. 영구 저장이 필요하면 Turso 등 외부 백엔드로 swap (`AUDIT_BACKEND=turso` — 별도 어댑터 필요).

시연 단계엔 `LOG_SINK=stdout` 만으로 갈음 — Logs 탭에서 검색 가능.

### 비용 추적
- OpenAI 대시보드 → Usage
- HF Spaces: 무료 (CPU basic) — 비용 추적 불필요
- Vercel: Hobby 플랜 무료, 1TB 대역폭 한도 모니터링

## 7. 비용 추정 (월)

| 항목 | USD/월 | KRW/월 |
|---|---|---|
| HF Spaces CPU basic | $0 | ₩0 |
| Vercel Hobby | $0 | ₩0 |
| Neo4j Aura Free | $0 | ₩0 |
| OpenAI (10명 × 5질문/일 × 2K 토큰, gpt-4o-mini) | $5~15 | ₩7,500~22,500 |
| **합계** | **$5~15** | **₩7,500~22,500** |

3개월 면접 시즌 총 ~₩30,000~70,000.

## 8. 롤백 / 종료

긴급 차단 (저작권 분쟁 등):
```
HF Space Settings → INVITE_CODES = (빈 값) → Save
→ 모든 사용자 401 (24h 응답 약속 충족)
```

영구 종료:
- HF Space → Settings → Delete this Space
- Vercel → Project Settings → Delete Project
- Neo4j Aura → Pause / Delete

## 9. Fallback — Fly.io 배포

HF Spaces latency 가 거슬릴 때 (한국 사용자, ~150ms RTT) 또는 동시성 한계 도달 시 사용.

### 9-1. 사전 준비

```bash
brew install flyctl
fly auth signup       # 신용카드 등록 필요
```

GitHub Secrets:
| Secret | 값 |
|---|---|
| `FLY_API_TOKEN` | `fly tokens create deploy` 출력 |

### 9-2. 첫 배포

```bash
fly launch --no-deploy   # 기존 fly.toml 사용
fly volumes create calvin_data --region nrt --size 1
fly secrets set \
  OPENAI_API_KEY=sk-... \
  INVITE_CODES=portfolio2026,demo-friend \
  CORS_ORIGINS=https://your-app.vercel.app \
  VISION_ENABLED=true
fly deploy
```

### 9-3. CI/CD

`.github/workflows/deploy-api-fly.yml` 가 이미 준비됨. Actions 탭 → **deploy-api-fly** → **Run workflow** (수동 트리거).

또는 `deploy-fly` 브랜치에 push 시 자동.

### 9-4. 비용

- shared-cpu-1x@1024MB 24시간 = ~$1.94/월
- volume 1GB = $0.15/월
- auto_stop_machines true → 비활성 시 0 머신 (cold start 5~10초)
- 합계 월 $0.5~5 (사용량 따라)

### 9-5. Vercel 환경변수 전환

`NEXT_PUBLIC_API_BASE` = `https://calvin-rag-api.fly.dev` 로 변경 → 자동 재배포.

## 10. 위험 / 알려진 한계

| 호스팅 | 한계 | 대응 |
|---|---|---|
| HF Spaces (free) | 미국 서버 ~150ms RTT, 동시성 ~5 | Fly.io fallback 으로 1줄 변경 전환 |
| HF Spaces (free) | 컨테이너 재시작 시 ephemeral | audit_log 외부 백엔드 또는 stdout 로깅 |
| Vercel Hobby | "Commercial use 금지" 약관 | 포트폴리오 / 면접 용도 (회색 지대 — 일반 허용) |
| Neo4j Aura Free | 1주 비활성 시 paused | 시연 전날 ping 으로 깨우기 |
| OpenAI | 사용량 폭증 시 청구 | `BUDGET_FREE_CAP` / `DAILY_TOKEN_CAP` 가드 |

## 11. 최초 배포 후 자동화 흐름 정리

이 시점부터 모든 변경은 git push 만으로 배포된다:

| 변경 | 명령 | 시간 |
|---|---|---|
| 시스템 프롬프트 수정 | `git push origin main` | ~7분 (HF 빌드) |
| Web UI 수정 | `git push origin main` | ~2분 (Vercel) |
| 환경변수 추가 | HF/Vercel 대시보드 클릭 | ~30초 |
| 인덱스 재빌드 | `build_calvin_rag()` + `python scripts/push_index_to_hf.py` + HF Space restart | ~12분 |
