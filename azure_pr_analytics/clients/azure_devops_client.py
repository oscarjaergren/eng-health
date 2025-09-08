"""Azure DevOps API client for fetching pull request data."""

import base64
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, RequestException, Timeout
from urllib3.util.retry import Retry

from ..core.config import Config
from ..utils.cache_manager import CacheManager


class AzureDevOpsClient:
    """
    Client for interacting with Azure DevOps API.

    This class provides methods to fetch repositories, pull requests, and related data
    from Azure DevOps using the REST API. It includes caching, retry logic, and
    parallel processing for optimal performance.

    Attributes:
        config (Config): Configuration object containing API credentials and settings
        logger (logging.Logger): Logger instance for structured logging
        session (requests.Session): HTTP session with retry configuration
        max_workers (int): Maximum number of parallel workers for API calls
        cache_manager (Optional[CacheManager]): Cache manager for API responses
    """

    def __init__(
        self, config: Config, logger: logging.Logger, enable_cache: bool = True
    ) -> None:
        """
        Initialize the Azure DevOps client.

        Args:
            config: Configuration object with Azure DevOps settings
            logger: Logger instance for structured logging
            enable_cache: Whether to enable API response caching

        Raises:
            ValueError: If required configuration is missing
        """
        self.config = config
        self.logger = logger
        self.session = self._create_session()

        # Performance settings
        self.max_workers = min(config.max_parallel_workers, (os.cpu_count() or 1) + 4)

        # Cache management
        self.cache_manager = (
            CacheManager(cache_dir=".cache/azure_devops") if enable_cache else None
        )

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy and authentication."""
        session = requests.Session()

        # Setup retry strategy with more aggressive retries for performance
        retry_strategy = Retry(
            total=2,  # Reduced retries for faster failure
            backoff_factor=0.5,  # Faster backoff
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy, pool_connections=100, pool_maxsize=100
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Setup authentication using PAT
        pat_encoded = base64.b64encode(f":{self.config.token}".encode()).decode()
        session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Basic {pat_encoded}",
            }
        )

        return session

    def _make_request_with_retry(
        self, url: str, params: Dict = None, max_retries: int = 3, cache_ttl: int = 3600
    ) -> Optional[requests.Response]:
        """
        Make HTTP request with enhanced error handling, retry logic, and caching.

        Args:
            url: URL to request
            params: Query parameters
            max_retries: Maximum number of retries
            cache_ttl: Cache time-to-live in seconds

        Returns:
            Response object or None if all retries failed
        """
        # Check cache first
        if self.cache_manager:
            cached_response = self.cache_manager.get(url, params)
            if cached_response is not None:
                # Create a mock response object from cached data
                mock_response = requests.Response()
                mock_response.status_code = 200
                mock_response._content = (
                    cached_response.encode()
                    if isinstance(cached_response, str)
                    else str(cached_response).encode()
                )
                return mock_response
        for attempt in range(max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=30)

                if response.status_code == 200:
                    # Cache successful response
                    if self.cache_manager:
                        self.cache_manager.set(
                            url, response.text, params, ttl=cache_ttl
                        )
                    return response
                elif response.status_code == 401:
                    self.logger.error("Authentication failed - check your PAT token")
                    return None
                elif response.status_code == 403:
                    self.logger.error("Access forbidden - insufficient permissions")
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
                        f"attempt {attempt + 1}/{max_retries + 1}"
                    )
                    if attempt < max_retries:
                        time.sleep(2**attempt)  # Exponential backoff

            except Timeout as e:
                self.logger.warning(
                    f"Request timeout: {e}, attempt {attempt + 1}/{max_retries + 1}"
                )
                if attempt < max_retries:
                    time.sleep(2**attempt)
            except ConnectionError as e:
                self.logger.warning(
                    f"Connection error: {e}, attempt {attempt + 1}/{max_retries + 1}"
                )
                if attempt < max_retries:
                    time.sleep(2**attempt)
            except RequestException as e:
                self.logger.warning(
                    f"Request exception: {e}, attempt {attempt + 1}/{max_retries + 1}"
                )
                if attempt < max_retries:
                    time.sleep(2**attempt)

        return None

    def fetch_all_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories in the project."""
        try:
            self.logger.info("Fetching repositories from Azure DevOps...")
            response = self._make_request_with_retry(self.config.repositories_url)

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
                f"Found {len(repositories)} repositories in project '{self.config.project}'"
            )
            for repo in repositories:
                repo_name = repo.get("name", "Unknown")
                repo_id = repo.get("id", "Unknown")
                self.logger.info(f"  - {repo_name} (ID: {repo_id})")  # noqa: E221

            return repositories

        except Exception as e:
            self.logger.error(f"Error fetching repositories: {e}")
            return []

    def fetch_pull_requests_for_repository(
        self, repository: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Fetch all pull requests for a specific repository with detailed information."""
        repo_name = repository.get("name", "Unknown")
        repo_id = repository.get("id", "")

        all_pr_data = []
        continuation_token = None
        page_count = 0

        while True:
            page_count += 1

            # Build URL with continuation token if available
            url = self.config.get_pull_requests_url(repo_id)
            if continuation_token:
                url += f"&continuationToken={continuation_token}"

            try:
                response = self._make_request_with_retry(url)

                if not response or response.status_code != 200:
                    if response and response.status_code == 404:
                        # Repo has no PRs or access denied - log as debug, not
                        # warning
                        self.logger.debug(f"No PRs found for {repo_name} (404)")
                    elif response:
                        self.logger.warning(
                            f"API request failed for {repo_name}: {response.status_code}"
                        )
                    else:
                        self.logger.error(
                            f"Failed to fetch PRs for {repo_name}: No response received"
                        )
                    break

                # Parse JSON response
                pr_data = response.json()
                page_results = pr_data.get("value", [])

                # Enhance each PR with repository information
                for pr in page_results:
                    pr["repository_name"] = repo_name
                    pr["repository_id"] = repo_id

                all_pr_data.extend(page_results)

                if page_results:
                    self.logger.info(
                        f"  Page {page_count}: {len(page_results)} PRs from {repo_name}"
                    )

                # Check for continuation token
                continuation_token = response.headers.get("x-ms-continuationtoken")
                if not continuation_token:
                    break

            except Exception as e:
                self.logger.error(f"Error fetching PRs for repository {repo_name}: {e}")
                break

        # Always fetch detailed information in parallel
        if all_pr_data:
            all_pr_data = self._fetch_pr_details_parallel(
                all_pr_data, repo_id, repo_name
            )

        if all_pr_data:
            self.logger.info(
                f"Repository {repo_name}: {len(all_pr_data)} total PRs fetched"
            )

        return all_pr_data

    def fetch_all_pull_requests(self) -> List[Dict[str, Any]]:
        """Fetch all pull requests from all repositories in the project using parallel processing."""
        # First, fetch all repositories
        repositories = self.fetch_all_repositories()

        if not repositories:
            self.logger.warning("No repositories found in the project")
            return []

        # Fetch PRs from repositories in parallel
        all_pr_data = []
        completed_repos = 0
        total_repos = len(repositories)

        self.logger.info(
            f"Fetching PRs from {total_repos} repositories using {min(self.max_workers, total_repos)} parallel workers..."
        )
        start_time = time.time()

        # Use thread pool for parallel API calls
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, total_repos)
        ) as executor:
            # Submit all repository PR fetch tasks
            future_to_repo = {
                executor.submit(self.fetch_pull_requests_for_repository, repo): repo
                for repo in repositories
            }

            # Collect results as they complete
            for future in as_completed(future_to_repo):
                repo = future_to_repo[future]
                repo_name = repo.get("name", "Unknown")
                completed_repos += 1

                try:
                    repo_prs = future.result()
                    all_pr_data.extend(repo_prs)

                    # Progress reporting
                    elapsed = time.time() - start_time
                    progress = (completed_repos / total_repos) * 100
                    self.logger.info(
                        f"Progress: {completed_repos}/{total_repos} repositories ({progress:.1f}%) - "
                        f"Elapsed: {elapsed:.1f}s - Current: {repo_name}"
                    )

                except Exception as e:
                    self.logger.error(
                        f"Failed to fetch PRs for repository {repo_name}: {e}"
                    )

        elapsed_total = time.time() - start_time
        self.logger.info(
            f"Total pull requests fetched across all repositories: {len(all_pr_data)} "
            f"(completed in {elapsed_total:.1f}s)"
        )
        return all_pr_data

    def _fetch_pr_details_parallel(
        self, pr_data: List[Dict[str, Any]], repo_id: str, repo_name: str
    ) -> List[Dict[str, Any]]:
        """Fetch detailed information (threads and iterations) for PRs in parallel."""
        if not pr_data:
            return pr_data

        # Use a smaller worker pool for detailed fetching to avoid overwhelming
        # the API
        detail_workers = min(8, len(pr_data))

        with ThreadPoolExecutor(max_workers=detail_workers) as executor:
            # Submit tasks for fetching PR details
            future_to_pr = {
                executor.submit(self._fetch_single_pr_details, pr, repo_id): pr
                for pr in pr_data
            }

            # Collect results
            for future in as_completed(future_to_pr):
                pr = future_to_pr[future]
                try:
                    updated_pr = future.result()
                    # Update the original PR data with fetched details
                    pr.update(updated_pr)
                except Exception as e:
                    pr_id = pr.get("pullRequestId", "unknown")
                    self.logger.warning(
                        f"Failed to fetch details for PR {pr_id} in {repo_name}: {e}"
                    )
                    # Set empty defaults so processing doesn't fail
                    pr["threads"] = []
                    pr["iterations"] = []

        return pr_data

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
            # Construct URL for PR threads - base_url already includes project
            threads_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/threads?api-version=7.1"

            response = self.session.get(threads_url, timeout=10)  # Reduced timeout
            if response.status_code == 200:
                threads_data = response.json()
                return threads_data.get("value", [])
            else:
                return []
        except Exception:
            return []

    def _fetch_pr_iterations(self, repo_id: str, pr_id: int) -> List[Dict[str, Any]]:
        """Fetch all iterations for a specific PR."""
        try:
            # Construct URL for PR iterations - base_url already includes
            # project
            iterations_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/iterations?api-version=7.1"

            params = {"api-version": self.api_version, "searchCriteria.status": "all"}
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
