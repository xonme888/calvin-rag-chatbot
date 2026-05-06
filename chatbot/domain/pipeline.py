"""제너릭 파이프라인 추상 — Stage[I, O], Pipeline[I, O].

인덱싱·검색·생성 등 어디서든 *순차 변환* 패턴이 나타난다. 이를 한 추상으로 통일해
- 단계 추가/교체/삽입을 균일하게 처리
- 단계별 trace event 기록을 한 곳에 위임
- 테스트는 단계 단독 + 파이프라인 합성 두 층위로 분리

도메인은 추상만 정의한다. 구체 파이프라인 (RetrievalPipeline 등) 은 application 레이어.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

TIn = TypeVar("TIn")
TOut = TypeVar("TOut")


@runtime_checkable
class Stage(Protocol, Generic[TIn, TOut]):
    """단일 변환 단계. 하나의 입력 타입 → 하나의 출력 타입.

    구현체는 *작은* 클래스/함수 — 한 책임만 갖는다. 예:
    - DocumentLoader: KnowledgeSource → list[Document]
    - QueryRewriter:  RetrievalRequest → RetrievalRequest (standalone_question 갱신)
    - Reranker:       list[DocumentRef] → list[DocumentRef] (재정렬)
    """

    name: str

    def run(self, input: TIn) -> TOut: ...


class Pipeline(Generic[TIn, TOut]):
    """Stage 들의 합성. 입력 타입 → 출력 타입.

    중간 단계의 타입 안전은 Python 의 generics 한계상 런타임에는 보장되지 않는다.
    구체 파이프라인은 명시적 타입 alias 로 단계 간 타입을 문서화한다 (application 레이어 참고).

    이 클래스는 *얇다* — 단계를 순회하며 각 단계의 ``run`` 을 호출할 뿐. 실패 처리·재시도·
    trace 는 데코레이터 또는 미들웨어 Stage 로 합성한다 (단일 책임 유지).
    """

    def __init__(self, name: str, stages: list[Stage]) -> None:
        self.name = name
        self.stages: tuple[Stage, ...] = tuple(stages)

    def run(self, input: TIn) -> TOut:
        value: object = input
        for stage in self.stages:
            value = stage.run(value)
        return value  # type: ignore[return-value]

    def with_stage(self, stage: Stage, *, before: str | None = None) -> Pipeline[TIn, TOut]:
        """새 단계를 삽입한 새 Pipeline 반환. 원본은 변경하지 않는다.

        before=None 이면 끝에 append. before='reranker' 면 'reranker' 앞에 삽입.
        """
        if before is None:
            return Pipeline(self.name, [*self.stages, stage])
        new_stages: list[Stage] = []
        inserted = False
        for s in self.stages:
            if not inserted and s.name == before:
                new_stages.append(stage)
                inserted = True
            new_stages.append(s)
        if not inserted:
            raise KeyError(f"Stage 없음: {before}")
        return Pipeline(self.name, new_stages)
