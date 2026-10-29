from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from app.schemas.faq import FAQSource


# A read-only snapshot of the cache counters; frozen so callers cannot change it.
@dataclass(frozen=True)
class FAQCacheStats:
    hits: int
    misses: int
    sets: int
    evictions: int
    entries: int


# One cached search result and the time at which it stops being valid.
@dataclass
class _FAQCacheEntry:
    expires_at: float
    items: list[dict[str, object]]


# Remembers FAQ search results in memory so repeated searches skip MongoDB.
# Entries expire after ttl_seconds, and the least recently used entry is dropped when max_entries is exceeded.
# It is process-local: every server process has its own cache.
class FAQSearchCache:
    """Small process-local TTL cache for the course caching lesson."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 60.0,
        max_entries: int = 100,
    ) -> None:
        # OrderedDict remembers order: least recently used first, most recently used last.
        self._entries: OrderedDict[str, _FAQCacheEntry] = OrderedDict()
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0

    def configure(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._trim_to_limit()

    # Returns the cached FAQs, or None on a miss (never stored, or expired).
    def get(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[FAQSource] | None:
        self._remove_expired()
        key = self._key(query, limit)
        entry = self._entries.get(key)

        if entry is None:
            self._misses += 1
            return None

        if entry.expires_at <= monotonic():
            self._entries.pop(key, None)
            self._misses += 1
            return None

        self._entries.move_to_end(key)
        self._hits += 1
        # Entries are stored as plain dicts and rebuilt on every hit,
        # so callers cannot modify the cached copy by accident.
        return [FAQSource.model_validate(item) for item in entry.items]

    # Stores a search result with an expiry time, then evicts old entries if we are over the limit.
    def set(
        self,
        query: str,
        *,
        limit: int,
        items: list[FAQSource],
    ) -> None:
        key = self._key(query, limit)
        self._entries[key] = _FAQCacheEntry(
            # monotonic() is a clock that never jumps backwards, which makes it safe for timeouts.
            expires_at=monotonic() + self._ttl_seconds,
            items=[item.model_dump(mode="python") for item in items],
        )
        # Mark this entry as recently used so it is evicted last.
        self._entries.move_to_end(key)
        self._sets += 1
        self._trim_to_limit()

    def clear(self, *, reset_stats: bool = True) -> None:
        self._entries.clear()
        if reset_stats:
            self._hits = 0
            self._misses = 0
            self._sets = 0
            self._evictions = 0

    def snapshot(self) -> FAQCacheStats:
        self._remove_expired()
        return FAQCacheStats(
            hits=self._hits,
            misses=self._misses,
            sets=self._sets,
            evictions=self._evictions,
            entries=len(self._entries),
        )

    # Drop the oldest entries until we are back under max_entries.
    def _trim_to_limit(self) -> None:
        while len(self._entries) > self._max_entries:
            # last=False removes the oldest (first) entry.
            self._entries.popitem(last=False)
            self._evictions += 1

    def _remove_expired(self) -> None:
        now = monotonic()
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)

    # Normalise the query so "Refund  Policy" and "refund policy" share one cache entry.
    @staticmethod
    def _key(query: str, limit: int) -> str:
        normalized = " ".join(query.strip().lower().split())
        return f"{limit}:{normalized}"


# One shared cache for the whole app; services import this instance.
faq_search_cache = FAQSearchCache()
