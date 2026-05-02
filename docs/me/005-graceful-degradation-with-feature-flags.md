# 005. 외부 의존성 장애에 대한 graceful degradation

## 상황
KG 모드는 Neo4j(외부 의존성) 가동을 전제. 다음 시나리오에서 챗봇이 깨질 수 있다:
- Docker 컨테이너 정지/재시작 중
- `.env`의 `NEO4J_URI` 오타
- `.[kg]` 옵션 그룹 미설치 (langchain-neo4j 없음)
- Aura 무료 티어의 7일 미사용 자동 일시정지
- 면접 시연 도중 네트워크 끊김 / 컨테이너 죽음

기존 동작: 사용자가 KG 모드를 선택하면 `RuntimeError` 발생 → 사용자는 사이드바에서 다른 모드를 직접 선택해야 함. 면접 도중엔 매끄럽지 않음.

## 결정
**3계층 graceful degradation**:

1. **Domain 격리 (구조)**: `rag_core/hybrid`, `rag_core/agentic`, `rag_core/builder` 등 RAG 코어가 `rag_core.kg`/`langchain-neo4j`에 import 의존하지 않는다. AST 검증 테스트로 강제
2. **Feature flag (런타임)**: 챗봇 시작 시 `_check_kg_available()` (30초 캐시)로 Neo4j 연결 + 인덱싱 상태 확인. 가용 시에만 사이드바 옵션에 KG 모드 추가
3. **명확한 사유 + 복구 가이드 (UX)**: 미가용 시 정보 배너에 `Neo4j 미연결 — docker compose up -d` 같은 *실행 가능한* 한국어 안내. "Hybrid/Agentic은 영향 없이 사용 가능"도 함께 명시

## 근거
- **Hexagonal 분리의 본질적 가치를 살림**: 어댑터(Neo4j) 장애가 도메인(RAG 로직)을 깨지 않음. 이는 분리 자체로는 보장되지 않고 *런타임 fallback*까지 있어야 완성
- **면접 시연 시 안전망**: 데모 중 Docker가 죽어도 챗봇은 동작. 시연 사고 → 발표자 평정 유지
- **30초 TTL 캐시**: docker 재시작 직후 30초 안에 자동 감지 → 사용자가 새로고침만 하면 KG 모드 다시 나타남. 매 인터랙션마다 health check를 부르지 않아 응답 시간 영향 없음
- **AST 기반 의존성 테스트**: 단순 import 테스트가 아니라 *소스 코드*에서 forbidden import를 강제. 향후 누군가가 `from rag_core.kg import ...` 를 hybrid에 추가하면 CI에서 차단됨

## 적용 방법
1. **AST 검증 테스트**: 도메인 모듈 각각에 대해 forbidden 패키지 import 체크. 새 도메인 모듈 추가 시 테스트도 함께 추가
2. **헬스체크 헬퍼**: `_check_xxx_available() -> tuple[bool, str | None]` 형식. (가용성, 사유) 튜플
3. **사이드바 동적 옵션**: 모드 라디오 옵션을 가용성에 따라 동적으로 구성. 옵션을 disable하지 않고 *숨김* — 잘못된 선택 자체를 막음
4. **사유 배너**: 모드 선택 직후. 1줄 사유 + 1줄 복구 명령 + 1줄 "다른 모드는 정상 동작" 보장
5. **Mock 어댑터로 단위 테스트**: 실 외부 시스템 없이 fallback 경로를 검증

## 사례

### AST 의존성 테스트
```python
def test_hybrid_module_independent_of_kg():
    import rag_core.hybrid as hybrid_module
    src = inspect.getsource(hybrid_module)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            assert "rag_core.kg" not in mod
            assert "langchain_neo4j" not in mod
```

### 동적 사이드바
```python
kg_available, kg_reason = _check_kg_available()
mode_options = ["Hybrid", "Agentic"]
if kg_available:
    mode_options.append("Knowledge Graph")

mode = st.radio("모드", options=mode_options, index=0)

if not kg_available:
    st.info(
        f"**KG 모드 비활성화** — {kg_reason}\n\n"
        "Hybrid/Agentic은 영향 없이 사용 가능합니다."
    )
```

### Failing Mock 어댑터
```python
class FailingKGAdapter:
    def health_check(self) -> bool:
        return False
    def get_subgraph(self, names, hops=1) -> SubgraphData:
        return SubgraphData()  # 빈 결과 — UI 렌더링 보호
```

## 검증 결과
- 16/16 단위 테스트 PASS (LLM/DB 호출 0회)
- 면접 데모 중 `docker compose stop` 시: KG 모드 옵션 사라짐 + 정보 배너 + Hybrid/Agentic 즉시 사용 가능
- 복구: `docker compose up -d` 후 30초 안에 KG 모드 자동 복구

## 어필 내러티브 (면접용)
> "Port/Adapter 분리만으로는 부족합니다. 실제 graceful degradation을 위해
> (1) AST 기반 의존성 테스트로 도메인 격리를 *코드로* 강제하고,
> (2) 런타임 헬스체크로 사이드바 옵션을 동적으로 구성하며,
> (3) 사용자 사유 배너에 복구 명령까지 포함했습니다.
> 데모 중 Docker가 죽어도 챗봇은 멈추지 않습니다."
