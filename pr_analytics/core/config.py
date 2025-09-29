"""Configuration management for multi-platform PR extraction tool."""

import os
from typing import List


class Config:
    """Configuration class that loads settings from environment variables."""

    def __init__(self):
        """Initialize configuration with environment variables."""
        # Determine which platforms to use
        self.platforms = self._get_enabled_platforms()

        # Azure DevOps configuration (optional if GitHub is enabled)
        if "azure_devops" in self.platforms:
            self.organization = self._get_required_env("AZURE_DEVOPS_ORGANIZATION")
            self.token = self._get_required_env("AZURE_DEVOPS_PAT")

        # GitHub configuration (optional if Azure DevOps is enabled)
        if "github" in self.platforms:
            self.github_token = self._get_required_env("GITHUB_TOKEN")
            self.github_owner = self._get_required_env("GITHUB_OWNER")
            self.github_type = os.getenv(
                "GITHUB_TYPE", "org"
            ).lower()  # 'org' or 'user'

        self.output_filename = os.getenv("OUTPUT_FILENAME", "pr_data.xlsx")

        # API configuration
        self.api_version = "7.0"
        self.max_results_per_page = 1000
        self.pr_status = "completed"

        # Core filtering - always enabled for meaningful analytics
        self.exclude_iac = True
        self.exclude_personal_approvals = True

        self.max_parallel_workers = int(os.getenv("MAX_PARALLEL_WORKERS", "16"))

    def _get_enabled_platforms(self) -> List[str]:
        """Determine which platforms are enabled based on environment variables."""
        platforms = []

        # Check if Azure DevOps is configured (project is now optional)
        if os.getenv("AZURE_DEVOPS_ORGANIZATION") and os.getenv("AZURE_DEVOPS_PAT"):
            platforms.append("azure_devops")

        # Check if GitHub is configured
        if os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_OWNER"):
            platforms.append("github")

        if not platforms:
            raise ValueError(
                "No platforms configured. Please set up either Azure DevOps "
                "(AZURE_DEVOPS_ORGANIZATION, AZURE_DEVOPS_PAT) "
                "or GitHub (GITHUB_TOKEN, GITHUB_OWNER) environment variables."
            )

        return platforms

    def _get_required_env(self, key: str) -> str:
        """Get required environment variable or raise an error."""
        value = os.getenv(key)
        if not value:
            raise ValueError(
                f"Required environment variable '{key}' is not set. "
                f"Please check your .env file or environment configuration."
            )
        return value

    @property
    def base_url(self) -> str:
        """Get the base API URL for Azure DevOps (organization level)."""
        return f"https://dev.azure.com/{self.organization}/_apis"

    @property
    def repositories_url(self) -> str:
        """Get the repositories API URL for all projects in the organization."""
        return f"{self.base_url}/git/repositories?api-version={self.api_version}"

    def get_pull_requests_url(self, repository_id: str) -> str:
        """Get the pull requests API URL for a specific repository."""
        return (
            f"{self.base_url}/git/repositories/{repository_id}/pullRequests"
            f"?searchCriteria.status={self.pr_status}"
            f"&$top={self.max_results_per_page}"
            f"&api-version={self.api_version}"
        )
