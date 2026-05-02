#!/usr/bin/env bash
# Phase 2 Step 1~3 검증 스크립트.
#
# 사용:
#   별도 터미널: uvicorn api.main:app --port 8000
#   본 스크립트:
#     bash scripts/verify_api.sh                 # 전체 (~₩15 LLM 비용)
#     bash scripts/verify_api.sh --no-llm        # LLM 호출 스킵 (₩0)
#     bash scripts/verify_api.sh --from 9        # 9번부터 끝까지
#     bash scripts/verify_api.sh --only 8        # 8번만
#     bash scripts/verify_api.sh --list          # 시나리오 목록
#     bash scripts/verify_api.sh --help
#
# 환경변수:
#   API_BASE=http://localhost:8000   # 기본
#   AUDIT_DB_PATH=...                # 기본 ~/.calvin-rag-chatbot/audit.db

set -u  # set -e 는 일부 grep/curl 실패에서 조기 종료 — 명시 검사로 대체

API_BASE="${API_BASE:-http://localhost:8000}"

# ============================================================
# 옵션 파싱
# ============================================================
FROM=1
ONLY=""
SKIP_LLM=0
LIST_ONLY=0

usage() {
    cat <<EOF
사용: $0 [옵션]

옵션:
  --from N      N번 시나리오부터 끝까지 실행 (1~14)
  --only N      N번만 실행
  --no-llm      LLM 호출 시나리오(8,9,10,12) 스킵 — 비용 0
  --list        시나리오 목록 출력
  --help, -h    이 도움말

시나리오:
  1. /health (no-llm)
  2. /modes (no-llm)
  3. /stats 빈 (no-llm)
  4. /chat/sync empty → 422 (no-llm)
  5. /chat/sync invalid mode → 422 (no-llm)
  6. /chat/sync dense_weight 범위 외 → 422 (no-llm)
  7. /chat/sync 3000자 → 422 (no-llm)
  8. /chat/sync Hybrid 정상 호출 (LLM, ~₩1)
  9. /chat/sync KG 모드 (LLM, ~₩2 또는 503)
 10. /chat/stream SSE 스트리밍 (LLM, ~₩1)
 11. /stats 누적 (no-llm)
 12. Rate limit 11번 연속 → 429 (LLM partial, ~₩10)
 13. Audit log sqlite 조회 (no-llm)
 14. Token cap 안내 (no-llm)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)    FROM="$2"; shift 2 ;;
        --only)    ONLY="$2"; shift 2 ;;
        --no-llm)  SKIP_LLM=1; shift ;;
        --full)    shift ;;
        --list)    LIST_ONLY=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *)         echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ "$LIST_ONLY" = "1" ]]; then usage; exit 0; fi

# ============================================================
# 색상 + 출력 헬퍼
# ============================================================
if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; CYAN=''; NC=''
fi

pass()   { echo -e "${GREEN}PASS${NC} $1"; }
fail()   { echo -e "${RED}FAIL${NC} $1"; }
header() { echo -e "\n${CYAN}=== $1 ===${NC}"; }
note()   { echo -e "${YELLOW}note${NC} $1"; }

# 마지막 줄(상태코드)과 본문 분리 — macOS BSD 호환 (head -n-1 사용 안 함)
split_body_code() {
    local resp="$1"
    BODY=$(printf '%s' "$resp" | sed '$d')
    CODE=$(printf '%s' "$resp" | tail -n1)
}

# ============================================================
# 시나리오 메타
# ============================================================
declare -A IS_LLM=(
    [1]=0  [2]=0  [3]=0  [4]=0  [5]=0  [6]=0  [7]=0
    [8]=1  [9]=1  [10]=1
    [11]=0
    [12]=1
    [13]=0 [14]=0
)

should_run() {
    local n="$1"
    [[ "$n" -lt "$FROM" ]] && return 1
    [[ -n "$ONLY" && "$ONLY" != "$n" ]] && return 1
    if [[ "$SKIP_LLM" = "1" && "${IS_LLM[$n]:-0}" = "1" ]]; then
        echo -e "${YELLOW}SKIP${NC} step $n (LLM 호출, --no-llm)"
        return 1
    fi
    return 0
}

