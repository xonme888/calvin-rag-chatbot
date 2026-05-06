"""IntentClassifier 테스트 — 휴리스틱 우선순위 + LLM fallback 비활성/활성."""

from __future__ import annotations

from datetime import UTC, datetime

from chatbot.domain.conversation import Message, Turn
from chatbot.domain.intent import Intent
from chatbot.infrastructure.intent_llm import (
    HeuristicIntentClassifier,
    HeuristicWithLLMFallbackClassifier,
)


def _msg(text: str) -> Message:
    return Message(role="user", content=text)


def _last_turn() -> Turn:
    return Turn(
        user_message=Message(role="user", content="이전질문"),
        intent=Intent.NEW_QUESTION,
        answer=Message(role="assistant", content="이전답변"),
        trace_id="t",
        elapsed_ms=1,
        started_at=datetime.now(UTC),
    )


def test_heuristic_meta_reference_우선():
    c = HeuristicIntentClassifier()
    assert (
        c.classify(message=_msg("방금 그 그래프"), last_turn=_last_turn()) == Intent.META_REFERENCE
    )


def test_heuristic_meta_recap():
    c = HeuristicIntentClassifier()
    assert c.classify(message=_msg("위 내용 요약"), last_turn=_last_turn()) == Intent.META_RECAP
    assert c.classify(message=_msg("정리해줘"), last_turn=_last_turn()) == Intent.META_RECAP


def test_heuristic_meta_recap_대화_자체_지칭():
    """운영에서 발견된 회귀 — '우리 무슨 대화를 한 것 같아' 류가 NEW_QUESTION 으로 잘못
    분류되어 PDF 검색이 일어나던 문제.
    """
    c = HeuristicIntentClassifier()
    cases = [
        "우리 무슨 대화를 한 것 같아",
        "내가 뭐 물어봤지?",
        "여태 어떤 이야기 했지?",
        "내가 한 질문이 뭐야",
        "우리 뭐 얘기했어",
        "내가 한 질문",
    ]
    for text in cases:
        assert c.classify(message=_msg(text), last_turn=_last_turn()) == Intent.META_RECAP, (
            f"META_RECAP 분류 실패: {text}"
        )


def test_heuristic_meta_reference_확장():
    c = HeuristicIntentClassifier()
    cases = ["아까 그 답변", "조금 전에 본 그래프", "이전 답변을 다시"]
    for text in cases:
        assert c.classify(message=_msg(text), last_turn=_last_turn()) == Intent.META_REFERENCE, (
            f"META_REFERENCE 분류 실패: {text}"
        )


def test_heuristic_smalltalk():
    c = HeuristicIntentClassifier()
    assert c.classify(message=_msg("안녕하세요"), last_turn=None) == Intent.SMALLTALK
    assert c.classify(message=_msg("고마워요"), last_turn=None) == Intent.SMALLTALK


def test_heuristic_followup_last_turn_있을_때만():
    c = HeuristicIntentClassifier()
    assert c.classify(message=_msg("그러면 무엇인가?"), last_turn=_last_turn()) == Intent.FOLLOWUP
    # last_turn 없으면 NEW_QUESTION
    assert c.classify(message=_msg("그러면 무엇인가?"), last_turn=None) == Intent.NEW_QUESTION


def test_heuristic_new_question_default():
    c = HeuristicIntentClassifier()
    assert c.classify(message=_msg("예정론은 무엇인가?"), last_turn=None) == Intent.NEW_QUESTION
    assert (
        c.classify(message=_msg("칼빈과 루터의 차이"), last_turn=_last_turn())
        == Intent.NEW_QUESTION
    )


def test_heuristic_우선순위_meta_reference_우선():
    """동일 메시지에 META_REFERENCE + META_RECAP 키워드 → META_REFERENCE 가 1위."""
    c = HeuristicIntentClassifier()
    assert (
        c.classify(message=_msg("방금 그 그래프 요약"), last_turn=_last_turn())
        == Intent.META_REFERENCE
    )


def test_llm_fallback_비활성_휴리스틱_그대로(monkeypatch):
    """CHATBOT_INTENT_LLM 미설정 시 LLM 호출 0."""
    monkeypatch.delenv("CHATBOT_INTENT_LLM", raising=False)

    class _Counter:
        def __init__(self):
            self.calls = 0

        def with_structured_output(self, schema):
            self.calls += 1
            return self

    counter = _Counter()
    c = HeuristicWithLLMFallbackClassifier(llm=counter)  # type: ignore[arg-type]
    assert c.classify(message=_msg("예정론?"), last_turn=None) == Intent.NEW_QUESTION
    assert counter.calls == 0


def test_llm_fallback_NEW_QUESTION_만_활성(monkeypatch):
    """LLM fallback 은 휴리스틱이 NEW_QUESTION 디폴트일 때만 호출. META 등은 휴리스틱 결과 보존."""
    monkeypatch.setenv("CHATBOT_INTENT_LLM", "true")

    class _LLM:
        def __init__(self):
            self.calls = 0

        def with_structured_output(self, schema):
            self.calls += 1
            raise RuntimeError("simulated")

    llm = _LLM()
    c = HeuristicWithLLMFallbackClassifier(llm=llm)  # type: ignore[arg-type]

    # META_RECAP — 휴리스틱 결과 그대로, LLM 미호출
    c.classify(message=_msg("위 내용 요약"), last_turn=_last_turn())
    assert llm.calls == 0

    # NEW_QUESTION 케이스 — LLM 호출 발생 (실패 시 휴리스틱 폴백)
    result = c.classify(message=_msg("예정론?"), last_turn=None)
    assert llm.calls == 1
    assert result == Intent.NEW_QUESTION  # LLM 실패 시 휴리스틱 결과 유지
