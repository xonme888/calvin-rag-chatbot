# 003. Port/Adapter + Config 분기 (환경 추상화)

## 상황
같은 외부 시스템(Neo4j)을 환경별로 다르게 호스팅한다 (로컬 Docker / 클라우드 Aura). 두 환경의 코드 차이는 90%가 *동일* — URI scheme(`bolt://` vs `neo4j+s://`)과 SSL 옵션 정도.

## 결정
**Port 1개 + Adapter 1개 + Config 분기**.

```
KnowledgeGraphPort (Protocol)        ← 도메인 인터페이스
    ↑
Neo4jAdapter (단일 구현)              ← 환경 무관
    ↑
Neo4jConfig.mode (자동 감지)          ← URI scheme으로 local/aura 분기
```

설계 옵션 비교:
| 옵션 | 설명 | 평가 |
|---|---|---|
| (A) 단순 환경변수 토글 | URI만 다름, 코드 0줄 | 어필 약함 |
| (B) Port + Adapter 2개 (LocalAdapter, AuraAdapter) | 두 어댑터가 90% 동일 | 과한 분리 |
| **(C) Port + Adapter 1개 + Config 분기** ★ | 차이는 Config로, 인터페이스는 살림 | 적정 |
| (D) Port + Neo4j/NetworkX/FalkorDB 다중 | 미래 확장 풍부 | 야크 셰이빙 |

## 근거
- **Mock 어댑터로 단위 테스트 가능** — 실제 DB/LLM 호출 0회로 RAG 로직 검증
- Spring AI의 `VectorStore` 인터페이스 + 구현체 분리와 동일 사상 (자바 백그라운드 어필)
- 환경 차이가 작을 때 Adapter를 둘로 쪼개면 중복 코드 발생 → Config 분기가 더 깔끔
- 미래 확장(NetworkX, FalkorDB 등)은 Adapter 추가만으로 가능 — Port 정의 자체는 미래 옵션을 열어둠

## 적용 방법
1. Port를 `Protocol` 또는 ABC로 정의 (런타임 isinstance 가능)
2. Adapter 단일 클래스, 환경 차이는 `Config.mode` 프로퍼티로 분기
3. `Config.from_env()` 자동 감지 (예: URI scheme)
4. `factory.get_*_adapter()` 싱글톤 + `reset_adapter_cache()` 테스트 헬퍼 함께 제공
5. **Mock Adapter는 별도 파일** (인메모리 구현, Port 만족) — 단위 테스트 + 의존성 미설치 환경 fallback
6. 환경 전환은 `.env` 한 줄 변경으로 — 코드 무수정

## 사례
```python
# rag_core/kg/config.py
class Neo4jConfig(BaseSettings):
    uri: str

    @property
    def mode(self) -> Literal["local", "aura"]:
        return "aura" if self.uri.startswith("neo4j+s://") else "local"

# rag_core/kg/factory.py
@lru_cache
def get_kg_adapter() -> KnowledgeGraphPort:
    return Neo4jAdapter(Neo4jConfig())

# tests/test_kg_port.py
class InMemoryKGAdapter:  # Port 구현, LLM/DB 무관
    def health_check(self) -> bool: return True
    ...
```

테스트 결과: **6/6 PASS, LLM/DB 호출 0회**.

## 어필 내러티브 (면접용)
> "KG 백엔드를 `KnowledgeGraphPort`로 추상화해 로컬 Docker / Neo4j Aura를 동일 인터페이스로 처리합니다.
> Hexagonal 원칙을 따라 RAG 도메인 로직은 어댑터에 의존하지 않으며, Mock 어댑터로 단위 테스트가 가능합니다.
> Spring AI의 `VectorStore` 인터페이스와 동일 사상입니다."