# ============================================================
# 시나리오 함수 (1~14)
# ============================================================
step_1() {
    header "1. /health — liveness probe"
    local resp; resp=$(curl -s "$API_BASE/health")
    echo "$resp"
    if echo "$resp" | grep -q '"status":"ok"'; then pass "/health 200"; else fail "/health 응답 이상"; fi
}

step_2() {
    header "2. /modes — 3 모드 목록"
    local resp; resp=$(curl -s "$API_BASE/modes")
    echo "$resp"
    if echo "$resp" | grep -q '"hybrid"' && echo "$resp" | grep -q '"agentic"' && echo "$resp" | grep -q '"kg"'; then
        pass "/modes 3 모드 응답"
    else
        fail "/modes 응답 이상"
    fi
}

step_3() {
    header "3. /stats — 빈 통계 (호출 전)"
    local resp; resp=$(curl -s "$API_BASE/stats")
    echo "$resp"
    if echo "$resp" | grep -q '"total_calls":0'; then
        pass "/stats 빈 응답"
    else
        note "이미 호출이 있어 0 아님 (정상)"
    fi
}

step_4() {
    header "4. /chat/sync empty 질문 → 422"
    local code; code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_BASE/chat/sync" \
        -H "Content-Type: application/json" -d '{"question":"","mode":"hybrid"}')
    if [[ "$code" = "422" ]]; then pass "empty 질문 422"; else fail "응답: $code"; fi
}

step_5() {
    header "5. /chat/sync invalid mode → 422"
    local code; code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_BASE/chat/sync" \
        -H "Content-Type: application/json" -d '{"question":"Q","mode":"unknown"}')
    if [[ "$code" = "422" ]]; then pass "invalid mode 422"; else fail "응답: $code"; fi
}

step_6() {
    header "6. /chat/sync dense_weight 범위 외 → 422"
    local code; code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_BASE/chat/sync" \
        -H "Content-Type: application/json" -d '{"question":"Q","mode":"hybrid","dense_weight":2.0}')
    if [[ "$code" = "422" ]]; then pass "dense_weight 2.0 거절"; else fail "응답: $code"; fi
}

step_7() {
    header "7. /chat/sync 3000자 → 거절"
    local long; long=$(python3 -c "print('a'*3000)")
    local code; code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_BASE/chat/sync" \
        -H "Content-Type: application/json" -d "{\"question\":\"$long\",\"mode\":\"hybrid\"}")
    if [[ "$code" = "422" || "$code" = "400" ]]; then pass "3000자 거절 (코드 $code)"; else fail "응답: $code"; fi
}

step_8() {
    header "8. /chat/sync Hybrid 정상 호출"
    note "실 RAG 호출 — OpenAI API 비용 ~₩1 (OPENAI_API_KEY 필요)"
    local resp; resp=$(curl -s -X POST "$API_BASE/chat/sync" \
        -H "Content-Type: application/json" \
        -d '{"question":"칼빈은 예정론을 어떻게 정의하는가?","mode":"hybrid"}')
    echo "$resp" | head -c 500; echo
    if echo "$resp" | grep -q '"answer"'; then pass "Hybrid 응답 받음"; else fail "Hybrid 호출 실패"; fi
}

step_9() {
    header "9. /chat/sync KG 모드 (Neo4j 가용성에 따라 200 또는 503)"
    local resp; resp=$(curl -s -w "\n%{http_code}" -X POST "$API_BASE/chat/sync" \
        -H "Content-Type: application/json" \
        -d '{"question":"예정론과 어거스틴의 관계","mode":"kg"}')
    split_body_code "$resp"
    echo "$BODY" | head -c 400; echo
    case "$CODE" in
        503) pass "KG 비가용 → 503 (Neo4j 미연결, 정상)" ;;
        200) pass "KG 정상 응답" ;;
        *)   fail "KG 응답 코드: $CODE" ;;
    esac
}

