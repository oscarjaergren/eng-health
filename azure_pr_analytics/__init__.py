"""Azure DevOps PR Analytics - A comprehensive tool for analyzing pull request data."""

__version__ = "2.0.0"
__author__ = "Azure DevOps PR Analytics Team"

from .core.config import Config
from .clients.azure_devops_client import AzureDevOpsClient
from .clients.github_client import GitHubClient
from .processors.unified_data_processor import UnifiedDataProcessor

__all__ = ["Config", "AzureDevOpsClient", "GitHubClient", "UnifiedDataProcessor"]
