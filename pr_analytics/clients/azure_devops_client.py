"""
Refactored Azure DevOps API client with base client integration.

This module provides a client for interacting with the Azure DevOps API,
built on top of the BaseAPIClient class for common functionality.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Union

import requests

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
        self,
        repository: Dict[str, Any],
        fetch_threads: bool = True,
        since_date: Optional[str] = None,
        known_pr_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch pull requests for a repository with pagination support.

        Args:
            repository: Repository dictionary containing id, name, and project info
            fetch_threads: Whether to fetch threads for each PR (needed for historical approvals)
            since_date: ISO date string to only fetch PRs created after this date
            known_pr_ids: Set of PR IDs already in cache — thread fetching is skipped for these

        Returns:
            List of pull request objects from all pages
        """
        all_pull_requests = []
        current_skip = 0
        top = 100

        repo_id = repository.get("id")
        project_name = repository.get("project", {}).get("name")

        if not repo_id or not project_name:
            self.logger.error("Repository missing required fields (id or project.name)")
            return []

        known_pr_ids = known_pr_ids or set()

        while True:
            params = {
                "searchCriteria.status": "all",
                "$top": top,
                "$skip": current_skip,
                "api-version": self.API_VERSION,
            }

            if since_date:
                params["searchCriteria.minTime"] = since_date

            # Try project-scoped URL first; fall back to org-scoped if 404
            url = f"{self.BASE_URL}/{self.config.organization}/{project_name}/_apis/git/repositories/{repo_id}/pullrequests"
            response = self._make_request("GET", url, params=params)

            if response is None or response.status_code == 404:
                fallback_url = f"{self.BASE_URL}/{self.config.organization}/_apis/git/repositories/{repo_id}/pullrequests"
                response = self._make_request("GET", fallback_url, params=params)

            # Handle response
            if not response or response.status_code != 200:
                break

            data = response.json()
            pull_requests = data.get("value", [])

            # If no more PRs, we're done
            if not pull_requests:
                break

            # Only fetch threads for PRs not already in cache
            if fetch_threads and pull_requests:
                new_prs = [
                    pr for pr in pull_requests
                    if pr.get("pullRequestId") not in known_pr_ids
                ]
                if new_prs:
                    self._fetch_threads_parallel(new_prs, repo_id)
                # Mark cached PRs so the processor knows threads weren't re-fetched
                for pr in pull_requests:
                    if pr.get("pullRequestId") in known_pr_ids and "threads" not in pr:
                        pr["threads"] = []

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
        import aiohttp

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
            threads_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/threads"
            response = self._make_request("GET", threads_url, params={"api-version": "7.1"}, cache_ttl=0)
            if response and response.status_code == 200:
                return response.json().get("value", [])
            return []
        except Exception:
            return []

    def _fetch_pr_iterations(self, repo_id: str, pr_id: int) -> List[Dict[str, Any]]:
        """Fetch all iterations for a specific PR."""
        try:
            iterations_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/iterations"
            params = {"api-version": "7.1", "searchCriteria.status": "all"}
            response = self._make_request("GET", iterations_url, params=params, cache_ttl=0)
            if response and response.status_code == 200:
                return response.json().get("value", [])
            return []
        except Exception:
            return []
