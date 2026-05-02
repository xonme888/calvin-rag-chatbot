# 006. 파일명/모듈명 명명 규칙

## 상황
신규 파일을 한 번에 3~4개 추가하려는 시점에, 기존 구조를 둘러보니 일관성 균열이 보였다:
- `rag_core/kg/rag.py`가 디렉토리명과 동어반복 (`kg.rag`)
- `rag_core/kg/extractor.py`가 실제로는 단원 page 필터인데 이름이 모호 (entity/triple 추출로 오해)
- `rag_core/builder.py`에 도메인 정보 없음 (`build_calvin_rag` 함수만 보면 칼빈 전용)
- `rag_core/postprocess.py`만 동사 어근, 다른 모듈은 모두 명사형
- `infra/env.py`만 단독 명사, 다른 infra 모듈은 `<대상>_<역할>` (`document_loader`, `index_cache`)

명명 일관성은 시간이 지날수록 빠르게 누적되어 가독성을 망가뜨리므로 *지금* 통일하기로 결정.

## 결정 — 6개 규칙
1. **모듈명은 명사/명사구** — 동사 어근(`postprocess`, `build`) 금지. 그 모듈에서 만들어지는 것 또는 핵심 객체로
2. **`infra/`는 `<대상>_<역할>` 패턴** — `document_loader`, `index_cache`, `env_loader`, `llm_callback`. 단독 명사 금지
3. **도메인 헬퍼는 `<domain>_<역할>` prefix** — 칼빈 전용 코드는 `calvin_builder`. 신학 도메인 외엔 도메인 식별 가능해야
4. **Hexagonal 역할 접미사 고정** — `_port.py`/`_adapter.py`/`_factory.py`/`_config.py`. 디렉토리 안에서 단일이면 prefix 생략 가능하나 두 개 이상 공존 시 prefix 필수
5. **디렉토리명과 동어반복 금지** — `kg/rag.py`, `kg/kg_*.py` 패턴 회피. 디렉토리가 이미 컨텍스트를 제공하므로 모듈명은 *구체적 책임* 을 드러내야 함
6. **Streamlit multipage는 `NN_<snake_case>.py`** — 숫자 prefix 두 자리 zero-padding + 알파벳 시작. 한국어 라벨은 코드 내 `st.set_page_config`로 분리

## 근거
- 사용자가 명시 — "깔끔하고 읽기 쉬운 코드 좋아함. 구조 난잡해질 수 있어"
- 디렉토리 구조가 이미 hexagonal로 명확하므로 (`app/`, `rag_core/`, `infra/`, `tests/`) **모듈명은 그 안에서 차이를 드러내는 책임**
- import 경로(`from rag_core.kg.pipeline import ...`)가 자연 영문 어순으로 읽혀야 함
- 동어반복(`kg.rag`)은 cognitive load 증가 — 같은 정보가 두 번

## 적용 결과 (rename)
| 이전 | 이후 |
|---|---|
| `rag_core/kg/rag.py` | `rag_core/kg/pipeline.py` |
| `rag_core/kg/extractor.py` | `rag_core/kg/section_filter.py` |
| `rag_core/kg/visualization.py` | `rag_core/kg/graph_renderer.py` |
| `rag_core/builder.py` | `rag_core/calvin_builder.py` |
| `rag_core/postprocess.py` | `rag_core/reranker.py` |
| `infra/env.py` | `infra/env_loader.py` |

신규 4개 파일도 같은 규칙 적용:
- `rag_core/kg/entity_normalizer.py`
- `infra/llm_callback.py` (관측성)
- `rag_core/mode_dispatcher.py`
- `app/pages/01_compare_modes.py`

## 적용 방법 (다음 작업에서)
- 신규 파일 추가 *전*: `find . -name '*.py'`로 기존 구조 한 번 보고 패턴 확인
- 두 개 이상 모듈을 동시 추가할 때: 별도 에이전트 감사 발사 → docs/me/NNN 기록 → 적용
- 기존 모듈에 균열이 보이면 신규 작업과 함께 일괄 정리 (분산 누적 회피)
- rename 시 import 경로 영향: `grep -rn "from <old_module>"` 로 사전 확인
