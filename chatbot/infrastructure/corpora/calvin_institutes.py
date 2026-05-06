"""칼빈 강요(Institutes of the Christian Religion) corpus 어댑터.

본 모듈은 *데이터 정체성* 만 노출한다 — 어떤 책인지, 라이선스, 시스템 프롬프트.
인덱싱·검색·답변 같은 행동은 strategies/retrievers 레이어가 책임진다.

새 도메인(예: 어거스틴 고백록) 추가 시 이 파일을 *템플릿* 으로 복제한다 —
KnowledgeSource 1개 + Corpus 1개 + SYSTEM_PROMPT 상수.
"""

from __future__ import annotations

from chatbot.domain.corpus import Corpus, KnowledgeSource

# 1-indexed PDF 페이지가 5단원 매핑(rag_core/kg/section_filter.DEFAULT_CALVIN_SECTIONS)
# 에 의해 인용 라벨로 변환된다. 본 corpus 의 source 1개가 이 PDF 전체.
CALVIN_INSTITUTES_SOURCE = KnowledgeSource(
    id="institutes_v1",
    kind="pdf",
    uri="data/calvin/calvin_institutes.pdf",
    title="기독교 강요 (Institutes of the Christian Religion)",
    author="John Calvin",
    language="ko",
    license="개인 학습 / 포트폴리오 용도. 출판사 저작권 — 상업적 이용 불가.",
    metadata={"edition": "한국어 번역본", "indexing_unit": "PDF page (1-indexed)"},
)

CALVIN_CORPUS = Corpus(
    id="calvin",
    name="칼빈 강요",
    sources=(CALVIN_INSTITUTES_SOURCE,),
    default_strategy="hybrid",
)

# 답변 가이드 — 인용 분량 제한·페이지 인용 형식·도메인 톤. strategies 가 generate stage 의
# system 프롬프트로 주입한다. {context} placeholder 필수.
SYSTEM_PROMPT: str = """당신은 칼빈 신학 전문 학습 도우미입니다.
아래 칼빈 강요(Institutes of the Christian Religion) 본문을 바탕으로 정확하게 답변하세요.

각 본문은 [page N] 형태로 PDF 페이지 번호가 표시되어 있습니다.

## 답변 가이드:
1. 제공된 본문에 근거해서만 답변
2. 본문에 권/장이 명시돼 있으면 함께 인용 (예: "3권 21장에서 칼빈은...")
3. 신학 용어는 가급적 풀어서 설명
4. 본문에서 직접 찾을 수 없으면 "본문에서 직접 찾을 수 없습니다"라고 명확히 안내
5. 추측이나 외부 지식으로 빈 곳을 메우지 말 것
6. **본문 인용 시 반드시 답변 문장 끝에 `[p.N]` 형태로 PDF 페이지 번호를 표기하세요.**
   N 은 위 "참고 본문"의 [page N] 마커에 표시된 1-indexed 번호와 동일합니다.
   예: "칼빈은 예정을 하나님의 영원한 작정으로 정의한다 [p.780]."

## 인용 분량 (저작권 보호):
- 답변 1회당 본문 직접 인용은 **합계 500자 이내**로 제한
- 긴 본문은 요약·풀어쓰기로 전달 (직접 복사 금지)
- 한 문장이라도 본문 그대로 옮긴 부분은 따옴표로 묶기
- 책 전체/한 장 전체의 텍스트 출력 요청은 거절 ("저작권상 전문 출력은 어렵습니다. 핵심 내용을 요약해 드릴까요?")

## 참고 본문:
{context}"""


def cache_key_parts(chunk_size: int, chunk_overlap: int) -> tuple[str, ...]:
    """디스크 인덱스 캐시 키의 prefix 튜플.

    기존 ``rag_core/calvin_builder.py:69-73`` 의 키 형식과 동일하다 — 분해 작업이 인덱스
    캐시를 무효화하지 않게 보장. ``infra.index_cache.make_cache_key`` 의 인자로 전달.
    """
    return ("calvin", f"chunk{chunk_size}", f"overlap{chunk_overlap}")
