from typing import Any

from app.config import get_settings
from app.core.cache import faq_search_cache
from app.core.logging import log_event
from app.schemas.faq import FAQSource


# Only approved support fields leave the repository boundary.
FAQ_SOURCE_PROJECTION = {
    "_id": 0,
    "faq_id": 1,
    "category": 1,
    "question": 1,
    "answer": 1,
}


# The only code that reads the faqs collection. Only active, approved FAQs can leave it.
class FAQRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database.faqs
        self.settings = get_settings()

        # Apply the cache size and expiry from settings.
        faq_search_cache.configure(
            ttl_seconds=self.settings.faq_cache_ttl_seconds,
            max_entries=self.settings.faq_cache_max_entries,
        )

    # Fetch FAQs by ID. IDs only select records; the content always comes from the database.
    async def get_by_ids(
        self,
        faq_ids: list[str],
        *,
        limit: int = 3,
    ) -> list[FAQSource]:
        # Remove duplicate IDs (keeping their order) and cap how many FAQs are used.
        requested_ids = list(dict.fromkeys(faq_ids))[:limit]

        if not requested_ids:
            return []

        # Only active approved FAQs can be returned.
        cursor = self.collection.find(
            {
                "faq_id": {"$in": requested_ids},
                "active": True,
            },
            FAQ_SOURCE_PROJECTION,
        )

        found: dict[str, FAQSource] = {}

        # Validate each document before the application uses it.
        async for document in cursor:
            faq = FAQSource.model_validate(document)
            found[faq.faq_id] = faq

        # Preserve the requested ID order when returning matches.
        return [
            found[faq_id]
            for faq_id in requested_ids
            if faq_id in found
        ]

    # Full-text search over the FAQs; this needs a text index on the faqs collection.
    async def search(
        self,
        query: str,
        *,
        limit: int = 3,
    ) -> list[FAQSource]:
        search_query = query.strip()

        if not search_query:
            return []

        # Keep the limit between 1 and 3 so only a small amount of FAQ text goes to Claude.
        safe_limit = max(1, min(limit, 3))

        # Check the cache first: a repeated search skips MongoDB.
        if self.settings.faq_cache_enabled:
            cached = faq_search_cache.get(
                search_query,
                limit=safe_limit,
            )
            if cached is not None:
                log_event(
                    "faq_cache_hit",
                    limit=safe_limit,
                    result_count=len(cached),
                )
                return cached
            log_event(
                "faq_cache_miss",
                limit=safe_limit,
            )

        # MongoDB performs retrieval; Claude does not browse the collection.
        pipeline = [
            {
                "$match": {
                    "active": True,
                    "$text": {
                        "$search": search_query,
                    },
                }
            },
            {
                "$sort": {
                    "score": {
                        "$meta": "textScore",
                    }
                }
            },
            {
                "$limit": safe_limit,
            },
            {
                "$project": FAQ_SOURCE_PROJECTION,
            },
        ]

        cursor = await self.collection.aggregate(pipeline)

        results: list[FAQSource] = []

        # Validate each document before the application uses it.
        async for document in cursor:
            results.append(
                FAQSource.model_validate(document)
            )

        # Remember this result for the next identical search.
        if self.settings.faq_cache_enabled:
            faq_search_cache.set(
                search_query,
                limit=safe_limit,
                items=results,
            )

        return results
