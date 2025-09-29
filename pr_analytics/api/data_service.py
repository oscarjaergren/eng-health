"""
Data service layer for fetching and processing PR data.

This module provides the business logic layer between API endpoints and data clients.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from pr_analytics.api.cache_service import get_cache_service
from pr_analytics.clients.azure_devops_client import AzureDevOpsClient
from pr_analytics.clients.github_client import GitHubClient
from pr_analytics.core.config import Config
from pr_analytics.processors.unified_data_processor import UnifiedDataProcessor


class DataService:
    """
    Service layer for fetching and processing PR data with caching.

    This service coordinates between API clients, processors, and cache
    to provide efficient data retrieval.
    """

    def __init__(
        self,
        config: Config,
        logger: Optional[logging.Logger] = None,
        cache_ttl: int = 300,
    ):
        """
        Initialize the data service.

        Args:
            config: Configuration object
            logger: Logger instance
            cache_ttl: Cache time-to-live in seconds (default: 5 minutes)
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.cache = get_cache_service(default_ttl=cache_ttl)
        self.processor = UnifiedDataProcessor(self.logger, config)

        # Initialize clients based on configured platforms
        self.clients = {}
        if "azure_devops" in config.platforms:
            self.clients["azure_devops"] = AzureDevOpsClient(config, self.logger)

        if "github" in config.platforms:
            self.clients["github"] = GitHubClient(config, self.logger)

        self.logger.info(f"DataService initialized for platforms: {config.platforms}")

    def fetch_pull_requests(
        self,
        platform: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch pull requests with caching.

        Args:
            platform: Specific platform to fetch from (None for all)
            force_refresh: Force refresh from API, bypassing cache

        Returns:
            List of processed pull request data
        """
        cache_key = platform or "all"
        cache_params = {"force_refresh": force_refresh}

        # Check cache first unless force refresh
        if not force_refresh:
            cached_data = self.cache.get("pull_requests", cache_key, cache_params)
            if cached_data is not None:
                self.logger.info(f"Returning cached PR data for: {cache_key}")
                return cached_data

        # Fetch fresh data
        self.logger.info(f"Fetching fresh PR data for: {cache_key}")
        all_pr_data = []

        platforms_to_fetch = [platform] if platform else self.config.platforms

        for plt in platforms_to_fetch:
            if plt not in self.clients:
                self.logger.warning(f"Platform {plt} not configured")
                continue

            try:
                # Fetch raw PR data from client
                client = self.clients[plt]
                raw_prs = client.fetch_all_pull_requests()

                if raw_prs:
                    # Process PRs
                    processed_prs = self.processor.process_pull_requests(raw_prs, plt)
                    all_pr_data.extend(processed_prs)
                    self.logger.info(f"Fetched {len(processed_prs)} PRs from {plt}")

            except Exception as e:
                self.logger.error(f"Error fetching PRs from {plt}: {e}")

        # Cache the results
        self.cache.set("pull_requests", cache_key, all_pr_data, params=cache_params)

        return all_pr_data

    def filter_pull_requests(
        self,
        prs: List[Dict[str, Any]],
        filters: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Apply filters to pull request data.

        Args:
            prs: List of pull requests
            filters: Filter parameters

        Returns:
            Filtered list of pull requests
        """
        filtered_prs = prs.copy()

        # Platform filter
        if filters.get("platform"):
            platform = filters["platform"].replace("_", " ").title()
            filtered_prs = [pr for pr in filtered_prs if pr.get("Platform") == platform]

        # Repository filter
        if filters.get("repository"):
            filtered_prs = [
                pr
                for pr in filtered_prs
                if pr.get("Repository") == filters["repository"]
            ]

        # Creator filter
        if filters.get("creator"):
            filtered_prs = [
                pr for pr in filtered_prs if pr.get("Created By") == filters["creator"]
            ]

        # Status filter
        if filters.get("status"):
            filtered_prs = [
                pr
                for pr in filtered_prs
                if pr.get("State", "").lower() == filters["status"].lower()
            ]

        # Date filters
        if filters.get("days"):
            cutoff_date = datetime.now() - timedelta(days=filters["days"])
            filtered_prs = [
                pr
                for pr in filtered_prs
                if pd.to_datetime(pr.get("Created Date")) >= cutoff_date
            ]

        if filters.get("start_date"):
            start_date = datetime.fromisoformat(filters["start_date"])
            filtered_prs = [
                pr
                for pr in filtered_prs
                if pd.to_datetime(pr.get("Created Date")) >= start_date
            ]

        if filters.get("end_date"):
            end_date = datetime.fromisoformat(filters["end_date"])
            filtered_prs = [
                pr
                for pr in filtered_prs
                if pd.to_datetime(pr.get("Created Date")) <= end_date
            ]

        self.logger.info(f"Filtered PRs: {len(prs)} -> {len(filtered_prs)}")
        return filtered_prs

    def get_repositories(
        self,
        platform: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of repositories with PR counts.

        Args:
            platform: Filter by platform

        Returns:
            List of repository information
        """
        cache_key = f"repos_{platform or 'all'}"
        cached_data = self.cache.get("repositories", cache_key)

        if cached_data is not None:
            return cached_data

        # Fetch PRs and aggregate by repository
        prs = self.fetch_pull_requests(platform)
        df = pd.DataFrame(prs)

        if df.empty:
            return []

        repo_data = (
            df.groupby(["Repository", "Platform"]).size().reset_index(name="pr_count")
        )

        repositories = [
            {
                "name": row["Repository"],
                "platform": row["Platform"],
                "pr_count": int(row["pr_count"]),
            }
            for _, row in repo_data.iterrows()
        ]

        self.cache.set("repositories", cache_key, repositories)
        return repositories

    def get_contributors(
        self,
        platform: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of contributors with PR counts.

        Args:
            platform: Filter by platform

        Returns:
            List of contributor information
        """
        cache_key = f"contributors_{platform or 'all'}"
        cached_data = self.cache.get("contributors", cache_key)

        if cached_data is not None:
            return cached_data

        # Fetch PRs and aggregate by contributor
        prs = self.fetch_pull_requests(platform)
        df = pd.DataFrame(prs)

        if df.empty:
            return []

        contrib_data = (
            df.groupby(["Created By", "Platform"]).size().reset_index(name="pr_count")
        )

        contributors = [
            {
                "name": row["Created By"],
                "platform": row["Platform"],
                "pr_count": int(row["pr_count"]),
            }
            for _, row in contrib_data.iterrows()
        ]

        self.cache.set("contributors", cache_key, contributors)
        return contributors

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get overall metrics summary.

        Returns:
            Dictionary containing summary metrics
        """
        cached_data = self.cache.get("metrics", "summary")

        if cached_data is not None:
            return cached_data

        # Fetch all PRs
        prs = self.fetch_pull_requests()
        df = pd.DataFrame(prs)

        if df.empty:
            return {
                "total_prs": 0,
                "total_repositories": 0,
                "total_contributors": 0,
                "total_reviewers": 0,
                "avg_approvals": 0.0,
                "avg_comments": 0.0,
                "avg_reviewers": 0.0,
                "platforms": self.config.platforms,
            }

        # Calculate metrics
        metrics = {
            "total_prs": len(df),
            "total_repositories": df["Repository"].nunique(),
            "total_contributors": df["Created By"].nunique(),
            "total_reviewers": int(df["Total Reviewers"].sum()),
            "avg_approvals": float(df["Approval Count"].mean()),
            "avg_comments": float(df["Total Comments"].mean()),
            "avg_reviewers": float(df["Total Reviewers"].mean()),
            "platforms": self.config.platforms,
        }

        self.cache.set("metrics", "summary", metrics, ttl=60)  # Cache for 1 minute
        return metrics

    def get_platform_stats(self) -> List[Dict[str, Any]]:
        """
        Get statistics per platform.

        Returns:
            List of platform statistics
        """
        cached_data = self.cache.get("metrics", "platform_stats")

        if cached_data is not None:
            return cached_data

        prs = self.fetch_pull_requests()
        df = pd.DataFrame(prs)

        if df.empty:
            return []

        stats = []
        for platform in df["Platform"].unique():
            platform_df = df[df["Platform"] == platform]
            stats.append(
                {
                    "platform": platform,
                    "pr_count": len(platform_df),
                    "repository_count": platform_df["Repository"].nunique(),
                    "contributor_count": platform_df["Created By"].nunique(),
                }
            )

        self.cache.set("metrics", "platform_stats", stats, ttl=60)
        return stats

    def export_to_excel(
        self,
        prs: List[Dict[str, Any]],
        filename: str,
    ) -> bool:
        """
        Export PR data to Excel file.

        Args:
            prs: List of pull requests to export
            filename: Output filename

        Returns:
            True if successful, False otherwise
        """
        try:
            df = pd.DataFrame(prs)

            if df.empty:
                self.logger.warning("No data to export")
                return False

            # Sort by platform and creation date
            if "Created Date" in df.columns:
                df["Created Date"] = pd.to_datetime(df["Created Date"], errors="coerce")
                # Remove timezone info if present
                if df["Created Date"].dt.tz is not None:
                    df["Created Date"] = df["Created Date"].dt.tz_localize(None)

            df = df.sort_values(
                [col for col in ["Platform", "Created Date"] if col in df.columns],
                ascending=[True, False],
            )

            # Remove timezone info from all datetime columns
            for col in df.columns:
                if df[col].dtype.name.startswith("datetime64[ns,") or "datetime" in str(
                    df[col].dtype
                ):
                    try:
                        df[col] = pd.to_datetime(df[col], errors="coerce")
                        if (
                            hasattr(df[col].dtype, "tz")
                            and df[col].dtype.tz is not None
                        ):
                            df[col] = df[col].dt.tz_localize(None)
                    except Exception as e:
                        self.logger.warning(
                            f"Could not process datetime column {col}: {e}"
                        )

            df.to_excel(filename, index=False)
            self.logger.info(f"Exported {len(prs)} PRs to {filename}")
            return True

        except Exception as e:
            self.logger.error(f"Error exporting to Excel: {e}")
            return False

    def invalidate_cache(self, namespace: Optional[str] = None) -> int:
        """
        Invalidate cache entries.

        Args:
            namespace: Cache namespace to invalidate (None for all)

        Returns:
            Number of entries invalidated
        """
        count = self.cache.invalidate(namespace)
        self.logger.info(f"Invalidated {count} cache entries")
        return count

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Cache statistics dictionary
        """
        return self.cache.get_stats()
