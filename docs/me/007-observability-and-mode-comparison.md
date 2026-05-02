# 007. 관측성 + 3 모드 동시 비교

## 상황
KG 모드까지 갖춘 후 챗봇은 시연 가능 상태였지만 두 가지가 부족했다:
1. **관측성 부재** — 시연 중 비용 의식을 *시각적으로* 보여줄 수 없었다. 면접관이 "한 번 시연에 얼마 들었나요?"라 물으면 추정값밖에 못 줌
2. **모드별 차이가 한 화면에 안 보임** — 같은 질문을 모드를 바꿔가며 3번 던져야 차이를 확인할 수 있었음. 시연자/관찰자 모두 cognitive load 큼

## 결정

### 관측성 — `infra/usage_tracker.py`
- LangChain `BaseCallbackHandler` 확장 (`UsageTracker`) — `on_llm_end` 에서 token usage 추출
- `SessionStats` (dataclass) — 모드별 누적 (`by_mode: dict[str, ModeStats]`)
- 모델별 단가 사전 (`MODEL_PRICING_USD`)으로 비용 자동 산출
- 사이드바에 "누적 사용 통계" expander — 매 호출 후 자동 갱신, 리셋 버튼 포함
- RAG 클래스 인터페이스 확장 (`callbacks: list | None = None`) — 챗봇이 모드별로 다른 tracker 주입

### 3 모드 동시 비교 — `rag_core/mode_dispatcher.py` + `app/pages/01_compare_modes.py`
- `concurrent.futures.ThreadPoolExecutor` 로 병렬 호출 → 응답 시간 = max(3 모드)
- KG None이면 자동 스킵 — graceful degradation
- 한 모드 실패 시 다른 모드 결과는 정상 반환 (`ModeResult.error` 필드)
- Streamlit 멀티페이지(`app/pages/`) 활용 — 사이드바에서 자동 노출
- 결과 3 column: 답변 / 메타 / 출처 / (KG는 그래프)

## 근거

### 관측성을 콜백으로 묶은 이유
- 모든 LangChain LLM 호출이 BaseCallbackHandler 의 `on_llm_end` 를 거침 → 인터페이스 변경 최소
- streaming/비-streaming 모두 동작 (LangChain v1.x ChatOpenAI 는 둘 다 token usage 보고)
- streamlit `session_state` 에 `SessionStats` 단일 인스턴스 영속 — 페이지 간 공유

### ThreadPoolExecutor를 선택한 이유
- LLM 호출은 I/O 바운드 → GIL 영향 없음
- asyncio는 RAG 클래스 전체를 async로 바꿔야 → 변경 범위 큼
- ThreadPool은 동기 코드 그대로 병렬화 — 시그니처 변경 0

### 멀티페이지로 분리한 이유
- 메인 챗봇과 비교 페이지의 *목적이 다름* — 단일 답변 vs 비교
- Streamlit 멀티페이지 규약(`app/pages/NN_*.py`) 으로 사이드바 자동 노출 → 코드 변경 0
- `session_state.usage_stats` 를 두 페이지가 자연스럽게 공유

## 적용 방법

### 새 모드 추가 시 패턴
1. `rag_core/<new_mode>.py` 작성 — `query(question, callbacks=None)` 시그니처 준수
2. `mode_dispatcher.compare_all_modes` 의 `targets` 리스트에 추가
3. `_MODE_ORDER` 에 표시 순서 등록
4. 메인 챗봇 사이드바 라디오 옵션과 비교 페이지 column에 자동 노출

### 새 콜백 추가 시 패턴
1. `infra/<new_callback>.py` 작성 — `BaseCallbackHandler` 상속
2. 챗봇/비교 페이지의 `callbacks_per_mode` dict에 주입
3. SessionStats 같은 영속 데이터가 필요하면 `session_state` 키 추가

## 사례

### Mock 기반 단위 테스트 (LLM 호출 0회)
```python
# tests/test_mode_dispatcher.py
def test_compare_runs_in_parallel():
    """3 모드 각각 0.3초 sleep — 병렬 시 ~0.3초, 직렬 시 ~0.9초."""
    h = _MockRAG("Hybrid", latency_sec=0.3)
    a = _MockRAG("Agentic", latency_sec=0.3)
    k = _MockRAG("Knowledge Graph", latency_sec=0.3)
    start = time.time()
    compare_all_modes("Q", hybrid=h, agentic=a, kg=k)
    elapsed = time.time() - start
    assert elapsed < 0.7  # 병렬 OK
```

### 사이드바 패널
```
누적 사용 통계 (8회 호출)
  Hybrid — 4회
    in 12,400 / out 1,200 토큰  ·  ₩3.0
  Agentic — 2회
    in 5,600 / out 800 토큰  ·  ₩1.6
  Knowledge Graph — 2회
    in 7,800 / out 600 토큰  ·  ₩1.7
  합계: ₩6.3 ($0.0042 · 28,400 토큰)
  [통계 리셋]
```

## 어필 내러티브

> "각 RAG 호출에 LangChain 콜백으로 토큰 사용량을 추적해 모드별 비용을 ₩으로 노출합니다.
> 그리고 같은 질문을 3 모드에 ThreadPool로 병렬 투입하는 비교 페이지를 별도 멀티페이지로 분리했습니다.
> 한 모드가 실패해도 다른 모드는 정상 반환되는 graceful degradation 구조입니다.
> Mock RAG로 병렬성/실패 격리/콜백 주입 모두 단위 테스트로 검증했습니다."

## 검증 결과
- 단위 테스트: usage_tracker 11/11 + mode_dispatcher 7/7 = 18/18
- 누적 49/49 PASS (LLM/DB 호출 0회)
- 인터페이스 확장은 모두 keyword arg 추가라 기존 호출 호환
