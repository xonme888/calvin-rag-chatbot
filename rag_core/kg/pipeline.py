"""Knowledge Graph RAG — Cypher 부분 그래프 + 벡터 검색 결합.

흐름:
1. 질문에서 엔티티 추출 (LLM, structured output)
2. KG 부분 그래프 (어댑터 ``get_subgraph(entities, hops)``)
3. Hybrid 벡터 검색 (HybridRAG 재사용 — 청크 본문)
4. [그래프 관계 + 청크 본문] 결합 컨텍스트 → LLM 답변
5. 시각화용 부분 그래프를 metadata에 반환

이 클래스는 ``KnowledgeGraphPort``에만 의존 — Mock 어댑터로 단위 테스트 가능.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field as PydanticField

from rag_core.hybrid import HybridRAG, _format_doc_with_meta
from rag_core.kg.section_filter import (
    DEFAULT_CALVIN_SECTIONS,
    CalvinSection,
    estimate_cost,
    filter_chunks_by_sections,
)
from rag_core.kg.port import KnowledgeGraphPort, SubgraphData


# ====================================================================
# Structured Output 스키마
# ====================================================================
class EntityExtraction(PydanticBaseModel):
    """질문에서 추출한 엔티티들."""

    entities: list[str] = PydanticField(
        default_factory=list,
        description="질문에 등장한 핵심 엔티티 (인물명/신학 개념/교리). 짧은 명사형.",
    )
    intent: str = PydanticField(
        default="general",
        description=(
            "질문 의도: 'definition' (정의 묻기), 'comparison' (비교), "
            "'influence' (영향 관계), 'general' (그 외)"
        ),
    )


KG_SYSTEM_PROMPT = """당신은 칼빈 신학 전문 학습 도우미입니다.
아래 두 가지 정보를 결합해 답변하세요:

## 1) 지식 그래프 (개념/인물 관계)
{graph_text}

## 2) 칼빈 강요 본문 발췌 (검증된 출처)
{chunk_text}

