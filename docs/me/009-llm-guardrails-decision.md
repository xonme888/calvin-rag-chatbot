# 009. LLM 가드레일 — 위협 모델, 5층 방어, 단계 확장 계획

## 상황
사용자: "각 모드의 앞단 보호 장치가 없지 않나? 음란 키워드 방어, 우회/해킹 방지 등."

이 시스템은 **인터넷 공개 운영을 목표** (시연용 로컬 데모가 아님). 보안은 운영 기준으로 *지금* 결정해야 한다.

## 위협 모델 (인터넷 공개 + 익명 사용자)

실제 위협 (도메인이 좁은 신학 챗봇이라도 노출되는 부분):
1. **토큰 비용 DoS** — 익명 봇이 long-context 폭격 → OpenAI 청구서 폭주 (LLM04 Critical)
2. **Prompt Injection** — 시스템 프롬프트 leak → 무료 GPT 프록시 악용 (LLM01 High)
3. **부적절 콘텐츠 유도** → 스크린샷 평판 리스크
4. **운영 가시성 부재** — audit log 없으면 사고 후 원인 불명
5. **API key 노출** — 예외 트레이스/로그에 실수로 포함

도메인이 줄여주는 표면: 칼빈 KG 데이터 자체는 유출 가치 낮음. 시스템 프롬프트가 도메인 강제.

## OWASP LLM Top 10 매핑 (운영 기준)

| 항목 | 위협 | 우선순위 | 우리 대응 |
|---|---|---|---|
| LLM01 Prompt Injection | Yes | High | 시스템 프롬프트 + KeywordGuard(시스템 프롬프트 leak) + Phase B 정규식 패턴 |
| LLM02 Insecure Output | Maybe | Medium | `st.markdown` 만, KeywordGuard(API key 마스킹) |
| LLM04 Model DoS (비용 폭주) | **Yes** | **Critical** | LengthGuard + Phase B(Token cap, Rate limit, OpenAI hard limit) |
| LLM06 Sensitive Disclosure | Yes | Medium | KeywordGuard + Phase B(예외 sanitize) |
| LLM08 Excessive Agency | 완화 | Medium | Agent `recursion_limit=10` |
| LLM09 Overreliance | 완화 | Low | Self-RAG groundedness 토글 |
| LLM03/05/07/10 | No | Low | fine-tuning/모델 보유 안 함 |

## 핵심 설계 원칙 — 인프라 vs LLM 가드 분리

산업 조사 결과(Microsoft Copilot, GitHub Copilot, Anthropic, OpenAI):
- **1차 방어선은 인프라 레이어** (rate limit / token cap / WAF / 인증 / audit log)
- **LLM 가드 SaaS(Lakera 등 유료)는 옵션** — *비용으로 비용을 막는 역설*
- **무료 LLM 가드 (OpenAI Moderation API, Kanana Safeguard 오픈소스)는 산업 표준 보강**

→ **유료 LLM 가드 배제 = 정당. 무료 LLM 가드까지 배제 = 산업 표준에서 한 칸 부족** (보강).

## 5층 방어 (운영 공개 시)

```
L1 외곽:    Cloudflare WAF + bot fight + Access      ← Phase B
L2 입구:    LengthGuard + IP rate limit              ← A: Length / B: rate limit
L3 모델:    Token budget cap (전역/세션)             ← Phase B
L4 출구:    KeywordGuard + OpenAI Moderation         ← Phase A
L5 관측:    Audit log (질문/답변/IP/토큰/비용)       ← Phase B
```

## Phase A — 시연 가능 + Port 자산 (지금)

신규 서브패키지 `rag_core/guardrail/`:
- `port.py`: `GuardrailPort` (Protocol) + `GuardrailDecision` + `GuardrailDirection`
- `length_guard.py`: 입력 2,000자 제한 (자체)
- `keyword_guard.py`: 출력 정규식 — API key 마스킹 + 시스템 프롬프트 leak 차단 (자체)
- `openai_moderation_adapter.py`: omni-moderation-latest (무료, 다국어, fail-open)
- `chain.py`: `CompositeGuardrail` — 첫 block 단락, sanitize 누적
- `factory.py`: `get_input_guardrail()` / `get_output_guardrail()` — 환경변수 토글

통합:
- `app/calvin_chatbot.py`: 입력 가드 (chat_input 직후), 출력 가드 (RAG 답변 후)
- `app/pages/01_compare_modes.py`: 동일 적용 (3 모드 모두 출력 가드)

테스트: 24/24 PASS (LLM/네트워크 호출 0회). 누적 123/123.

## Phase B — 운영 공개 직전 (시연 후 1주, ~10시간)

| 항목 | 신규 모듈/외부 | 시간 |
|---|---|---|
| Cloudflare 프록시 + bot fight + Access | 외부 (DNS) | 1h |
| `infra/rate_limiter.py` (slowapi 또는 token bucket) | 신규 | 2h |
| `usage_tracker.py` 확장 — Token cap (전역/세션) | 기존 보강 | 3h |
| 간단 인증 (Cloudflare Access 또는 액세스 토큰) | 외부 + Streamlit | 1h |
| `infra/audit_log.py` (SQLite, 질문/답변/IP/토큰/비용) | 신규 | 2h |
| OpenAI 콘솔 hard limit ($10/일) | 외부 | 0.2h |

