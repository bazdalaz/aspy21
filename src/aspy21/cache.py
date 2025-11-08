"""Caching layer for Aspen API responses to reduce load and improve performance."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, TypeVar

import pandas as pd

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheConfig:
    """Configuration for caching behavior.

    Attributes:
        enabled: Enable/disable caching (default: True)
        max_size: Maximum number of cache entries (default: 1000)
        ttl_search: TTL for search results in seconds (default: 3600 = 1h)
        ttl_metadata: TTL for tag descriptions in seconds (default: 3600 = 1h)
        ttl_historical: TTL for historical data in seconds (default: 86400 = 24h)
        ttl_snapshot: TTL for snapshot data in seconds (default: 60 = 1min)
        ttl_aggregates: TTL for aggregates in seconds (default: 86400 = 24h)
    """

    enabled: bool = True
    max_size: int = 1000
    ttl_search: int = 3600  # 1 hour
    ttl_metadata: int = 3600  # 1 hour
    ttl_historical: int = 86400  # 24 hours
    ttl_snapshot: int = 60  # 1 minute
    ttl_aggregates: int = 86400  # 24 hours


class CacheEntry:
    """Cache entry with TTL support."""

    def __init__(self, value: Any, ttl_seconds: int):
        """Initialize cache entry.

        Args:
            value: Value to cache
            ttl_seconds: Time-to-live in seconds
        """
        self.value = value
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return datetime.now() > self.expires_at

    def __repr__(self) -> str:
        """String representation."""
        age = (datetime.now() - self.created_at).total_seconds()
        ttl_remaining = (self.expires_at - datetime.now()).total_seconds()
        return f"CacheEntry(age={age:.1f}s, ttl_remaining={ttl_remaining:.1f}s)"


class AspenCache:
    """Thread-safe LRU cache with TTL support for Aspen API responses."""

    def __init__(self, config: CacheConfig | None = None):
        """Initialize cache with configuration.

        Args:
            config: Cache configuration. If None, uses default config.
        """
        self.config = config or CacheConfig()
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

        logger.info(
            f"Initialized AspenCache: enabled={self.config.enabled}, "
            f"max_size={self.config.max_size}"
        )

    def _generate_key(self, operation: str, **params: Any) -> str:
        """Generate cache key from operation and parameters.

        Args:
            operation: Operation type (read, search, etc.)
            **params: Parameters to include in key

        Returns:
            Hash-based cache key
        """
        # Sort parameters for consistent keys
        sorted_params = sorted(params.items())

        # Handle special types
        key_data: dict[str, Any] = {"op": operation}
        for k, v in sorted_params:
            if isinstance(v, (list, tuple)):
                # Sort and convert to tuple for consistent hashing
                key_data[k] = tuple(str(x) for x in sorted(v)) if v else ()
            elif isinstance(v, pd.DataFrame):
                # Don't cache DataFrames as keys
                continue
            elif hasattr(v, "value"):  # Enum
                key_data[k] = v.value
            else:
                key_data[k] = v

        # Generate hash
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if cache is full (LRU policy)."""
        if len(self._cache) >= self.config.max_size:
            # Sort by creation time and remove oldest
            oldest_key = min(self._cache.items(), key=lambda x: x[1].created_at)[0]
            del self._cache[oldest_key]
            logger.debug(f"Evicted cache entry: {oldest_key}")

    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
        for key in expired_keys:
            del self._cache[key]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    def get(self, operation: str, **params: Any) -> Any | None:
        """Get value from cache if present and not expired.

        Args:
            operation: Operation type
            **params: Parameters that were used for the operation

        Returns:
            Cached value or None if not found or expired
        """
        if not self.config.enabled:
            return None

        key = self._generate_key(operation, **params)

        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                logger.debug(f"Cache miss: {operation} (key={key})")
                return None

            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                logger.debug(f"Cache expired: {operation} (key={key})")
                return None

            self._hits += 1
            logger.debug(f"Cache hit: {operation} (key={key}, {entry})")
            return entry.value

    def set(
        self, operation: str, value: Any, ttl_seconds: int | None = None, **params: Any
    ) -> None:
        """Store value in cache with TTL.

        Args:
            operation: Operation type
            value: Value to cache
            ttl_seconds: Time-to-live in seconds. If None, uses default for operation.
            **params: Parameters that were used for the operation
        """
        if not self.config.enabled:
            return

        # Determine TTL based on operation type
        if ttl_seconds is None:
            ttl_map = {
                "search": self.config.ttl_search,
                "metadata": self.config.ttl_metadata,
                "read_historical": self.config.ttl_historical,
                "read_snapshot": self.config.ttl_snapshot,
                "read_aggregates": self.config.ttl_aggregates,
            }
            ttl_seconds = ttl_map.get(operation, 3600)  # Default 1 hour

        key = self._generate_key(operation, **params)

        with self._lock:
            self._cleanup_expired()
            self._evict_if_needed()
            entry = CacheEntry(value, ttl_seconds)
            self._cache[key] = entry
            logger.debug(f"Cache set: {operation} (key={key}, ttl={ttl_seconds}s)")

    def invalidate(self, operation: str | None = None, **params: Any) -> int:
        """Invalidate cache entries.

        Args:
            operation: If specified, only invalidate entries for this operation.
                      If None, clear entire cache.
            **params: If specified, only invalidate entries matching these params.

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            if operation is None and not params:
                # Clear entire cache
                count = len(self._cache)
                self._cache.clear()
                logger.info(f"Cleared entire cache ({count} entries)")
                return count

            # Invalidate specific entry
            key = self._generate_key(operation or "", **params)
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Invalidated cache entry: {operation} (key={key})")
                return 1

            return 0

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats: hits, misses, hit_rate, size, etc.
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "enabled": self.config.enabled,
                "size": len(self._cache),
                "max_size": self.config.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total_requests,
                "hit_rate_percent": round(hit_rate, 2),
            }

    def clear_stats(self) -> None:
        """Reset hit/miss counters."""
        with self._lock:
            self._hits = 0
            self._misses = 0
        logger.debug("Cache stats cleared")


def cached(
    cache_instance: AspenCache, operation: str, ttl_seconds: int | None = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for caching function results.

    Args:
        cache_instance: Cache instance to use
        operation: Operation type for cache key
        ttl_seconds: Optional TTL override

    Returns:
        Decorated function with caching

    Example:
        >>> cache = AspenCache()
        >>> @cached(cache, "expensive_op", ttl_seconds=3600)
        ... def expensive_function(x, y):
        ...     return x + y
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Try to get from cache
            cached_value = cache_instance.get(operation, args=args, kwargs=kwargs)
            if cached_value is not None:
                return cached_value

            # Execute function
            result = func(*args, **kwargs)

            # Store in cache
            cache_instance.set(operation, result, ttl_seconds=ttl_seconds, args=args, kwargs=kwargs)

            return result

        return wrapper

    return decorator
