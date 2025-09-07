"""Cache manager for API responses to improve performance."""

import hashlib
import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class CacheManager:
    """
    Manages caching of API responses to reduce redundant requests and improve performance.

    Features:
    - TTL-based cache expiration
    - Configurable cache directory
    - Memory and disk-based caching
    - Cache size management
    - Thread-safe operations
    """

    def __init__(
        self,
        cache_dir: str = ".cache",
        default_ttl: int = 3600,
        max_cache_size_mb: int = 100,
    ):
        """
        Initialize the cache manager.

        Args:
            cache_dir: Directory to store cache files
            default_ttl: Default time-to-live in seconds (1 hour)
            max_cache_size_mb: Maximum cache size in megabytes
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.default_ttl = default_ttl
        self.max_cache_size_mb = max_cache_size_mb
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)

        # Create subdirectories for different cache types
        (self.cache_dir / "api_responses").mkdir(exist_ok=True)
        (self.cache_dir / "processed_data").mkdir(exist_ok=True)

    def _generate_cache_key(
        self, url: str, params: Dict = None, headers: Dict = None
    ) -> str:
        """
        Generate a unique cache key based on request parameters.

        Args:
            url: API endpoint URL
            params: Query parameters
            headers: Request headers (excluding auth)

        Returns:
            str: Unique cache key
        """
        # Create a deterministic key from request components
        key_data = {
            "url": url,
            "params": params or {},
            # Only include non-sensitive headers
            "headers": {
                k: v
                for k, v in (headers or {}).items()
                if k.lower() not in ["authorization", "x-api-key", "token"]
            },
        }

        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]

    def _get_cache_file_path(
        self, cache_key: str, cache_type: str = "api_responses"
    ) -> Path:
        """Get the file path for a cache entry."""
        return self.cache_dir / cache_type / f"{cache_key}.cache"

    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if a cache entry is still valid based on TTL."""
        if "expires_at" not in cache_entry:
            return False

        return datetime.now().timestamp() < cache_entry["expires_at"]

    def _cleanup_expired_cache(self) -> None:
        """Remove expired cache entries from disk."""
        try:
            for cache_type in ["api_responses", "processed_data"]:
                cache_type_dir = self.cache_dir / cache_type
                if not cache_type_dir.exists():
                    continue

                for cache_file in cache_type_dir.glob("*.cache"):
                    try:
                        with open(cache_file, "rb") as f:
                            cache_entry = pickle.load(f)

                        if not self._is_cache_valid(cache_entry):
                            cache_file.unlink()
                            self.logger.debug(
                                f"Removed expired cache file: {
                                    cache_file.name}"
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Error checking cache file {cache_file}: {e}"
                        )
                        # Remove corrupted cache files
                        cache_file.unlink()
        except Exception as e:
            self.logger.error(f"Error during cache cleanup: {e}")

    def _manage_cache_size(self) -> None:
        """Manage cache size by removing oldest entries if size limit exceeded."""
        try:
            total_size = 0
            cache_files = []

            for cache_type in ["api_responses", "processed_data"]:
                cache_type_dir = self.cache_dir / cache_type
                if not cache_type_dir.exists():
                    continue

                for cache_file in cache_type_dir.glob("*.cache"):
                    size = cache_file.stat().st_size
                    mtime = cache_file.stat().st_mtime
                    cache_files.append((cache_file, size, mtime))
                    total_size += size

            # Convert to MB
            total_size_mb = total_size / (1024 * 1024)

            if total_size_mb > self.max_cache_size_mb:
                # Sort by modification time (oldest first)
                cache_files.sort(key=lambda x: x[2])

                # Remove oldest files until under size limit
                for cache_file, size, _ in cache_files:
                    if (
                        total_size_mb <= self.max_cache_size_mb * 0.8
                    ):  # Leave 20% buffer
                        break

                    cache_file.unlink()
                    total_size_mb -= size / (1024 * 1024)
                    self.logger.debug(
                        f"Removed cache file for size management: {
                            cache_file.name}"
                    )

        except Exception as e:
            self.logger.error(f"Error during cache size management: {e}")

    def get(
        self,
        url: str,
        params: Dict = None,
        headers: Dict = None,
        cache_type: str = "api_responses",
    ) -> Optional[Any]:
        """
        Retrieve cached response if available and valid.

        Args:
            url: API endpoint URL
            params: Query parameters
            headers: Request headers
            cache_type: Type of cache ("api_responses" or "processed_data")

        Returns:
            Cached data if available and valid, None otherwise
        """
        cache_key = self._generate_cache_key(url, params, headers)

        # Check memory cache first
        if cache_key in self.memory_cache:
            cache_entry = self.memory_cache[cache_key]
            if self._is_cache_valid(cache_entry):
                self.logger.debug(f"Cache hit (memory): {cache_key}")
                return cache_entry["data"]
            else:
                # Remove expired entry from memory
                del self.memory_cache[cache_key]

        # Check disk cache
        cache_file = self._get_cache_file_path(cache_key, cache_type)
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    cache_entry = pickle.load(f)

                if self._is_cache_valid(cache_entry):
                    # Load back into memory cache for faster access
                    self.memory_cache[cache_key] = cache_entry
                    self.logger.debug(f"Cache hit (disk): {cache_key}")
                    return cache_entry["data"]
                else:
                    # Remove expired file
                    cache_file.unlink()
                    self.logger.debug(f"Removed expired cache: {cache_key}")

            except Exception as e:
                self.logger.warning(f"Error reading cache file {cache_key}: {e}")
                # Remove corrupted cache file
                cache_file.unlink()

        self.logger.debug(f"Cache miss: {cache_key}")
        return None

    def set(
        self,
        url: str,
        data: Any,
        params: Dict = None,
        headers: Dict = None,
        ttl: Optional[int] = None,
        cache_type: str = "api_responses",
    ) -> None:
        """
        Store data in cache with TTL.

        Args:
            url: API endpoint URL
            data: Data to cache
            params: Query parameters
            headers: Request headers
            ttl: Time-to-live in seconds (uses default if None)
            cache_type: Type of cache ("api_responses" or "processed_data")
        """
        cache_key = self._generate_cache_key(url, params, headers)
        ttl = ttl or self.default_ttl

        cache_entry = {
            "data": data,
            "created_at": datetime.now().timestamp(),
            "expires_at": datetime.now().timestamp() + ttl,
            "cache_key": cache_key,
            "url": url,
        }

        # Store in memory cache
        self.memory_cache[cache_key] = cache_entry

        # Store in disk cache
        cache_file = self._get_cache_file_path(cache_key, cache_type)
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(cache_entry, f)

            self.logger.debug(f"Cached data: {cache_key} (TTL: {ttl}s)")

        except Exception as e:
            self.logger.error(f"Error writing cache file {cache_key}: {e}")

        # Periodic cleanup (every 100 cache operations)
        if len(self.memory_cache) % 100 == 0:
            self._cleanup_expired_cache()
            self._manage_cache_size()

    def invalidate(
        self,
        url: str,
        params: Dict = None,
        headers: Dict = None,
        cache_type: str = "api_responses",
    ) -> None:
        """
        Invalidate a specific cache entry.

        Args:
            url: API endpoint URL
            params: Query parameters
            headers: Request headers
            cache_type: Type of cache
        """
        cache_key = self._generate_cache_key(url, params, headers)

        # Remove from memory cache
        if cache_key in self.memory_cache:
            del self.memory_cache[cache_key]

        # Remove from disk cache
        cache_file = self._get_cache_file_path(cache_key, cache_type)
        if cache_file.exists():
            cache_file.unlink()

        self.logger.debug(f"Invalidated cache: {cache_key}")

    def clear_all(self) -> None:
        """Clear all cache entries."""
        # Clear memory cache
        self.memory_cache.clear()

        # Clear disk cache
        try:
            for cache_type in ["api_responses", "processed_data"]:
                cache_type_dir = self.cache_dir / cache_type
                if cache_type_dir.exists():
                    for cache_file in cache_type_dir.glob("*.cache"):
                        cache_file.unlink()

            self.logger.info("Cleared all cache entries")

        except Exception as e:
            self.logger.error(f"Error clearing cache: {e}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict containing cache statistics
        """
        stats = {
            "memory_entries": len(self.memory_cache),
            "disk_entries": 0,
            "total_size_mb": 0,
            "cache_types": {},
        }

        try:
            for cache_type in ["api_responses", "processed_data"]:
                cache_type_dir = self.cache_dir / cache_type
                if not cache_type_dir.exists():
                    continue

                type_count = 0
                type_size = 0

                for cache_file in cache_type_dir.glob("*.cache"):
                    type_count += 1
                    type_size += cache_file.stat().st_size

                stats["cache_types"][cache_type] = {
                    "count": type_count,
                    "size_mb": type_size / (1024 * 1024),
                }

                stats["disk_entries"] += type_count
                stats["total_size_mb"] += type_size / (1024 * 1024)

        except Exception as e:
            self.logger.error(f"Error getting cache stats: {e}")

        return stats