→ **운영 위험 80% 차단 가능**.

## 미래 확장 계획 — 사용자 규모별 어댑터 swap

> **인터페이스는 처음부터 추상화, 구현체만 사용량에 맞게 swap.** Hexagonal Port/Adapter 의 본질.

| 시점 | 사용자 | LLM 호출/일 | 권장 변화 | 코드 변경 |
|---|---|---|---|---|
| **현재 (Phase A)** | ~50명 | ~수백 | OpenAI Moderation 인라인 동기 | — |
| Phase 2 (필요 시) | 100~1,000명 | ~만 | Moderation 비동기 + placeholder fallback | factory 1줄 |
| Phase 3 (필요 시) | 10,000명+ | ~수십만 | **`KananaSafeguardAdapter` 자체 호스팅으로 swap** (한국어 최적화) | Adapter 추가만 |
| Phase 4 (엔터프라이즈) | 100,000+ | ~수백만 | Risk-based routing + 캐싱 + Edge inference (Cloudflare Workers AI) | Composite 확장 |

### Swap 트리거 — 비용 객관 결정

```
OpenAI Moderation 누적 비용 > 자체 호스팅 비용 (~$300/월)
  ⇒ KananaSafeguardAdapter 로 swap
  ⇒ factory.get_*_guardrail() 에서 어댑터 한 줄 교체
  ⇒ RAG 본체 / 챗봇 코드 0줄 변경
```

### Audit log 외부 영속 — 멀티 인스턴스 대비

Phase B의 `infra/audit_log.py`는 SQLite로 시작. 사용자 폭주 시:
- SQLite → PostgreSQL 또는 CloudWatch Logs
- `AuditLogPort` 추상화 (KG/Retriever 와 같은 사상) 후 어댑터 교체
- 단일 프로세스 → 다중 인스턴스에서도 자연 분산

### Rate limiter 외부 store — 분산 대응

Phase B는 in-memory token bucket으로 시작. 다중 인스턴스 시:
- in-memory → Redis bucket (slowapi가 둘 다 지원)
- 인스턴스 간 일관 rate limit

## 면접 어필 내러티브

> "Spring 보안은 인증·인가·SQLi 중심이지만, LLM 시스템은 **비용 자체가 공격면**입니다.
> 익명 사용자가 토큰 1만 개를 한 번에 요청하면 단일 응답이 곧 DoS입니다.
> 그래서 OWASP LLM Top 10 중 LLM04(Model DoS)를 Critical로 두고
> *외곽(Cloudflare) → 입구(LengthGuard+rate limit) → 모델(token cap) → 출구(KeywordGuard+Moderation) → 관측(audit log)* 5층으로 구성했습니다.
>
> Lakera 같은 *유료* LLM 가드는 비용으로 비용을 막는 역설이라 의도적으로 배제했고,
> Microsoft Copilot조차 Azure API Management 의 token limit + content safety 를 *인프라 레이어*에서 적용한다는 산업 사례에 정렬했습니다.
>
> 한국어 서비스 확장 시점이 오면 OpenAI Moderation 어댑터를 카카오 **Kanana Safeguard** 자체 호스팅으로 swap합니다.
> `GuardrailPort` 가 영구 인터페이스이므로 RAG 본체 코드는 0줄 변경됩니다 — Hexagonal 의 본질적 가치입니다."

자바 비교 정리표:

| 영역 | Spring 서버 | LLM RAG |
|---|---|---|
| DoS 단위 | request/sec | **token/sec, $/req** |
| Injection | SQL/XSS | Prompt Injection |
| 인증 | Spring Security | 외곽(Cloudflare) + 세션 |
| 출력 검증 | DTO 직렬화 | KeywordGuard + Moderation |
| 감사 | AccessLog | LLM I/O + cost log |
| 설계 가치 | 인터페이스 + DI | **인터페이스 + Adapter swap (사용자 규모 대응)** |

## 검증 결과
- Phase A 단위 테스트 24/24 PASS (LLM/DB 호출 0회)
- 누적 123/123 PASS
- 인터페이스 영구 자산 — Phase 2~4 swap 시 RAG 본체 변경 0
- "비용 의식" 내러티브 (docs/me/002) + "Hexagonal 가드" (이 문서) 결합 → 시니어 어필 강화

## 미래 확장 — 본 repo 안에서 직접 처리 vs 별도 에이전트

이 문서가 **미래 확장 계획의 단일 진실 원천**. 향후 작업 (Phase B, Kanana swap, Audit log 외부화 등) 시:
- 이 문서를 컨텍스트로 *명시 전달* — 별도 에이전트가 환경 가정을 잘못 잡지 않도록
- 또는 본 repo 안에서 직접 작업 — 컨텍스트 누락 위험 0
- 컨텍스트 없이 던지지 않는다 (이전 사례: "로컬 데모" 잘못된 가정으로 결론 왜곡됨)
