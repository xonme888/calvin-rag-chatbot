"""LangChain BaseTool ↔ domain.Tool 양방향 어댑터.

도메인은 LangChain 무지를 유지한다 — 본 어댑터가 두 세계를 잇는다. AgenticStrategy 의
create_agent 호출은 BaseTool 시퀀스를 요구하므로, registry 가 보유한 domain.Tool 들을
``domain_tool_to_basetool`` 로 변환해 전달한다.

반대 방향(``basetool_to_domain_tool``)은 PRD-001 의 rag_core/tools/registry.py 가 등록한
기존 BaseTool 자산을 domain.Tool 로 흡수해 ToolRegistry 가 단일 시그니처로 관리하기 위함.
"""
