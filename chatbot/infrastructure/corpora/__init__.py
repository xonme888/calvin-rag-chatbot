"""Corpus 어댑터 — 새 도메인(책) 추가 진입점.

각 corpus 모듈은:
- ``KnowledgeSource`` 인스턴스 (1개 책 = 1개 source 가 보통)
- ``Corpus`` 인스턴스 (registry 등록 단위)
- ``SYSTEM_PROMPT`` 상수 (해당 corpus 의 답변 가이드)

만 노출한다. 행동(빌더, 인덱싱)은 strategies 레이어가 책임진다.
"""
