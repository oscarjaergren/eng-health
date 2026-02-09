"""
Refactored GitHub API client with base client integration.

This module provides a client for interacting with the GitHub API,
built on top of the BaseAPIClient class for common functionality.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from .base_client import BaseAPIClient


class GitHubClient(BaseAPIClient):
    """
    Client for interacting with GitHub API.

    This client provides methods to fetch repositories, pull requests, and related data
    from GitHub using the REST API. It inherits common functionality from BaseAPIClient
    and implements GitHub-specific behavior.
    """

    BASE_URL = "https://api.github.com"
    PER_PAGE = 100  # Maximum allowed by GitHub API

    def __init__(
        self,
        config: Any,
        logger: logging.Logger,
        enable_cache: bool = True,
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        """
        Initialize the GitHub client.

        Args:
            config: Configuration object with GitHub settings
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
            cache_dir=".cache/github",
            enable_cache=enable_cache,
            max_retries=max_retries,
            timeout=timeout,
        )

        # Setup authentication
        self._setup_auth()

        # Rate limiting
        self.rate_limit_remaining = 5000  # Default for authenticated users
        self.rate_limit_reset = time.time() + 3600  # Default to 1 hour
        self.rate_limit_lock = None  # Not needed for GitHub token auth

    def _get_default_headers(self) -> Dict[str, str]:
        """Get the default headers for GitHub API requests."""
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _setup_auth(self) -> None:
        """Set up authentication for GitHub API."""
        if not hasattr(self.config, "github_token") or not self.config.github_token:
            raise ValueError("GitHub personal access token is required")

        self.session.headers["Authorization"] = f"Bearer {self.config.github_token}"

    def _build_url(self, path: str) -> str:
        """
        Build a full GitHub API URL.

        Args:
            path: API path (without leading slash)

        Returns:
            Full API URL
        """
        return f"{self.BASE_URL}/{path}"

    def _check_rate_limit(self) -> None:
        """Check rate limits and sleep if necessary."""
        current_time = time.time()

        # If we've hit the rate limit, wait until the reset time
        if self.rate_limit_remaining <= 0 and current_time < self.rate_limit_reset:
            sleep_time = self.rate_limit_reset - current_time + 1  # Add 1s buffer
            self.logger.warning(
                f"GitHub rate limit reached. Sleeping for {sleep_time:.1f} seconds"
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
                response.headers.get("X-RateLimit-Remaining", 5000)
            )

        if "X-RateLimit-Reset" in response.headers:
            reset_timestamp = int(response.headers.get("X-RateLimit-Reset", 0))
            self.rate_limit_reset = reset_timestamp + 1  # Add 1s buffer

    def _handle_pagination(
        self, url: str, params: Optional[Dict] = None, max_pages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Handle GitHub API pagination.

        Args:
            url: Initial URL to fetch
            params: Query parameters
            max_pages: Maximum number of pages to fetch (None for all)

        Returns:
            List of items from all pages

        Raises:
            ValueError: If authentication fails or the request is invalid
        """
        items = []
        page = 1

        if params is None:
            params = {}

        params["per_page"] = self.PER_PAGE

        while True:
            params["page"] = page

            try:
                # Make request with retry logic from base class
                response = self._make_request("GET", url, params=params, cache_ttl=3600)

                # If response is None, there was an error that couldn't be recovered from
                if response is None:
                    self.logger.error(f"Failed to fetch data from {url}")
                    break

                # Check for authentication errors
                if response.status_code == 401:
                    error_msg = "Authentication failed: Invalid or missing credentials"
                    try:
                        error_data = response.json()
                        if "message" in error_data:
                            error_msg = (
                                f"Authentication failed: {error_data['message']}"
                            )
                    except ValueError:
                        pass
                    raise ValueError(error_msg)

                # Check for other errors
                if response.status_code != 200:
                    self.logger.warning(
                        f"Received status code {response.status_code} from {url}"
                    )
                    break

                # Add items from this page
                try:
                    page_items = response.json()
                    if not isinstance(page_items, list):
                        page_items = [page_items]

                    items.extend(page_items)

                    # Check if we've reached the end
                    if len(page_items) < self.PER_PAGE:
                        break

                except ValueError as e:
                    self.logger.error(f"Failed to parse response from {url}: {e}")
                    break

                # Check if we've reached the maximum number of pages
                if max_pages and page >= max_pages:
                    break

                page += 1

            except ValueError as e:
                # Re-raise authentication errors
                if "authentication failed" in str(e).lower():
                    raise
                self.logger.error(f"Error fetching data from {url}: {e}")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error fetching data from {url}: {e}")
                break

        return items

    def get_repositories(
        self,
        org_or_user: str,
        type_: str = "all",
    ) -> List[Dict[str, Any]]:
        """
        Fetch all repositories for an organization or user.

        Args:
            org_or_user: Organization or username
            type_: Type of repositories to fetch (all, public, private, forks, etc.)

        Returns:
            List of repository objects

        Raises:
            ValueError: If authentication fails or the request is invalid
        """
        if not org_or_user:
            raise ValueError("Organization or username is required")

        try:
            github_type = getattr(self.config, "github_type", "org")
            path = (
                f"orgs/{org_or_user}/repos"
                if github_type == "org"
                else f"users/{org_or_user}/repos"
            )
            params = {
                "type": type_,
                "sort": "updated",
                "direction": "desc",
            }

            url = self._build_url(path)
            return self._handle_pagination(url, params=params)

        except ValueError as e:
            # Re-raise authentication errors
            if "authentication failed" in str(e).lower():
                raise
            self.logger.error(f"Error fetching repositories for {org_or_user}: {e}")
            raise ValueError(f"Failed to fetch repositories: {e}") from e
        except Exception as e:
            self.logger.error(
                f"Unexpected error fetching repositories for {org_or_user}: {e}"
            )
            raise ValueError(f"Failed to fetch repositories: {e}") from e

    def get_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        base: Optional[str] = None,
        head: Optional[str] = None,
        sort: str = "updated",
        direction: str = "desc",
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch pull requests for a repository.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            state: PR state (open, closed, all)
            base: Filter by base branch name
            head: Filter by head user or head organization and branch
            sort: What to sort results by (created, updated, popularity, long-running)
            direction: Sort order (asc or desc)
            max_pages: Maximum number of pages to fetch (None for all)

        Returns:
            List of pull request objects
        """
        path = f"repos/{owner}/{repo}/pulls"
        params = {
            "state": state,
            "sort": sort,
            "direction": direction,
        }

        if base:
            params["base"] = base
        if head:
            params["head"] = head

        url = self._build_url(path)
        return self._handle_pagination(url, params=params, max_pages=max_pages)

    def get_pull_request_details(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific pull request.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            pull_number: PR number

        Returns:
            Pull request details or None if not found
        """
        path = f"repos/{owner}/{repo}/pulls/{pull_number}"
        url = self._build_url(path)

        response = self._make_request("GET", url)
        if response and response.status_code == 200:
            return response.json()

        return None

    def get_pull_request_comments(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> List[Dict[str, Any]]:
        """
        Get review comments for a pull request.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            pull_number: PR number

        Returns:
            List of review comments
        """
        path = f"repos/{owner}/{repo}/pulls/{pull_number}/comments"
        url = self._build_url(path)

        return self._handle_pagination(url)

    def get_pull_request_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> List[Dict[str, Any]]:
        """
        Get reviews for a pull request.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            pull_number: PR number

        Returns:
            List of reviews
        """
        path = f"repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        url = self._build_url(path)

        return self._handle_pagination(url)

    def get_pull_request_commits(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> List[Dict[str, Any]]:
        """
        Get commits for a pull request.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            pull_number: PR number

        Returns:
            List of commits
        """
        path = f"repos/{owner}/{repo}/pulls/{pull_number}/commits"
        url = self._build_url(path)

        return self._handle_pagination(url)

    def fetch_all_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories, matching the Azure DevOps client interface."""
        owner = getattr(self.config, "github_owner", "")
        if not owner:
            self.logger.warning("No github_owner configured")
            return []

        repos = self.get_repositories(owner)
        for repo in repos:
            repo["repository_name"] = repo.get("name", "Unknown")
        return repos

    def fetch_pull_requests_for_repository(
        self,
        repository: Dict[str, Any],
        since_date: Optional[str] = None,
        known_pr_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch pull requests for a repository, matching the Azure DevOps client interface.

        Args:
            repository: Repository dict with at least a 'name' key
            since_date: ISO date string — stop paginating once all PRs on a page
                        were updated before this date
            known_pr_ids: Set of PR numbers already in cache — review/comment
                          fetching is skipped for these
        """
        owner = getattr(self.config, "github_owner", "")
        repo_name = repository.get("name", "")
        if not owner or not repo_name:
            return []

        known_pr_ids = known_pr_ids or set()

        # Fetch PRs sorted by updated desc — allows early exit on incremental sync
        all_prs: List[Dict[str, Any]] = []
        path = f"repos/{owner}/{repo_name}/pulls"
        params = {"state": "all", "sort": "updated", "direction": "desc"}
        url = self._build_url(path)
        page = 1

        while True:
            page_params = {**params, "page": page, "per_page": self.PER_PAGE}
            response = self._make_request("GET", url, params=page_params, cache_ttl=3600)

            if response is None or response.status_code != 200:
                break

            try:
                page_items = response.json()
                if not isinstance(page_items, list):
                    page_items = [page_items]
            except ValueError:
                break

            if not page_items:
                break

            for pr in page_items:
                pr["repository_name"] = repo_name
            all_prs.extend(page_items)

            # Early exit: if every PR on this page was updated before our
            # last sync, older pages won't have anything new either.
            if since_date and page_items:
                newest_on_page = page_items[0].get("updated_at", "")
                if newest_on_page and newest_on_page < since_date:
                    break

            if len(page_items) < self.PER_PAGE:
                break
            page += 1

        # Enrich only NEW PRs with reviews and comments (most expensive part)
        for pr in all_prs:
            pr_number = pr.get("number")
            if pr_number and pr_number not in known_pr_ids:
                pr["reviews"] = self.get_pull_request_reviews(
                    owner, repo_name, pr_number
                )
                pr["review_comments"] = self.get_pull_request_comments(
                    owner, repo_name, pr_number
                )

        return all_prs
