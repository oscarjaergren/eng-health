"""GitHub API client for fetching pull request data."""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.config import Config
from ..utils.cache_manager import CacheManager


class GitHubClient:
    """Client for interacting with GitHub API."""

    def __init__(
        self, config: Config, logger: logging.Logger, enable_cache: bool = True
    ):
        """Initialize the GitHub client."""
        self.config = config
        self.logger = logger
        self.session = self._create_session()

        # Performance settings
        self.max_workers = min(config.max_parallel_workers, (os.cpu_count() or 1) + 4)

        # Rate limiting
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = time.time()
        self.rate_limit_lock = threading.Lock()

        # Cache management
        self.cache_manager = (
            CacheManager(cache_dir=".cache/github") if enable_cache else None
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

        # Setup authentication using GitHub token
        session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.config.github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

        return session

    def _handle_rate_limit(self, response: requests.Response) -> bool:
        """
        Handle GitHub rate limiting with exponential backoff.

        Args:
            response: HTTP response object

        Returns:
            bool: True if rate limited and handled, False otherwise
        """
        if response.status_code == 429 or response.status_code == 403:
            # Check if this is a rate limit response
            if "X-RateLimit-Remaining" in response.headers:
                remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
                if remaining == 0:
                    reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                    sleep_time = max(reset_time - time.time(), 60)
                    self.logger.warning(
                        f"GitHub rate limit exceeded. Sleeping for {
                            sleep_time:.0f} seconds"
                    )
                    time.sleep(sleep_time)
                    return True

            # Secondary rate limit (abuse detection)
            if "Retry-After" in response.headers:
                retry_after = int(response.headers.get("Retry-After", 60))
                self.logger.warning(
                    f"GitHub secondary rate limit hit. Sleeping for {retry_after} seconds"
                )
                time.sleep(retry_after)
                return True

        return False

    def _make_request_with_retry(
        self, url: str, params: Dict = None, max_retries: int = 3, cache_ttl: int = 3600
    ) -> Optional[requests.Response]:
        """
        Make HTTP request with rate limiting, retry logic, and caching.

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

                # Handle rate limiting
                if self._handle_rate_limit(response):
                    continue  # Retry after rate limit handling

                if response.status_code == 200:
                    # Cache successful response
                    if self.cache_manager:
                        self.cache_manager.set(
                            url, response.text, params, ttl=cache_ttl
                        )
                    return response
                elif response.status_code == 404:
                    # Not found is not a retry-able error
                    return response
                else:
                    self.logger.warning(
                        f"Request failed with status {
                            response.status_code}, attempt {
                            attempt + 1}/{
                            max_retries + 1}"
                    )
                    if attempt < max_retries:
                        time.sleep(2**attempt)  # Exponential backoff

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"Request exception: {e}, attempt {attempt + 1}/{max_retries + 1}"
                )
                if attempt < max_retries:
                    time.sleep(2**attempt)

        return None

    def _parse_link_header(self, link_header: str) -> Dict[str, str]:
        """
        Parse GitHub's Link header for pagination.

        Args:
            link_header: Link header value

        Returns:
            Dict mapping rel types to URLs
        """
        links = {}
        if not link_header:
            return links

        for link in link_header.split(","):
            parts = link.strip().split(";")
            if len(parts) != 2:
                continue

            url = parts[0].strip("<>")
            rel = parts[1].strip()

            if "rel=" in rel:
                rel_type = rel.split("rel=")[1].strip("\"'")
                links[rel_type] = url

        return links

    def fetch_all_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories for the organization or user."""
        try:
            self.logger.info(
                f"Fetching repositories from GitHub for {
                    self.config.github_owner}..."
            )

            # Determine if this is an organization or user
            if self.config.github_type == "org":
                url = f"https://api.github.com/orgs/{
                    self.config.github_owner}/repos"
            else:
                url = f"https://api.github.com/users/{
                    self.config.github_owner}/repos"

            all_repos = []
            next_url = url

            # Use GitHub's Link header pagination
            while next_url:
                params = {"per_page": 100, "sort": "updated", "direction": "desc"}

                response = self._make_request_with_retry(next_url, params)

                if not response or response.status_code != 200:
                    if response:
                        self.logger.error(
                            f"Failed to fetch repositories: {
                                response.status_code}"
                        )
                        self.logger.error(f"Response: {response.text}")
                    else:
                        self.logger.error(
                            "Failed to fetch repositories: No response received"
                        )
                    break

                repos = response.json()
                if not repos:
                    break

                all_repos.extend(repos)

                # Parse Link header for next page
                link_header = response.headers.get("Link", "")
                links = self._parse_link_header(link_header)
                next_url = links.get("next")

                self.logger.info(
                    f"Fetched {
                        len(repos)} repositories, total: {
                        len(all_repos)}"
                )

                # Rate limiting info
                remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
                self.logger.debug(f"Rate limit remaining: {remaining}")

            self.logger.info(
                f"Found {
                    len(all_repos)} repositories for {
                    self.config.github_owner}"
            )
            for repo in all_repos[:10]:  # Log first 10 repos
                self.logger.info(
                    f"  - {repo.get('name', 'Unknown')} (ID: {repo.get('id', 'Unknown')})"
                )

            if len(all_repos) > 10:
                self.logger.info(
                    f"  ... and {
                        len(all_repos) -
                        10} more repositories"
                )

            return all_repos

        except Exception as e:
            self.logger.error(f"Error fetching repositories: {e}")
            return []

    def fetch_pull_requests_for_repository(
        self, repository: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Fetch all pull requests for a specific repository with detailed information."""
        repo_name = repository.get("name", "Unknown")
        repo_full_name = repository.get("full_name", "")

        try:
            self.logger.info(f"Fetching pull requests for repository: {repo_name}")

            url = f"https://api.github.com/repos/{repo_full_name}/pulls"
            all_pr_data = []
            next_url = url

            # Use GitHub's Link header pagination
            while next_url:
                params = {
                    "state": "all",  # Get both open and closed PRs
                    "per_page": 100,
                    "sort": "updated",
                    "direction": "desc",
                }

                response = self._make_request_with_retry(next_url, params)

                if not response or response.status_code != 200:
                    if response and response.status_code == 404:
                        # Repo has no PRs or access denied - log as info, not
                        # warning
                        self.logger.debug(f"No PRs found for {repo_name} (404)")
                    elif response:
                        self.logger.warning(
                            f"API request failed for {repo_name}: {
                                response.status_code}"
                        )
                    else:
                        self.logger.error(
                            f"Failed to fetch PRs for {repo_name}: No response received"
                        )
                    break

                # Parse JSON response
                page_results = response.json()

                if not page_results:
                    break

                # Enhance each PR with repository information
                for pr in page_results:
                    pr["repository_name"] = repo_name
                    pr["repository_full_name"] = repo_full_name
                    pr["repository_id"] = repository.get("id")

                all_pr_data.extend(page_results)

                # Parse Link header for next page
                link_header = response.headers.get("Link", "")
                links = self._parse_link_header(link_header)
                next_url = links.get("next")

                self.logger.debug(
                    f"Fetched {
                        len(page_results)} PRs for {repo_name}, total: {
                        len(all_pr_data)}"
                )

                # Rate limiting info
                remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
                self.logger.debug(f"Rate limit remaining: {remaining}")

            return all_pr_data

        except Exception as e:
            self.logger.error(f"Error fetching PRs for repository {repo_name}: {e}")
            return []

    def fetch_all_pull_requests(self) -> List[Dict[str, Any]]:
        """Fetch all pull requests from all repositories using parallel processing."""
        # First, fetch all repositories
        repositories = self.fetch_all_repositories()

        if not repositories:
            self.logger.warning("No repositories found")
            return []

        # Fetch PRs from repositories in parallel
        all_pr_data = []
        completed_repos = 0
        total_repos = len(repositories)

        self.logger.info(
            f"Fetching PRs from {total_repos} repositories using {
                min(
                    self.max_workers,
                    total_repos)} parallel workers..."
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
            f"Total pull requests fetched across all repositories: {
                len(all_pr_data)} "
            f"(completed in {
                elapsed_total:.1f}s)"
        )
        return all_pr_data

    def _fetch_pr_details_parallel(
        self, pr_data: List[Dict[str, Any]], repo_full_name: str, repo_name: str
    ) -> List[Dict[str, Any]]:
        """Fetch detailed information (reviews and comments) for PRs in parallel."""
        if not pr_data:
            return pr_data

        # Use a smaller worker pool for detailed fetching to avoid overwhelming
        # the API
        detail_workers = min(8, len(pr_data))

        with ThreadPoolExecutor(max_workers=detail_workers) as executor:
            # Submit tasks for fetching PR details
            future_to_pr = {
                executor.submit(self._fetch_single_pr_details, pr, repo_full_name): pr
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
                    pr_number = pr.get("number", "unknown")
                    self.logger.warning(
                        f"Failed to fetch details for PR {pr_number} in {repo_name}: {e}"
                    )
                    # Set empty defaults so processing doesn't fail
                    pr["reviews"] = []
                    pr["review_comments"] = []
                    pr["issue_comments"] = []

        return pr_data

    def _fetch_single_pr_details(
        self, pr: Dict[str, Any], repo_full_name: str
    ) -> Dict[str, Any]:
        """Fetch detailed information for a single PR."""
        pr_number = pr.get("number")
        details = {}

        if pr_number:
            # Fetch reviews, review comments, and issue comments concurrently
            with ThreadPoolExecutor(max_workers=3) as executor:
                reviews_future = executor.submit(
                    self._fetch_pr_reviews, repo_full_name, pr_number
                )
                review_comments_future = executor.submit(
                    self._fetch_pr_review_comments, repo_full_name, pr_number
                )
                issue_comments_future = executor.submit(
                    self._fetch_pr_issue_comments, repo_full_name, pr_number
                )

                details["reviews"] = reviews_future.result()
                details["review_comments"] = review_comments_future.result()
                details["issue_comments"] = issue_comments_future.result()
        else:
            details["reviews"] = []
            details["review_comments"] = []
            details["issue_comments"] = []

        return details

    def _fetch_pr_reviews(
        self, repo_full_name: str, pr_number: int
    ) -> List[Dict[str, Any]]:
        """Fetch all reviews for a specific PR with pagination."""
        try:
            url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews"
            all_reviews = []
            next_url = url

            # Use GitHub's Link header pagination
            while next_url:
                params = {"per_page": 100}
                response = self._make_request_with_retry(next_url, params)

                if not response or response.status_code != 200:
                    break

                reviews = response.json()
                if not reviews:
                    break

                all_reviews.extend(reviews)

                # Parse Link header for next page
                link_header = response.headers.get("Link", "")
                links = self._parse_link_header(link_header)
                next_url = links.get("next")

            return all_reviews
        except Exception:
            return []

    def _fetch_pr_review_comments(
        self, repo_full_name: str, pr_number: int
    ) -> List[Dict[str, Any]]:
        """Fetch all review comments (code comments) for a specific PR with pagination."""
        try:
            url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/comments"
            all_comments = []
            next_url = url

            # Use GitHub's Link header pagination
            while next_url:
                params = {"per_page": 100}
                response = self._make_request_with_retry(next_url, params)

                if not response or response.status_code != 200:
                    break

                comments = response.json()
                if not comments:
                    break

                all_comments.extend(comments)

                # Parse Link header for next page
                link_header = response.headers.get("Link", "")
                links = self._parse_link_header(link_header)
                next_url = links.get("next")

            return all_comments
        except Exception:
            return []

    def _fetch_pr_issue_comments(
        self, repo_full_name: str, pr_number: int
    ) -> List[Dict[str, Any]]:
        """Fetch all issue comments (general PR comments) for a specific PR with pagination."""
        try:
            url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
            all_comments = []
            next_url = url

            # Use GitHub's Link header pagination
            while next_url:
                params = {"per_page": 100}
                response = self._make_request_with_retry(next_url, params)

                if not response or response.status_code != 200:
                    break

                comments = response.json()
                if not comments:
                    break

                all_comments.extend(comments)

                # Parse Link header for next page
                link_header = response.headers.get("Link", "")
                links = self._parse_link_header(link_header)
                next_url = links.get("next")

            return all_comments
        except Exception:
            return []
