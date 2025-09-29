"""
API client for the dashboard to communicate with the FastAPI backend.

This module provides a client interface for the Streamlit dashboard
to fetch data from the PR Analytics API.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests


class APIClient:
    """
    Client for communicating with the PR Analytics API.

    This client handles all API communication for the dashboard,
    including error handling and response parsing.
    """

    def __init__(
        self, base_url: Optional[str] = None, logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the API client.

        Args:
            base_url: Base URL of the API (default: from environment or localhost:8000)
            logger: Logger instance
        """
        self.base_url = base_url or os.getenv("API_URL", "http://localhost:8000")
        self.logger = logger or logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP request to the API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON request body

        Returns:
            Response data or None if request failed
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=30,
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Connection error: {e}")
            return None
        except requests.exceptions.Timeout as e:
            self.logger.error(f"Request timeout: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return None

    def health_check(self) -> Optional[Dict[str, Any]]:
        """
        Check API health status.

        Returns:
            Health check information or None if unavailable
        """
        return self._make_request("GET", "/")

    def get_pull_requests(
        self,
        platform: Optional[str] = None,
        repository: Optional[str] = None,
        creator: Optional[str] = None,
        status: Optional[str] = None,
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Get pull requests from the API.

        Args:
            platform: Filter by platform
            repository: Filter by repository
            creator: Filter by creator
            status: Filter by status
            days: Filter by days
            start_date: Filter by start date
            end_date: Filter by end date
            force_refresh: Force refresh from API

        Returns:
            DataFrame containing pull request data
        """
        params = {
            "platform": platform,
            "repository": repository,
            "creator": creator,
            "status": status,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
            "force_refresh": force_refresh,
        }

        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}

        data = self._make_request("GET", "/api/pull-requests", params=params)

        if data is None:
            return pd.DataFrame()

        # Convert API response to DataFrame format expected by dashboard
        records = []
        for pr in data:
            record = {
                "ID": pr.get("id"),
                "Repository": pr.get("repository"),
                "Title": pr.get("title"),
                "Created By": pr.get("created_by"),
                "Created Date": pr.get("created_date"),
                "State": pr.get("status"),
                "Platform": pr.get("platform"),
                "Approval Count": pr.get("approval_count", 0),
                "Total Comments": pr.get("total_comments", 0),
                "Total Reviewers": pr.get("total_reviewers", 0),
                "Description": pr.get("description", ""),
                "Approved By": pr.get("approved_by", []),
                "Rejected By": pr.get("rejected_by", []),
                "Commenters": pr.get("commenters", []),
                "Total Threads": pr.get("total_threads", 0),
                "Active Threads": pr.get("active_threads", 0),
                "Resolved Threads": pr.get("resolved_threads", 0),
            }
            records.append(record)

        return pd.DataFrame(records)

    def get_repositories(self, platform: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get list of repositories.

        Args:
            platform: Filter by platform

        Returns:
            List of repository information
        """
        params = {"platform": platform} if platform else {}
        data = self._make_request("GET", "/api/repositories", params=params)
        return data or []

    def get_contributors(self, platform: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get list of contributors.

        Args:
            platform: Filter by platform

        Returns:
            List of contributor information
        """
        params = {"platform": platform} if platform else {}
        data = self._make_request("GET", "/api/contributors", params=params)
        return data or []

    def get_metrics_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get overall metrics summary.

        Returns:
            Metrics summary dictionary
        """
        return self._make_request("GET", "/api/metrics/summary")

    def get_platform_stats(self) -> List[Dict[str, Any]]:
        """
        Get platform-specific statistics.

        Returns:
            List of platform statistics
        """
        data = self._make_request("GET", "/api/metrics/platforms")
        return data or []

    def export_to_excel(
        self,
        filters: Optional[Dict[str, Any]] = None,
        filename: str = "pr_data.xlsx",
    ) -> Optional[Dict[str, Any]]:
        """
        Export data to Excel file.

        Args:
            filters: Filter parameters
            filename: Output filename

        Returns:
            Export response or None if failed
        """
        request_data = {
            "filters": filters,
            "filename": filename,
        }

        return self._make_request("POST", "/api/export", json_data=request_data)

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get cache statistics.

        Returns:
            Cache statistics dictionary
        """
        return self._make_request("GET", "/api/cache/stats")

    def invalidate_cache(
        self, namespace: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Invalidate cache entries.

        Args:
            namespace: Cache namespace to invalidate

        Returns:
            Invalidation response
        """
        params = {"namespace": namespace} if namespace else {}
        return self._make_request("POST", "/api/cache/invalidate", params=params)

    def is_available(self) -> bool:
        """
        Check if API is available.

        Returns:
            True if API is available, False otherwise
        """
        health = self.health_check()
        return health is not None and health.get("status") == "healthy"
