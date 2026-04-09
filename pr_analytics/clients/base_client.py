"""
Base API client with common functionality for all API clients.

This module provides a base class with shared functionality for making HTTP requests,
handling rate limits, and managing caching.
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.cache_manager import CacheManager

T = TypeVar("T")


class _CachedResponse:
    """Minimal response-like wrapper for cached API JSON data."""

    def __init__(self, data: Any) -> None:
        self._data = data
        self.status_code = 200

    def json(self) -> Any:
        return self._data


class BaseAPIClient(ABC):
    """
    Base class for API clients with common functionality.

    This class provides shared functionality for making HTTP requests, handling rate limits,
    caching, and parallel processing. Concrete API clients should inherit from this class
    and implement the abstract methods.
    """

    def __init__(
        self,
        config: Any,
        logger: logging.Logger,
        cache_dir: str,
        enable_cache: bool = True,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        """
        Initialize the base API client.

        Args:
            config: Configuration object containing API settings
            logger: Logger instance for structured logging
            cache_dir: Directory to store cached responses
            enable_cache: Whether to enable response caching
            max_retries: Maximum number of retry attempts for failed requests
            timeout: Default request timeout in seconds
        """
        self.config = config
        self.logger = logger
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = self._create_session()

        # Performance settings
        max_parallel = getattr(config, "max_parallel_workers", 10)
        # Ensure we have an integer value (handle case where config is a Mock)
        max_parallel = max_parallel if isinstance(max_parallel, int) else 10
        self.max_workers = min(max_parallel, (os.cpu_count() or 1) * 4)

        # Rate limiting
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = time.time()
        self.rate_limit_lock = None  # To be initialized in child class if needed

        # Cache management
        self.cache_manager = CacheManager(cache_dir=cache_dir) if enable_cache else None

    def _create_session(self) -> requests.Session:
        """
        Create a requests session with retry strategy and default headers.

        Returns:
            Configured requests.Session instance
        """
        session = requests.Session()

        # Setup retry strategy
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        # Configure adapter with larger connection pooling for parallel requests
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=30,
            pool_maxsize=30,
            pool_block=False,
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set default headers
        session.headers.update(self._get_default_headers())

        return session

    @abstractmethod
    def _get_default_headers(self) -> Dict[str, str]:
        """
        Get the default headers for API requests.

        Returns:
            Dictionary of default headers
        """

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        cache_ttl: int = 3600,
        **kwargs,
    ) -> Optional[requests.Response]:
        """
        Make an HTTP request with retry logic and caching.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            params: Query parameters
            data: Form data
            json: JSON data
            headers: Additional headers
            cache_ttl: Cache time-to-live in seconds
            **kwargs: Additional arguments for requests.request()

        Returns:
            Response object or None if request failed
        """
        cache_key = self._generate_cache_key(method, url, params, data, json)

        # Check cache first if enabled and method is GET
        if cache_ttl > 0 and method.upper() == "GET" and self.cache_manager:
            cached_data = self.cache_manager.get(cache_key, max_age=cache_ttl)
            if cached_data is not None:
                self.logger.debug(f"Cache hit for {url}")
                return _CachedResponse(cached_data)

        # Prepare request
        request_headers = {}
        if headers:
            request_headers.update(headers)

        # Handle rate limiting
        self._check_rate_limit()

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json,
                headers=request_headers,
                timeout=self.timeout,
                **kwargs,
            )

            # Update rate limit info
            self._update_rate_limit_headers(response)

            # Check for authentication errors first
            if response.status_code == 401:
                error_msg = "Authentication failed: Invalid or missing credentials"
                try:
                    error_data = response.json()
                    if "message" in error_data:
                        error_msg = f"Authentication failed: {error_data['message']}"
                except ValueError:
                    pass
                raise requests.exceptions.HTTPError(error_msg, response=response)

            # Check for other errors
            response.raise_for_status()

            # Cache successful responses (store parsed JSON, not the Response object)
            if cache_ttl > 0 and method.upper() == "GET" and self.cache_manager:
                try:
                    self.cache_manager.set(cache_key, response.json(), ttl=cache_ttl)
                except Exception:
                    pass  # Skip caching non-JSON or unserializable responses

            return response

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                self.logger.error(f"Authentication failed: {e}")
                raise ValueError(str(e)) from e
            if e.response is not None and e.response.status_code == 404:
                # Return the response so callers can implement fallback logic
                return e.response
            self.logger.error(f"HTTP error: {e}")
            return None

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request failed: {e}")
            return None

    def _generate_cache_key(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json: Optional[Dict] = None,
    ) -> str:
        """
        Generate a cache key for a request.

        Args:
            method: HTTP method
            url: Request URL
            params: Query parameters
            data: Form data
            json: JSON data

        Returns:
            String representation of the cache key
        """
        import hashlib
        import json as json_module

        key_parts = [method.upper(), url]

        if params:
            key_parts.append(json_module.dumps(params, sort_keys=True))
        if data:
            key_parts.append(json_module.dumps(data, sort_keys=True))
        if json:
            key_parts.append(json_module.dumps(json, sort_keys=True))

        key_string = ":".join(str(part) for part in key_parts)
        return hashlib.md5(key_string.encode("utf-8")).hexdigest()

    def _check_rate_limit(self) -> None:
        """
        Check rate limits and sleep if necessary.

        This method should be implemented by subclasses to handle provider-specific
        rate limiting logic.
        """

    def _update_rate_limit_headers(self, response: requests.Response) -> None:
        """
        Update rate limit information from response headers.

        This method should be implemented by subclasses to handle provider-specific
        rate limit headers.

        Args:
            response: Response object from API request
        """

    def _process_in_parallel(
        self,
        items: List[Any],
        process_func: Callable[[Any], T],
        chunk_size: int = 10,
        max_workers: Optional[int] = None,
    ) -> List[T]:
        """
        Process items in parallel using a thread pool.

        Args:
            items: List of items to process
            process_func: Function to call for each item
            chunk_size: Number of items to process in each batch
            max_workers: Maximum number of worker threads (defaults to self.max_workers)

        Returns:
            List of results in the same order as input items
        """
        if not items:
            return []

        max_workers = max_workers or self.max_workers
        results = [None] * len(items)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit tasks in chunks to avoid overwhelming the executor
            for i in range(0, len(items), chunk_size):
                chunk = items[i : i + chunk_size]
                futures = {
                    executor.submit(process_func, item, idx + i): idx + i
                    for idx, item in enumerate(chunk)
                }

                # Process completed futures
                for future in futures:
                    idx = futures[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        self.logger.error(f"Error processing item {idx}: {e}")
                        results[idx] = None

        return results
