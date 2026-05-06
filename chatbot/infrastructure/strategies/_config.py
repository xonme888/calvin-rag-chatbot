"""Strategy 별 런타임 옵션 모음. 알고리즘 노브만 — LLM 모델/retriever 같은 *주입 인자* 는 제외.

본 파일에 다른 strategy 의 config 도 합류 가능 (Agentic/KG/Vision). 각 dataclass 는
서로 독립이고, 호환 필드는 *공유하지 않는다* — 단일 책임 유지.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HybridStrategyConfig:
    """Hybrid 전략의 노브."""

    top_k: int = 5
    reranker_enabled: bool = False
    reranker_top_k: int = 5
    self_rag_enabled: bool = False
    max_self_rag_retries: int = 1
    label: str = "Hybrid"
    pattern_name: str = "Hybrid RAG"


@dataclass
class KGStrategyConfig:
    """KG 전략의 노브."""

    top_k: int = 5
    subgraph_hops: int = 1
    label: str = "Knowledge Graph"
    pattern_name: str = "Knowledge Graph RAG"
    system_prompt: str = (
        "당신은 칼빈 신학 전문 학습 도우미입니다.\n"
        "아래 두 가지 정보를 결합해 답변하세요:\n\n"
        "## 1) 지식 그래프 (개념/인물 관계)\n"
        "{graph_text}\n\n"
        "## 2) 칼빈 강요 본문 발췌 (검증된 출처)\n"
        "{chunk_text}\n\n"
        "## 답변 가이드:\n"
        "1. 그래프 관계가 직접적인 답을 줄 때는 그것을 우선 활용 "
        '(예: "어거스틴이 영향을 준 개념")\n'
        "2. 본문 발췌로 구체 근거를 인용 (페이지 번호 포함)\n"
        "3. 그래프 관계와 본문이 모순되면 본문을 우선\n"
        '4. 본문에서 직접 찾을 수 없으면 "본문에서 직접 찾을 수 없습니다"라고 명확히 안내\n'
        "5. 핵심 인물/개념을 답변에 명시 (시각화에 활용됨)\n"
        "6. 본문 인용 시 반드시 답변 문장 끝에 `[p.N]` 형태로 PDF 페이지 번호를 표기하세요.\n"
        '   N 은 위 "본문 발췌"의 [page N] 마커 숫자입니다.\n'
        '   예: "칼빈은 예정을 하나님의 영원한 작정으로 정의한다 [p.780]."'
    )


@dataclass
class VisionStrategyConfig:
    """Vision 전략의 노브 — 첨부 검증 / corpus 검색 통합 / 비활성화 게이트."""

    label: str = "Vision"
    pattern_name: str = "Vision"
    enabled_env_var: str = "VISION_ENABLED"
    """is_available() 가 본 환경변수 (1/true/yes) 일 때만 True 반환."""

    with_retrieval_env_var: str = "VISION_WITH_RETRIEVAL"
    """본 변수가 truthy 일 때만 text_retriever 가 활성화 — 인용 첨부 가능."""

    text_top_k: int = 5
    """text_retriever 활성 시 검색 청크 수."""


@dataclass
class AgenticStrategyConfig:
    """Agentic 전략의 노브 — ReAct 루프 / 도구 호출 / cache 추적."""

    recursion_limit: int = 10
    """ReAct 루프 재귀 한도 — 도구 호출 + 답변 노드 합산. 폭주 방지."""

    label: str = "Agentic"
    pattern_name: str = "Agentic RAG"
    system_prompt: str = (
        "당신은 칼빈 신학 전문 학습 도우미입니다.\n"
        "주어진 도구를 사용해 칼빈 강요(Institutes of the Christian Religion) 본문을 "
        "검색하고 답변하세요.\n\n"
        "## 행동 가이드:\n"
        "1. 질문이 칼빈 신학과 관련 있다면 search_documents 도구로 본문을 검색하세요.\n"
        "2. 검색 결과로 충분하지 않으면 다른 키워드로 한 번 더 검색해도 됩니다 "
        "(최대 2~3회).\n"
        "3. 검색 결과가 답변에 충분하면 그 본문을 근거로 답변하세요.\n"
        "4. 칼빈 신학과 무관한 질문 (예: 날씨, 일반 지식)은 도구를 호출하지 말고 "
        "'본 챗봇은 칼빈 신학에 한정된 답변만 가능합니다'라고 안내하세요.\n"
        "5. 답변 시 가능하면 권/장 번호를 인용하세요.\n"
        "6. 본문에서 직접 찾을 수 없으면 '본문에서 직접 찾을 수 없습니다'라고 명확히 "
        "안내하고, 추측이나 외부 지식으로 빈 곳을 메우지 마세요.\n"
        "7. 본문 인용 시 반드시 답변 문장 끝에 `[p.N]` 형태로 PDF 페이지 번호를 "
        "표기하세요. N은 search_documents 결과의 [page N] 마커 숫자입니다. "
        '예: "칼빈은 예정을 하나님의 영원한 작정으로 정의한다 [p.780]."'
    )
