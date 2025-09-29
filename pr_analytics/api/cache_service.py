"""
Intelligent caching service for PR data.

This module provides a caching layer to balance API freshness with performance,
reducing load on Azure DevOps and GitHub APIs.
"""

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, Optional


class CacheService:
    """
    In-memory caching service with TTL and automatic invalidation.

    Features:
    - Time-to-live (TTL) based expiration
    - Thread-safe operations
    - Automatic cache invalidation
    - Cache statistics tracking
    """

    def __init__(self, default_ttl: int = 300, logger: Optional[logging.Logger] = None):
        """
        Initialize the cache service.

        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
            logger: Logger instance for tracking cache operations
        """
        self.default_ttl = default_ttl
        self.logger = logger or logging.getLogger(__name__)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "invalidations": 0,
            "expirations": 0,
        }

        # Start background cleanup thread
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_expired, daemon=True
        )
        self._cleanup_thread.start()
        self.logger.info(f"Cache service initialized with {default_ttl}s TTL")

    def _generate_key(
        self, namespace: str, identifier: str, params: Optional[Dict] = None
    ) -> str:
        """
        Generate a unique cache key.

        Args:
            namespace: Cache namespace (e.g., 'pull_requests', 'repositories')
            identifier: Unique identifier within namespace
            params: Optional parameters to include in key generation

        Returns:
            Unique cache key
        """
        key_parts = [namespace, identifier]
        if params:
            # Sort params for consistent key generation
            params_str = json.dumps(params, sort_keys=True)
            key_parts.append(hashlib.md5(params_str.encode()).hexdigest())

        return ":".join(key_parts)

    def get(
        self, namespace: str, identifier: str, params: Optional[Dict] = None
    ) -> Optional[Any]:
        """
        Retrieve data from cache.

        Args:
            namespace: Cache namespace
            identifier: Unique identifier
            params: Optional parameters

        Returns:
            Cached data or None if not found or expired
        """
        key = self._generate_key(namespace, identifier, params)

        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                self.logger.debug(f"Cache miss: {key}")
                return None

            entry = self._cache[key]

            # Check if expired
            if entry["expires_at"] < time.time():
                del self._cache[key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                self.logger.debug(f"Cache expired: {key}")
                return None

            self._stats["hits"] += 1
            self.logger.debug(f"Cache hit: {key}")
            return entry["data"]

    def set(
        self,
        namespace: str,
        identifier: str,
        data: Any,
        ttl: Optional[int] = None,
        params: Optional[Dict] = None,
    ) -> None:
        """
        Store data in cache.

        Args:
            namespace: Cache namespace
            identifier: Unique identifier
            data: Data to cache
            ttl: Time-to-live in seconds (uses default if not provided)
            params: Optional parameters
        """
        key = self._generate_key(namespace, identifier, params)
        ttl = ttl or self.default_ttl

        with self._lock:
            self._cache[key] = {
                "data": data,
                "created_at": time.time(),
                "expires_at": time.time() + ttl,
                "ttl": ttl,
            }
            self._stats["sets"] += 1
            self.logger.debug(f"Cache set: {key} (TTL: {ttl}s)")

    def invalidate(
        self, namespace: Optional[str] = None, identifier: Optional[str] = None
    ) -> int:
        """
        Invalidate cache entries.

        Args:
            namespace: If provided, invalidate all entries in namespace
            identifier: If provided (with namespace), invalidate specific entry

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            if namespace is None:
                # Clear all cache
                count = len(self._cache)
                self._cache.clear()
                self._stats["invalidations"] += count
                self.logger.info("Cache cleared completely")
                return count

            if identifier is None:
                # Clear all entries in namespace
                keys_to_remove = [
                    k for k in self._cache.keys() if k.startswith(f"{namespace}:")
                ]
                count = len(keys_to_remove)
                for key in keys_to_remove:
                    del self._cache[key]
                self._stats["invalidations"] += count
                self.logger.info(
                    f"Cache cleared for namespace: {namespace} ({count} entries)"
                )
                return count

            # Clear specific entry
            key = self._generate_key(namespace, identifier)
            if key in self._cache:
                del self._cache[key]
                self._stats["invalidations"] += 1
                self.logger.info(f"Cache invalidated: {key}")
                return 1

            return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary containing cache statistics
        """
        with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (
                (self._stats["hits"] / total_requests * 100)
                if total_requests > 0
                else 0
            )

            return {
                "entries": len(self._cache),
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": round(hit_rate, 2),
                "sets": self._stats["sets"],
                "invalidations": self._stats["invalidations"],
                "expirations": self._stats["expirations"],
            }

    def _cleanup_expired(self) -> None:
        """Background thread to clean up expired cache entries."""
        while True:
            try:
                time.sleep(60)  # Run cleanup every minute
                current_time = time.time()
                expired_keys = []

                with self._lock:
                    for key, entry in self._cache.items():
                        if entry["expires_at"] < current_time:
                            expired_keys.append(key)

                    for key in expired_keys:
                        del self._cache[key]

                    if expired_keys:
                        self._stats["expirations"] += len(expired_keys)
                        self.logger.debug(
                            f"Cleaned up {len(expired_keys)} expired entries"
                        )

            except Exception as e:
                self.logger.error(f"Error in cache cleanup: {e}")


# Global cache instance
_cache_instance: Optional[CacheService] = None
_cache_lock = threading.Lock()


def get_cache_service(default_ttl: int = 300) -> CacheService:
    """
    Get or create the global cache service instance.

    Args:
        default_ttl: Default TTL in seconds

    Returns:
        CacheService instance
    """
    global _cache_instance

    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = CacheService(default_ttl=default_ttl)

    return _cache_instance
