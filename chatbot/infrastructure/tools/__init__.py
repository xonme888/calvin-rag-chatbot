"""Tool 어댑터 — domain.Tool Protocol 구현체와 LangChain 양방향 변환.

각 Tool 은 *한 동작* 만 책임진다 ("검색+요약" 같은 합성은 Strategy 에서). 새 외부 통합은
``tools/<category>/<name>.py`` 에 1개 파일로 추가하고 ToolRegistry 에 등록한다.
"""

from chatbot.infrastructure.tools._adapters.domain_to_langchain import (
    domain_tool_to_basetool,
)
from chatbot.infrastructure.tools._adapters.langchain_to_domain import basetool_to_domain_tool

__all__ = ["domain_tool_to_basetool", "basetool_to_domain_tool"]
