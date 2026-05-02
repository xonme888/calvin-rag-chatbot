# 004. 학습 repo와 production-leaning repo 분리

## 상황
한 repo에 학습/실험/챗봇이 모두 있으면:
- 의존성이 섞임 (챗봇은 Streamlit 필요, 학습은 Jupyter 필요)
- 면접관이 "챗봇 보여줘"할 때 학습 코드까지 봐야 함
- 챗봇이 학습용 트랙 코드를 import → production이 학습용 코드에 의존하는 **역방향 의존성**
- `shared/` 같은 공통 유틸이 트랙 코드에 의존하기 시작 → Hexagonal 원칙 위반

구체 사례: `app/calvin_chatbot.py` 가 `track_a_essential.ex07_agentic.main.AgenticRAG` 직접 import.

## 결정
**2 repo 분리** (3개는 과함, 1개는 너무 결합):
1. **학습 repo** (`rag-study-tracks/`): track_*, experiments, compare, shared/(공통 유틸)
2. **챗봇 repo** (`calvin-rag-chatbot/`): app, **자체 rag_core/** (필요 패턴 추려 이식)

⚠ 핵심: **챗봇 repo는 학습 repo에 import 무의존**. 같은 코드의 일부를 ‘이식’해 자체 보유.

## 근거
- 청중이 다르다 → repo가 다르다 (학습 = 본인용, 챗봇 = 면접관용)
- 의존성 그래프가 명확해야 ("이 repo는 streamlit 필요, 저건 jupyter") 면접관이 5분 안에 파악 가능
- 코드 중복은 단점이지만 챗봇은 **production용으로 docstring/토글이 정리된** 버전 — 의도된 분기
- 데이터/인덱스 캐시는 환경변수(`CALVIN_PDF_PATH`, `INDEX_DIR`)로 양 repo 공유 가능 → 디스크 절약

## 적용 방법
1. 분리 전 의존성 분석: `grep -rn "from <학습 repo>" <챗봇 코드>`
2. 챗봇 repo가 가져갈 코드 추리기 — 학습용 토글/docstring 정리, 실행 main() 제거
3. 챗봇 repo의 `pyproject.toml`은 **자기 완결적** (학습 repo 미설치 상태에서도 동작)
4. 양 repo의 README 상호 링크 (`../calvin-rag-chatbot/`)
5. 데이터/캐시는 환경변수로 경로 공유 — fallback은 자체 폴더
6. 학습 repo의 CLAUDE.md에 "**챗봇 코드 변경 금지**: 별도 repo에서 자체 RAG 코어 보유. 학습 트랙 변경이 챗봇에 자동 반영되지 않음 — 의도된 분리" 명시

## 사례
- `track_a_essential/ex02_hybrid/main.py` (학습용, Day2/3/4/5 토글 docstring) → `rag_core/hybrid.py` (챗봇용, 정리됨)
- `track_a_essential/ex07_agentic/main.py` → `rag_core/agentic.py`
- `shared/calvin_setup.py` → `rag_core/builder.py`
- 검증: `python -m pytest`로 양 repo 독립 검증 + import 검증 16/16 모듈 PASS

## 분리 비용
- 1~2일 작업 (이번 사례)
- 코드 ~1KLOC 중복
- 양 repo의 의존성 관리 분리

## 분리 효과
- 챗봇 repo가 "포트폴리오 면접관 청중용"으로 깔끔
- 학습 repo가 "트랙 비교 + 실험"에 집중
- 챗봇 의존성에 streamlit/streamlit-agraph 같은 시연 라이브러리 명시 가능 (학습 repo는 무관)