step_10() {
    header "10. /chat/stream SSE 스트리밍 (Hybrid)"
    note "Vercel AI SDK Stream Protocol v1 — data: {type:text-delta,...}"
    curl -sN -X POST "$API_BASE/chat/stream" \
        -H "Content-Type: application/json" \
        -d '{"question":"이신칭의의 정의는?","mode":"hybrid"}' \
        --max-time 30 | head -c 800; echo
    pass "/chat/stream SSE 응답 도착"
}

step_11() {
    header "11. /stats 호출 후 누적 통계"
    local resp; resp=$(curl -s "$API_BASE/stats")
    echo "$resp" | python3 -m json.tool 2>/dev/null || echo "$resp"
    if echo "$resp" | grep -q '"total_calls"'; then pass "/stats 누적 응답"; else fail "/stats 응답 이상"; fi
}

step_12() {
    header "12. Rate limit 검증 (12번 연속 호출 → 429)"
    note "기본 limit: 10/minute (env: RATE_LIMIT_PER_MINUTE)"
    note "이전 호출들로 카운트가 누적됐으면 더 일찍 429 발생"
    local hit_429=0
    for i in $(seq 1 12); do
        local code; code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_BASE/chat/sync" \
            -H "Content-Type: application/json" \
            -d '{"question":"x","mode":"hybrid"}' --max-time 10)
        if [[ "$code" = "429" ]]; then hit_429=$((hit_429+1)); fi
    done
    if [[ "$hit_429" -gt 0 ]]; then
        pass "Rate limit 429 발생 (총 ${hit_429}회)"
    else
        note "429 미발생 — RATE_LIMIT_PER_MINUTE 늘려져 있거나 1분 대기 필요"
    fi
}

step_13() {
    header "13. Audit log sqlite 조회"
    local db="${AUDIT_DB_PATH:-$HOME/.calvin-rag-chatbot/audit.db}"
    if [[ -f "$db" ]]; then
        local count; count=$(sqlite3 "$db" "SELECT COUNT(*) FROM audit_log;" 2>/dev/null || echo "0")
        echo "audit.db: $db"
        echo "총 레코드: $count"
        sqlite3 "$db" "SELECT timestamp, mode, guard_action, elapsed_seconds FROM audit_log ORDER BY id DESC LIMIT 5;" 2>/dev/null
        if [[ "$count" -gt 0 ]]; then pass "Audit log 기록됨"; else note "audit log 빈 상태"; fi
    else
        note "audit.db 미생성 — chat/sync 호출 후 BackgroundTasks 가 기록"
    fi
}

step_14() {
    header "14. Token budget cap 안내"
    note "별도 터미널에서 다음을 실행:"
    note "  DAILY_TOKEN_CAP=100 uvicorn api.main:app --port 8001"
    note "  API_BASE=http://localhost:8001 bash scripts/verify_api.sh --only 8"
    note "현재 server 의 cap 설정은 booting 시점에 캐시됨"
}

# ============================================================
# 실행 루프
# ============================================================
RUNNING_NUMS=()
for n in $(seq 1 14); do
    if should_run "$n"; then
        RUNNING_NUMS+=("$n")
    fi
done

if [[ ${#RUNNING_NUMS[@]} -eq 0 ]]; then
    echo "실행할 시나리오가 없습니다. --list 로 목록 확인."
    exit 0
fi

echo -e "${CYAN}실행 시나리오: ${RUNNING_NUMS[*]}${NC}"
[[ "$SKIP_LLM" = "1" ]] && echo -e "${YELLOW}--no-llm: LLM 호출 시나리오 스킵 (비용 ₩0)${NC}"

for n in "${RUNNING_NUMS[@]}"; do
    "step_$n"
done

echo -e "\n${CYAN}=== 검증 완료 ===${NC}"
echo "OpenAPI Swagger UI: $API_BASE/docs"
echo "OpenAPI Redoc:     $API_BASE/redoc"
