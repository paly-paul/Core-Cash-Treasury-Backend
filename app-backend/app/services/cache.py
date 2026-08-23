import asyncio
from datetime import datetime, timedelta
from typing import Optional

cache_invalidation_flags = {}


async def invalidate_cash_position_cache(client_id: str) -> None:
    """Invalidate cash position cache for a client."""
    cache_invalidation_flags[f"cash_position:{client_id}"] = datetime.utcnow()


async def is_cache_valid(client_id: str, last_computed: Optional[datetime] = None) -> bool:
    """Check if cache is still valid for a client."""
    key = f"cash_position:{client_id}"
    if key not in cache_invalidation_flags:
        return True
    invalidation_time = cache_invalidation_flags[key]
    if last_computed and invalidation_time < last_computed:
        return True
    return False
