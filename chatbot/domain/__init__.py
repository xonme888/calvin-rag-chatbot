"""도메인 레이어 — 불변 모델 + Protocol.

규칙:
- 외부 라이브러리 의존성은 pydantic 만. langchain/fastapi/openai 등 import 금지.
- 도메인은 행동(부수효과)을 갖지 않는다. 데이터와 계약만.
- 모든 모델은 frozen (불변). Conversation 같은 누적 객체도 turns 추가 시 새 인스턴스 반환을 권장.
"""
