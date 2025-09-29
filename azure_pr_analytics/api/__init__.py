"""
API package for Azure DevOps PR Analytics.

This package provides a FastAPI-based REST API for accessing PR analytics data
with intelligent caching and real-time data fetching.
"""

from azure_pr_analytics.api.cache_service import CacheService, get_cache_service
from azure_pr_analytics.api.data_service import DataService

__all__ = ["CacheService", "get_cache_service", "DataService"]