## 답변 가이드:
1. 그래프 관계가 직접적인 답을 줄 때는 그것을 우선 활용 (예: "어거스틴이 영향을 준 개념")
2. 본문 발췌로 구체 근거를 인용 (페이지 번호 포함)
3. 그래프 관계와 본문이 모순되면 본문을 우선
4. 본문에서 직접 찾을 수 없으면 "본문에서 직접 찾을 수 없습니다"라고 명확히 안내
5. 핵심 인물/개념을 답변에 명시 (시각화에 활용됨)
"""


class KnowledgeGraphRAG:
    """Cypher + 벡터 결합 RAG.

    Hybrid의 검색 인프라(BM25 + Dense + RRF)를 재사용하면서
    KG 부분 그래프를 추가 컨텍스트로 결합한다.
    """

    PATTERN_NAME: str = "Knowledge Graph RAG"

    def __init__(
        self,
        kg_adapter: KnowledgeGraphPort,
        hybrid_rag: HybridRAG,
        sections: tuple[CalvinSection, ...] = DEFAULT_CALVIN_SECTIONS,
        llm: BaseChatModel | None = None,
        subgraph_hops: int = 1,
    ) -> None:
        """KG RAG 인스턴스를 생성한다.

        Args:
            kg_adapter: KG 백엔드 어댑터 (Neo4j 또는 Mock).
            hybrid_rag: 벡터 검색 인프라 제공. ``index_documents()`` 가 끝난 상태여야 함.
            sections: 인덱싱 대상 단원. 통계/비용 추정용.
            llm: 외부 주입 LLM. None이면 hybrid의 llm 재사용.
            subgraph_hops: 부분 그래프 탐색 홉 수.
        """
        self.kg = kg_adapter
        self.hybrid = hybrid_rag
        self.sections = sections
        self.llm: BaseChatModel = llm or hybrid_rag.llm
        self.subgraph_hops = subgraph_hops

        self._extract_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "사용자 질문에서 핵심 엔티티(인물명/신학 개념/교리)를 추출하고 "
                    "질문 의도를 분류하세요. 엔티티는 짧은 명사형으로 정규화 "
                    "(예: '예정론', '어거스틴', '이신칭의').",
                ),
                ("human", "{question}"),
            ]
        )
        self._answer_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", KG_SYSTEM_PROMPT),
                ("human", "{question}"),
            ]
        )

    # ================================================================
    # 인덱싱
    # ================================================================
    def index_documents(self, documents: list[Document]) -> int:
        """문서를 청크로 나눠 핵심 단원 필터링 후 KG에 인덱싱.

        Hybrid는 별도로 ``index_documents()`` 가 끝나 있어야 함 (벡터 검색 인프라).

        Args:
            documents: PDF 페이지 단위 Document.

        Returns:
            KG에 인덱싱된 청크 수.
        """
        chunks = self.hybrid.text_splitter.split_documents(documents)
        filtered = filter_chunks_by_sections(chunks, self.sections)
        if not filtered:
            return 0
        return self.kg.index_chunks(filtered)

    def estimate_indexing_cost(self, documents: list[Document]) -> dict[str, float]:
        """본 인덱싱 전에 비용/시간 추정 (LLM 호출 없음, 청크 수 기반)."""
        chunks = self.hybrid.text_splitter.split_documents(documents)
        filtered = filter_chunks_by_sections(chunks, self.sections)
        return estimate_cost(filtered)

    # ================================================================
    # 질의
    # ================================================================
    def extract_entities(self, question: str) -> EntityExtraction:
        """질문에서 엔티티 + 의도 추출."""
        chain = self._extract_prompt | self.llm.with_structured_output(EntityExtraction)
        return chain.invoke({"question": question})  # type: ignore[return-value]

    def query(self, question: str, callbacks: list[Any] | None = None) -> dict[str, Any]:
        """질문에 답한다 (KG 부분 그래프 + 벡터 검색 결합).

        Returns:
            {
                "final_answer": str,
                "source_documents": list[str],     # 청크 본문 (벡터 검색 결과)
                "metadata": {
                    "pattern": "Knowledge Graph RAG",
                    "entities": list[str],
                    "intent": str,
                    "subgraph": {nodes, edges},     # 시각화용
                    "graph_node_count": int,
                    "graph_edge_count": int,
                    "vector_count": int,
                    "elapsed_seconds": float,
                    "source_pages": list[int | None],
                },
            }
        """
        if self.hybrid.vector_store is None or self.hybrid.bm25_retriever is None:
            raise RuntimeError("Hybrid RAG가 인덱싱되어 있지 않습니다.")

        start = time.time()

        invoke_config: dict[str, Any] = {}
        if callbacks:
            invoke_config["callbacks"] = callbacks

        # 1) 엔티티 추출
        extraction = self.extract_entities(question)
        entities = extraction.entities

        # 2) KG 부분 그래프
        subgraph: SubgraphData = (
            self.kg.get_subgraph(entities, hops=self.subgraph_hops)
            if entities
            else SubgraphData()
        )
        graph_text = _format_subgraph_for_llm(subgraph)

        # 3) 벡터 검색 (Hybrid의 RRF 재사용)
        bm25_results = self.hybrid.bm25_retriever.search(question, k=self.hybrid.config.top_k)
        dense_results = self.hybrid.vector_store.similarity_search_with_score(
            question, k=self.hybrid.config.top_k
        )
        fused = self.hybrid._reciprocal_rank_fusion(bm25_results, dense_results)
        top_docs = [doc for doc, _ in fused[: self.hybrid.config.top_k]]
        chunk_text = "\n\n---\n\n".join(_format_doc_with_meta(d) for d in top_docs)

        # 4) 결합 답변
        chain = self._answer_prompt | self.llm
        response = chain.invoke(
            {
                "question": question,
                "graph_text": graph_text,
                "chunk_text": chunk_text,
            },
            config=invoke_config,
        )
        answer = response.content if hasattr(response, "content") else str(response)

        elapsed = time.time() - start

        return {
            "final_answer": answer,
            "source_documents": [d.page_content for d in top_docs],
            "metadata": {
                "pattern": self.PATTERN_NAME,
                "entities": entities,
                "intent": extraction.intent,
                "subgraph": subgraph.model_dump(),
                "graph_node_count": len(subgraph.nodes),
                "graph_edge_count": len(subgraph.edges),
                "vector_count": len(top_docs),
                "elapsed_seconds": elapsed,
                "source_pages": [d.metadata.get("page") for d in top_docs],
            },
        }


def _format_subgraph_for_llm(subgraph: SubgraphData) -> str:
    """부분 그래프를 LLM이 읽기 좋은 텍스트로 변환.

    예:
        - 어거스틴 --[INFLUENCES]--> 칼빈
        - 칼빈 --[DEFINES]--> 예정론
        - 예정론 --[OPPOSED_BY]--> 펠라기우스
    """
    if not subgraph.edges:
        if subgraph.nodes:
            return "(그래프 노드: " + ", ".join(n.label for n in subgraph.nodes[:10]) + ")"
        return "(관련 그래프 관계 없음)"

    lines: list[str] = []
    for edge in subgraph.edges[:30]:  # 너무 많으면 LLM 컨텍스트 낭비
        src = _find_node_label(subgraph, edge.source)
        dst = _find_node_label(subgraph, edge.target)
        lines.append(f"- {src} --[{edge.label}]--> {dst}")
    return "\n".join(lines)


def _find_node_label(subgraph: SubgraphData, node_id: str) -> str:
    """node id 로 label 찾기 (없으면 id 자체 반환)."""
    for n in subgraph.nodes:
        if n.id == node_id:
            return n.label
    return node_id
