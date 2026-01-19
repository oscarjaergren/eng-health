"""
Refactored Azure DevOps API client with base client integration.

This module provides a client for interacting with the Azure DevOps API,
built on top of the BaseAPIClient class for common functionality.
"""

import asyncio
import base64
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Union

import aiohttp
import requests
from requests.exceptions import ConnectionError, RequestException, Timeout

from .base_client import BaseAPIClient

class AzureDevOpsClient(BaseAPIClient):
    """
    Client for interacting with Azure DevOps API.

    This client provides methods to fetch repositories, pull requests, and related data
    from Azure DevOps using the REST API. It inherits common functionality from
    BaseAPIClient and implements Azure DevOps specific behavior.
    """

    API_VERSION = "7.1"
    BASE_URL = "https://dev.azure.com"

    def __init__(
        self,
        config: Any,
        logger: logging.Logger,
        enable_cache: bool = True,
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        """
        Initialize the Azure DevOps client.

        Args:
            config: Configuration object with Azure DevOps settings
            logger: Logger instance for structured logging
            enable_cache: Whether to enable response caching
            max_retries: Maximum number of retry attempts for failed requests
            timeout: Request timeout in seconds

        Raises:
            ValueError: If required configuration is missing
        """
        super().__init__(
            config=config,
            logger=logger,
            cache_dir=".cache/azure_devops",
            enable_cache=enable_cache,
            max_retries=max_retries,
            timeout=timeout,
        )

        # Setup authentication
        self._setup_auth()

        # Rate limiting
        self.rate_limit_remaining = 10000  # Azure DevOps has a high default limit
        self.rate_limit_reset = time.time() + 3600  # Default to 1 hour
        self.rate_limit_lock = None  # Not needed for Azure DevOps basic auth

    def _get_default_headers(self) -> Dict[str, str]:
        """Get the default headers for Azure DevOps API requests."""
        return {
            "Content-Type": "application/json",
            "Accept": f"application/json; api-version={self.API_VERSION}",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def _setup_auth(self) -> None:
        """Set up authentication for Azure DevOps API."""
        if not hasattr(self.config, "token") or not self.config.token:
            raise ValueError("Azure DevOps personal access token is required")

        # Encode PAT for basic auth
        pat_encoded = base64.b64encode(f":{self.config.token}".encode()).decode()
        self.session.headers["Authorization"] = f"Basic {pat_encoded}"

    def _build_url(self, organization: str, path: str) -> str:
        """
        Build a full Azure DevOps API URL.

        Args:
            organization: Azure DevOps organization name
            path: API path (without leading slash)

        Returns:
            Full API URL
        """
        # The path already includes _apis/ so we don't need to add it again
        return f"{self.BASE_URL}/{organization}/{path}"

    def _check_rate_limit(self) -> None:
        """Check rate limits and sleep if necessary."""
        current_time = time.time()

        # If we've hit the rate limit, wait until the reset time
        if self.rate_limit_remaining <= 0 and current_time < self.rate_limit_reset:
            sleep_time = self.rate_limit_reset - current_time + 1  # Add 1s buffer
            self.logger.warning(
                f"Rate limit reached. Sleeping for {sleep_time:.1f} seconds"
            )
            time.sleep(sleep_time)

    def _update_rate_limit_headers(self, response: requests.Response) -> None:
        """
        Update rate limit information from response headers.

        Args:
            response: Response object from API request
        """
        if "X-RateLimit-Remaining" in response.headers:
            self.rate_limit_remaining = int(
                response.headers.get("X-RateLimit-Remaining", 10000)
            )

        if "X-RateLimit-Reset" in response.headers:
            self.rate_limit_reset = int(
                response.headers.get("X-RateLimit-Reset", time.time() + 3600)
            )

    def _make_request(
        self, method: str, url: str, **kwargs
    ) -> Optional[requests.Response]:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: URL to request
            **kwargs: Additional arguments to pass to requests.request()

        Returns:
            Response object or None if all retries failed
        """
        # Add default headers if not provided
        headers = kwargs.pop("headers", {})
        headers.update(self._get_default_headers())

        # Add API version if not provided
        params = kwargs.pop("params", {})
        if "api-version" not in params:
            params["api-version"] = self.API_VERSION

        # Add timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        # Make the request with retries
        for attempt in range(self.max_retries + 1):
            try:
                self.logger.debug(
                    "Making %s request to %s with params: %s", method, url, params
                )
                response = self.session.request(
                    method=method, url=url, headers=headers, params=params, **kwargs
                )

                # Update rate limit information
                self._update_rate_limit_headers(response)

                # Check for rate limiting
                if response.status_code == 429:
                    self._handle_rate_limit(response)
                    if attempt < self.max_retries:
                        continue

                # Check for authentication errors
                if response.status_code in (401, 403):
                    self.logger.error("Authentication failed: %s", response.text)
                    response.raise_for_status()

                # For successful responses, ensure we can parse the JSON
                if 200 <= response.status_code < 300:
                    try:
                        response.json()  # Try to parse JSON to catch any JSON decode errors
                    except json.JSONDecodeError as e:
                        self.logger.error("Failed to parse JSON response: %s", str(e))
                        if attempt < self.max_retries:
                            continue

                return response

            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                self.logger.error(
                    "Request error (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    str(e),
                )
                if attempt == self.max_retries:
                    if isinstance(e, requests.exceptions.ConnectionError):
                        self.logger.error(
                            "Connection error after %d attempts", attempt + 1
                        )
                        raise
                    return None
                elif response.status_code == 404:
                    # Not found is not a retry-able error
                    return response
                elif response.status_code == 429:
                    # Rate limiting
                    retry_after = int(response.headers.get("Retry-After", 60))
                    self.logger.warning(f"Rate limited. Waiting {retry_after} seconds")
                    time.sleep(retry_after)
                    continue
                else:
                    self.logger.warning(
                        f"Request failed with status {response.status_code}, "
                        f"attempt {attempt + 1}/{self.max_retries + 1}"
                    )
                    if attempt < self.max_retries:
                        time.sleep(2**attempt)  # Exponential backoff

            except Timeout as e:
                self.logger.warning(
                    f"Request timeout: {e}, attempt {attempt + 1}/{self.max_retries + 1}"
                )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
            except ConnectionError as e:
                self.logger.warning(
                    f"Connection error: {e}, attempt {attempt + 1}/{self.max_retries + 1}"
                )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
            except RequestException as e:
                self.logger.warning(
                    f"Request exception: {e}, attempt {attempt + 1}/{self.max_retries + 1}"
                )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)

        return None

    def fetch_all_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories from all projects in the Azure DevOps organization."""
        try:
            self.logger.info(
                "Fetching repositories from all Azure DevOps projects in organization..."
            )

            response = self._make_request("GET", self.config.repositories_url)

            if not response or response.status_code != 200:
                if response:
                    self.logger.error(
                        f"Failed to fetch repositories: {response.status_code}"
                    )
                    self.logger.error(f"Response: {response.text}")
                else:
                    self.logger.error(
                        "Failed to fetch repositories: No response received"
                    )
                return []

            repos_data = response.json()
            repositories = repos_data.get("value", [])

            self.logger.info(
                f"Found {len(repositories)} repositories across all projects in organization"
            )

            for repo in repositories:
                repo_name = repo.get("name", "Unknown")
                repo_id = repo.get("id", "Unknown")
                project_name = repo.get("project", {}).get("name", "Unknown")
                self.logger.info(f"  - {repo_name} in {project_name} (ID: {repo_id})")

            return repositories

        except Exception as e:
            self.logger.error(f"Error fetching repositories: {e}")
            return []

    def fetch_pull_requests_for_repository(
        self, repository: Dict[str, Any], fetch_threads: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Fetch pull requests for a repository with pagination support.

        Args:
            repository: Repository dictionary containing id, name, and project info
            fetch_threads: Whether to fetch threads for each PR (needed for historical approvals)

        Returns:
            List of pull request objects from all pages
        """
        all_pull_requests = []
        current_skip = 0
        top = 100

        # Extract repository details
        repo_id = repository.get("id")
        project_name = repository.get("project", {}).get("name")

        if not repo_id or not project_name:
            self.logger.error("Repository missing required fields (id or project.name)")
            return []

        while True:
            # Make API request for the current page
            path = f"{project_name}/_apis/git/repositories/{repo_id}/pullrequests"
            params = {
                "searchCriteria.status": "all",
                "$top": top,
                "$skip": current_skip,
                "api-version": self.API_VERSION,
            }

            url = f"{self.BASE_URL}/{self.config.organization}/{path}"
            response = self._make_request("GET", url, params=params)

            # Handle response
            if not response or response.status_code != 200:
                break

            data = response.json()
            pull_requests = data.get("value", [])

            # If no more PRs, we're done
            if not pull_requests:
                break

            # Parallel thread fetching for much better performance
            if fetch_threads and pull_requests:
                self._fetch_threads_parallel(pull_requests, repo_id)

            # Add PRs from this page to our results
            all_pull_requests.extend(pull_requests)

            # If we got fewer PRs than the page size, we've reached the end
            if len(pull_requests) < top:
                break

            # Update skip for the next page
            current_skip += len(pull_requests)

            # Continue to next page to get more results
            continue

        return all_pull_requests

    def _fetch_threads_parallel(
        self, pull_requests: List[Dict[str, Any]], repo_id: str
    ) -> None:
        """Fetch threads for multiple PRs using async I/O for maximum performance."""
        if not pull_requests:
            return
        
        try:
            # Try to use existing event loop or create new one
            try:
                loop = asyncio.get_running_loop()
                # If we're already in an async context, use thread pool fallback
                self._fetch_threads_threaded(pull_requests, repo_id)
            except RuntimeError:
                # No running loop, we can create one
                asyncio.run(self._fetch_threads_async(pull_requests, repo_id))
        except Exception:
            # Fallback to threaded approach
            self._fetch_threads_threaded(pull_requests, repo_id)
    
    def _fetch_threads_threaded(
        self, pull_requests: List[Dict[str, Any]], repo_id: str
    ) -> None:
        """Fallback threaded implementation for thread fetching."""
        def fetch_single_thread(pr: Dict[str, Any]) -> None:
            pr_id = pr.get("pullRequestId")
            if pr_id:
                pr["threads"] = self._fetch_pr_threads(repo_id, pr_id)

        max_thread_workers = min(20, len(pull_requests))
        with ThreadPoolExecutor(max_workers=max_thread_workers) as executor:
            executor.map(fetch_single_thread, pull_requests)

    async def _fetch_threads_async(
        self, pull_requests: List[Dict[str, Any]], repo_id: str
    ) -> None:
        """Async implementation for fetching threads - much faster for I/O bound work."""
        pat_encoded = base64.b64encode(f":{self.config.token}".encode()).decode()
        headers = {
            "Authorization": f"Basic {pat_encoded}",
            "Accept": "application/json; api-version=7.1",
            "Accept-Encoding": "gzip, deflate",
        }
        
        connector = aiohttp.TCPConnector(
            limit=50,  # Max concurrent connections
            limit_per_host=50,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        
        async with aiohttp.ClientSession(
            connector=connector, 
            headers=headers,
            timeout=timeout
        ) as session:
            tasks = []
            for pr in pull_requests:
                pr_id = pr.get("pullRequestId")
                if pr_id:
                    tasks.append(self._fetch_single_thread_async(session, pr, repo_id, pr_id))
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _fetch_single_thread_async(
        self, 
        session: aiohttp.ClientSession, 
        pr: Dict[str, Any], 
        repo_id: str, 
        pr_id: int
    ) -> None:
        """Fetch threads for a single PR asynchronously."""
        try:
            url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/threads?api-version=7.1"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    pr["threads"] = data.get("value", [])
                else:
                    pr["threads"] = []
        except Exception:
            pr["threads"] = []

    def get_pull_request_details(
        self,
        organization: str,
        project: str,
        repository: str,
        pull_request_id: Union[str, int],
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific pull request.

        Args:
            organization: Azure DevOps organization name
            project: Project name
            repository: Repository name or ID
            pull_request_id: ID of the pull request

        Returns:
            Pull request details or None if not found
        """
        path = f"{project}/_apis/git/repositories/{repository}/pullrequests/{pull_request_id}"
        params = {
            "api-version": self.API_VERSION,
        }

        url = self._build_url(organization, path)
        response = self._make_request("GET", url, params=params)

        if response and response.status_code == 200:
            return response.json()

        return None

    def get_pull_request_commits(
        self,
        organization: str,
        project: str,
        repository: str,
        pull_request_id: Union[str, int],
    ) -> List[Dict[str, Any]]:
        """Fetch commits for a specific pull request."""
        path = f"{project}/_apis/git/repositories/{repository}/pullRequests/{pull_request_id}/commits"
        params = {"api-version": self.API_VERSION}

        url = f"{self.BASE_URL}/{organization}/{path}"
        response = self._make_request("GET", url, params=params)

        if response and response.status_code == 200:
            data = response.json()
            return data.get("value", [])

        return []

    def _fetch_single_pr_details(
        self, pr: Dict[str, Any], repo_id: str
    ) -> Dict[str, Any]:
        """Fetch detailed information for a single PR."""
        pr_id = pr.get("pullRequestId")
        details = {}

        if pr_id:
            # Fetch threads and iterations concurrently
            with ThreadPoolExecutor(max_workers=2) as executor:
                threads_future = executor.submit(self._fetch_pr_threads, repo_id, pr_id)
                iterations_future = executor.submit(
                    self._fetch_pr_iterations, repo_id, pr_id
                )

                details["threads"] = threads_future.result()
                details["iterations"] = iterations_future.result()
        else:
            details["threads"] = []
            details["iterations"] = []

        return details

    def _fetch_pr_threads(self, repo_id: str, pr_id: int) -> List[Dict[str, Any]]:
        """Fetch all threads (comments and discussions) for a specific PR."""
        try:
            threads_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/threads?api-version=7.1"
            response = self.session.get(threads_url, timeout=5)
            if response.status_code == 200:
                return response.json().get("value", [])
            return []
        except Exception:
            return []

    def _fetch_pr_iterations(self, repo_id: str, pr_id: int) -> List[Dict[str, Any]]:
        """Fetch all iterations for a specific PR."""
        try:
            # Construct URL for PR iterations using organization-level API
            iterations_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/iterations"

            params = {"api-version": "7.1", "searchCriteria.status": "all"}
            response = self.session.get(
                iterations_url, params=params, timeout=10
            )  # Reduced timeout
            if response.status_code == 200:
                iterations_data = response.json()
                return iterations_data.get("value", [])
            else:
                return []
        except Exception:
            return []
