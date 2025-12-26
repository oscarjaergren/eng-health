"""
Tests for cache manager functionality.
"""

import time
from pathlib import Path

import pytest

from pr_analytics.utils.cache_manager import CacheManager


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create temporary cache directory."""
    cache_dir = tmp_path / "test_cache"
    return str(cache_dir)


@pytest.fixture
def cache_manager(temp_cache_dir):
    """Create CacheManager instance for testing."""
    return CacheManager(
        cache_dir=temp_cache_dir, default_ttl=3600, max_cache_size_mb=10
    )


class TestCacheManagerInitialization:
    """Test cache manager initialization."""

    def test_initialization(self, temp_cache_dir):
        """Test cache manager initializes correctly."""
        manager = CacheManager(cache_dir=temp_cache_dir)
        assert manager.cache_dir == Path(temp_cache_dir)
        assert manager.default_ttl == 3600
        assert manager.max_cache_size_mb == 100
        assert len(manager.memory_cache) == 0

    def test_creates_cache_directories(self, temp_cache_dir):
        """Test cache manager creates necessary directories."""
        manager = CacheManager(cache_dir=temp_cache_dir)
        assert (manager.cache_dir / "api_responses").exists()
        assert (manager.cache_dir / "processed_data").exists()


class TestCacheManagerKeyGeneration:
    """Test cache key generation."""

    def test_generate_cache_key_basic(self, cache_manager):
        """Test basic cache key generation."""
        key1 = cache_manager._generate_cache_key("https://api.example.com/data")
        key2 = cache_manager._generate_cache_key("https://api.example.com/data")
        assert key1 == key2
        assert len(key1) == 16

    def test_generate_cache_key_with_params(self, cache_manager):
        """Test cache key generation with parameters."""
        key1 = cache_manager._generate_cache_key(
            "https://api.example.com/data", params={"page": 1, "limit": 10}
        )
        key2 = cache_manager._generate_cache_key(
            "https://api.example.com/data", params={"page": 1, "limit": 10}
        )
        key3 = cache_manager._generate_cache_key(
            "https://api.example.com/data", params={"page": 2, "limit": 10}
        )

        assert key1 == key2
        assert key1 != key3

    def test_generate_cache_key_excludes_auth_headers(self, cache_manager):
        """Test cache key excludes sensitive headers."""
        key1 = cache_manager._generate_cache_key(
            "https://api.example.com/data",
            headers={
                "Authorization": "Bearer token123",
                "Content-Type": "application/json",
            },
        )
        key2 = cache_manager._generate_cache_key(
            "https://api.example.com/data",
            headers={
                "Authorization": "Bearer different",
                "Content-Type": "application/json",
            },
        )

        # Keys should be same since Authorization is excluded
        assert key1 == key2


class TestCacheManagerSetGet:
    """Test cache set and get operations."""

    def test_set_and_get_cache(self, cache_manager):
        """Test setting and getting cache."""
        url = "https://api.example.com/data"
        data = {"result": "test data"}

        cache_manager.set(url, data)
        cached_data = cache_manager.get(url)

        assert cached_data == data

    def test_get_nonexistent_cache(self, cache_manager):
        """Test getting non-existent cache returns None."""
        result = cache_manager.get("https://api.example.com/nonexistent")
        assert result is None

    def test_cache_with_params(self, cache_manager):
        """Test caching with parameters."""
        url = "https://api.example.com/data"
        params = {"page": 1}
        data = {"page": 1, "items": [1, 2, 3]}

        cache_manager.set(url, data, params=params)
        cached_data = cache_manager.get(url, params=params)

        assert cached_data == data

    def test_cache_different_params_different_entries(self, cache_manager):
        """Test different params create different cache entries."""
        url = "https://api.example.com/data"

        cache_manager.set(url, {"page": 1}, params={"page": 1})
        cache_manager.set(url, {"page": 2}, params={"page": 2})

        data1 = cache_manager.get(url, params={"page": 1})
        data2 = cache_manager.get(url, params={"page": 2})

        assert data1 == {"page": 1}
        assert data2 == {"page": 2}

    def test_cache_with_custom_ttl(self, cache_manager):
        """Test caching with custom TTL."""
        url = "https://api.example.com/data"
        data = {"test": "data"}

        cache_manager.set(url, data, ttl=1)  # 1 second TTL

        # Should be cached immediately
        assert cache_manager.get(url) == data

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache_manager.get(url) is None


class TestCacheManagerMemoryAndDisk:
    """Test memory and disk cache interaction."""

    def test_memory_cache_hit(self, cache_manager):
        """Test memory cache is checked first."""
        url = "https://api.example.com/data"
        data = {"test": "data"}

        cache_manager.set(url, data)

        # First get should hit memory cache
        result = cache_manager.get(url)
        assert result == data
        assert len(cache_manager.memory_cache) > 0

    def test_disk_cache_loaded_to_memory(self, cache_manager):
        """Test disk cache is loaded to memory on access."""
        url = "https://api.example.com/data"
        data = {"test": "data"}

        cache_manager.set(url, data)

        # Clear memory cache
        cache_manager.memory_cache.clear()

        # Get should load from disk to memory
        result = cache_manager.get(url)
        assert result == data
        assert len(cache_manager.memory_cache) > 0


class TestCacheManagerInvalidation:
    """Test cache invalidation."""

    def test_invalidate_specific_entry(self, cache_manager):
        """Test invalidating specific cache entry."""
        url = "https://api.example.com/data"
        data = {"test": "data"}

        cache_manager.set(url, data)
        assert cache_manager.get(url) == data

        cache_manager.invalidate(url)
        assert cache_manager.get(url) is None

    def test_clear_all_cache(self, cache_manager):
        """Test clearing all cache entries."""
        cache_manager.set("https://api.example.com/data1", {"data": 1})
        cache_manager.set("https://api.example.com/data2", {"data": 2})
        cache_manager.set("https://api.example.com/data3", {"data": 3})

        assert len(cache_manager.memory_cache) == 3

        cache_manager.clear_all()

        assert len(cache_manager.memory_cache) == 0
        assert cache_manager.get("https://api.example.com/data1") is None
        assert cache_manager.get("https://api.example.com/data2") is None


class TestCacheManagerStats:
    """Test cache statistics."""

    def test_get_cache_stats_empty(self, cache_manager):
        """Test getting stats for empty cache."""
        stats = cache_manager.get_cache_stats()

        assert stats["memory_entries"] == 0
        assert stats["disk_entries"] == 0
        assert stats["total_size_mb"] == 0

    def test_get_cache_stats_with_data(self, cache_manager):
        """Test getting stats with cached data."""
        cache_manager.set("https://api.example.com/data1", {"data": 1})
        cache_manager.set("https://api.example.com/data2", {"data": 2})

        stats = cache_manager.get_cache_stats()

        assert stats["memory_entries"] == 2
        assert stats["disk_entries"] >= 2
        assert stats["total_size_mb"] > 0


class TestCacheManagerCacheTypes:
    """Test different cache types."""

    def test_api_responses_cache_type(self, cache_manager):
        """Test API responses cache type."""
        url = "https://api.example.com/data"
        data = {"response": "data"}

        cache_manager.set(url, data, cache_type="api_responses")
        result = cache_manager.get(url, cache_type="api_responses")

        assert result == data

    def test_processed_data_cache_type(self, cache_manager):
        """Test processed data cache type."""
        url = "processed_key"
        data = {"processed": "data"}

        cache_manager.set(url, data, cache_type="processed_data")
        result = cache_manager.get(url, cache_type="processed_data")

        assert result == data

    def test_different_cache_types_isolated(self, cache_manager):
        """Test different cache types are stored in different directories."""
        url1 = "https://api.example.com/data1"
        url2 = "https://api.example.com/data2"

        cache_manager.set(url1, {"type": "api"}, cache_type="api_responses")
        cache_manager.set(url2, {"type": "processed"}, cache_type="processed_data")

        api_data = cache_manager.get(url1, cache_type="api_responses")
        processed_data = cache_manager.get(url2, cache_type="processed_data")

        assert api_data == {"type": "api"}
        assert processed_data == {"type": "processed"}

        # Verify they're in different directories
        stats = cache_manager.get_cache_stats()
        assert "api_responses" in stats["cache_types"]
        assert "processed_data" in stats["cache_types"]


class TestCacheManagerExpiration:
    """Test cache expiration handling."""

    def test_expired_cache_not_returned(self, cache_manager):
        """Test expired cache entries are not returned."""
        url = "https://api.example.com/data"
        data = {"test": "data"}

        cache_manager.set(url, data, ttl=1)

        # Should be cached
        assert cache_manager.get(url) == data

        # Wait for expiration
        time.sleep(1.1)

        # Should return None
        assert cache_manager.get(url) is None

    def test_expired_cache_removed_from_memory(self, cache_manager):
        """Test expired cache is removed from memory."""
        url = "https://api.example.com/data"
        data = {"test": "data"}

        cache_manager.set(url, data, ttl=1)
        time.sleep(1.1)

        # Access should remove from memory
        cache_manager.get(url)

        cache_key = cache_manager._generate_cache_key(url)
        assert cache_key not in cache_manager.memory_cache
