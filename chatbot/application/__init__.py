"""Application 레이어 — 오케스트레이터·노드·registry 등 도메인 위의 *조립 책임*.

도메인 Protocol 의 in-memory 구현, LangGraph 와이어링 등이 본 레이어에 모인다.
도메인만 의존하고 인프라(LangChain/Neo4j) 는 import 하지 않는다.
"""
