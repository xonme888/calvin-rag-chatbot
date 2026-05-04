"""글로벌 LLM 캐시 — query 단위 hit/miss 측정 가능한 InMemoryCache 싱글톤.

설계:
- LangChain ``set_llm_cache`` 는 프로세스 글로벌이라 모드 (Hybrid/Agentic/KG) 와
  무관하게 같은 캐시 인스턴스를 공유한다.
- query 단위 통계가 필요하므로 reset 이 아니라 **시작 시점 snapshot → 종료 시점
  snapshot 차이** 로 계산. 동시 query 가 섞여도 안전.
"""

from __future__ import annotations

from typing import Any

from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache


class TrackedInMemoryCache(InMemoryCache):
    """``InMemoryCache``를 확장해 lookup 시 누적 hit/miss 카운트.

    LangChain LLM 은 cache 사용 시 매 호출마다 ``lookup(prompt, llm_string)`` 을
    호출한다. None 반환은 cache miss (LLM 호출), 값 반환은 cache hit.
    """

    def __init__(self) -> None:
        super().__init__()
        self.hits: int = 0
        self.misses: int = 0

    def lookup(self, prompt: str, llm_string: str) -> Any:
        result = super().lookup(prompt, llm_string)
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def reset(self) -> None:
        """누적 카운트 초기화 (테스트용). 캐시 데이터는 보존."""
        self.hits = 0
        self.misses = 0


_global_cache: TrackedInMemoryCache | None = None


def get_tracked_cache() -> TrackedInMemoryCache:
    """프로세스 글로벌 캐시 인스턴스 반환. 첫 호출 시 langchain 글로벌에 등록."""
    global _global_cache
    if _global_cache is None:
        _global_cache = TrackedInMemoryCache()
        set_llm_cache(_global_cache)
    return _global_cache


def cache_snapshot() -> tuple[int, int]:
    """현재 누적 (hits, misses) 스냅샷."""
    c = get_tracked_cache()
    return c.hits, c.misses


def cache_delta(start: tuple[int, int]) -> dict[str, Any]:
    """``start`` (이전 snapshot) 이후의 query 단위 hit/miss 통계.

    Returns:
        {
            "cache_hits": int,
            "cache_misses": int,
            "cache_total": int,
            "cache_hit_rate": float (0~1),
            "from_cache": bool,  # 모든 LLM 호출이 캐시 hit 이면 True
        }
    """
    h_now, m_now = cache_snapshot()
    hits = max(0, h_now - start[0])
    misses = max(0, m_now - start[1])
    total = hits + misses
    rate = (hits / total) if total else 0.0
    return {
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_total": total,
        "cache_hit_rate": round(rate, 3),
        "from_cache": total > 0 and misses == 0,
    }
