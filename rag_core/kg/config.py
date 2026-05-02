"""Neo4j 연결 설정. URI scheme으로 local/aura 자동 감지."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Neo4jConfig(BaseSettings):
    """Neo4j 연결 설정.

    URI scheme으로 환경 자동 감지:
        - ``bolt://`` 또는 ``neo4j://``: 로컬 Docker (개발용)
        - ``neo4j+s://`` 또는 ``bolt+s://``: Neo4j Aura (시연용)

    환경 전환은 ``.env``의 ``NEO4J_URI`` 만 변경하면 끝. 코드 무수정.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    uri: Annotated[str, Field(alias="NEO4J_URI")] = "bolt://localhost:7687"
    username: Annotated[str, Field(alias="NEO4J_USERNAME")] = "neo4j"
    password: Annotated[SecretStr, Field(alias="NEO4J_PASSWORD")] = SecretStr("password")

    # KG 인덱싱 모델 설정 (LLMGraphTransformer 용)
    openai_model: Annotated[str, Field(alias="OPENAI_MODEL")] = "gpt-4o-mini"
    openai_api_key: Annotated[SecretStr, Field(alias="OPENAI_API_KEY")] = SecretStr("")

    @property
    def mode(self) -> Literal["local", "aura"]:
        """URI scheme 기반 환경 감지."""
        if self.uri.startswith(("neo4j+s://", "bolt+s://")):
            return "aura"
        return "local"

    @property
    def is_secure(self) -> bool:
        """SSL/TLS 사용 여부 (Aura는 필수)."""
        return self.mode == "aura"
