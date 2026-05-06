"""Stage 어댑터 모음 — domain.Stage[I, O] 구현.

각 Stage 는 *한 책임*만 가진다:
- retrieve_stage          : RetrievalRequest → list[DocumentRef]
- generate_stage          : GenerateInput → GenerateOutput   (LLM 답변 합성)
- grade_stage             : GradeInput → GradeResult         (Self-RAG 근거도 평가)
- rewrite_stage           : RewriteInput → str               (Self-RAG 질문 재작성)
- extract_entities_stage  : str → ExtractEntitiesResult       (KG 엔티티 추출)
- normalize_subgraph_stage: Subgraph → Subgraph              (alias 통합·노이즈 제거)
- section_filter_stage    : list[Chunk] → list[Chunk]        (단원 범위 필터)

재랭크 단계는 ``chatbot/infrastructure/rerankers/`` 에서 별도 제공.
"""

from chatbot.infrastructure.stages.extract_entities_stage import (
    ExtractEntitiesResult,
    ExtractEntitiesStage,
)
from chatbot.infrastructure.stages.generate_stage import (
    GenerateInput,
    GenerateOutput,
    GenerateStage,
)
from chatbot.infrastructure.stages.grade_stage import (
    GradeInput,
    GradeResult,
    GradeStage,
)
from chatbot.infrastructure.stages.normalize_subgraph_stage import NormalizeSubgraphStage
from chatbot.infrastructure.stages.prepare_image_payload_stage import (
    PreparedPayload,
    PrepareImagePayloadStage,
)
from chatbot.infrastructure.stages.retrieve_stage import RetrieveStage
from chatbot.infrastructure.stages.rewrite_stage import RewriteInput, RewriteStage
from chatbot.infrastructure.stages.section_filter_stage import (
    DEFAULT_CALVIN_SECTIONS,
    Section,
    SectionFilterStage,
)

__all__ = [
    "RetrieveStage",
    "GenerateStage",
    "GenerateInput",
    "GenerateOutput",
    "GradeStage",
    "GradeInput",
    "GradeResult",
    "RewriteStage",
    "RewriteInput",
    "ExtractEntitiesStage",
    "ExtractEntitiesResult",
    "NormalizeSubgraphStage",
    "SectionFilterStage",
    "Section",
    "DEFAULT_CALVIN_SECTIONS",
    "PrepareImagePayloadStage",
    "PreparedPayload",
]
