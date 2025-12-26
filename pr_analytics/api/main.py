"""
FastAPI application for PR Analytics API.

This module provides REST API endpoints for accessing pull request analytics
with real-time data fetching and intelligent caching.
"""

import logging
import os
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pr_analytics.api.data_service import DataService
from pr_analytics.api.models import (
    CacheStats,
    Contributor,
    HealthCheck,
    MetricsSummary,
    PlatformStats,
    PullRequestDetail,
    Repository,
)
from pr_analytics.core.config import Config

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="PR Analytics API",
    description="REST API for Azure DevOps and GitHub Pull Request Analytics",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global data service instance
_data_service: Optional[DataService] = None


def get_data_service() -> DataService:
    """
    Get or create the data service instance.

    Returns:
        DataService instance

    Raises:
        HTTPException: If configuration fails
    """
    global _data_service

    if _data_service is None:
        try:
            config = Config()
            cache_ttl = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes default
            _data_service = DataService(config, logger, cache_ttl=cache_ttl)
        except Exception as e:
            logger.error(f"Failed to initialize data service: {e}")
            raise HTTPException(
                status_code=500, detail=f"Configuration error: {str(e)}"
            )

    return _data_service


@app.get("/", response_model=HealthCheck)
async def health_check():
    """
    API health check endpoint.

    Returns:
        Health check information including API status and cache statistics
    """
    try:
        service = get_data_service()
        return HealthCheck(
            status="healthy",
            version="1.0.0",
            timestamp=datetime.now().isoformat(),
            platforms=service.config.platforms,
            cache_stats=service.get_cache_stats(),
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pull-requests", response_model=List[PullRequestDetail])
async def get_pull_requests(
    platform: Optional[str] = Query(
        None, description="Filter by platform (azure_devops, github)"
    ),
    repository: Optional[str] = Query(None, description="Filter by repository name"),
    creator: Optional[str] = Query(None, description="Filter by creator"),
    status: Optional[str] = Query(None, description="Filter by status"),
    days: Optional[int] = Query(
        None, description="Filter PRs from last N days", ge=1, le=365
    ),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    force_refresh: bool = Query(False, description="Force refresh from API"),
):
    """
    Get pull requests with optional filters.

    This endpoint returns pull request data with intelligent caching.
    Use force_refresh=true to bypass cache and get fresh data.
    """
    try:
        service = get_data_service()

        # Fetch PRs (with caching)
        prs = service.fetch_pull_requests(
            platform=platform, force_refresh=force_refresh
        )

        # Apply filters
        filters = {
            "platform": platform,
            "repository": repository,
            "creator": creator,
            "status": status,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
        }
        filtered_prs = service.filter_pull_requests(prs, filters)

        # Convert to response model
        response = []
        for pr in filtered_prs:
            response.append(
                PullRequestDetail(
                    id=pr.get("ID", 0),
                    repository=pr.get("Repository", "Unknown"),
                    title=pr.get("Title", ""),
                    created_by=pr.get("Created By", "Unknown"),
                    created_date=str(pr.get("Created Date", "")),
                    status=pr.get("State", "Unknown"),
                    platform=pr.get("Platform", "Unknown"),
                    approval_count=pr.get("Approval Count", 0),
                    total_comments=pr.get("Total Comments", 0),
                    total_reviewers=pr.get("Total Reviewers", 0),
                    description=pr.get("Description", ""),
                    approved_by=pr.get("Approved By", []),
                    rejected_by=pr.get("Rejected By", []),
                    commenters=pr.get("Commenters", []),
                    total_threads=pr.get("Total Threads", 0),
                    active_threads=pr.get("Active Threads", 0),
                    resolved_threads=pr.get("Resolved Threads", 0),
                )
            )

        return response

    except Exception as e:
        logger.error(f"Error fetching pull requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/repositories", response_model=List[Repository])
async def get_repositories(
    platform: Optional[str] = Query(None, description="Filter by platform"),
):
    """
    Get list of repositories with PR counts.

    Returns aggregated repository information across platforms.
    """
    try:
        service = get_data_service()
        repos = service.get_repositories(platform=platform)

        return [
            Repository(
                name=repo["name"],
                platform=repo["platform"],
                pr_count=repo["pr_count"],
            )
            for repo in repos
        ]

    except Exception as e:
        logger.error(f"Error fetching repositories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/contributors", response_model=List[Contributor])
async def get_contributors(
    platform: Optional[str] = Query(None, description="Filter by platform"),
):
    """
    Get list of contributors with PR counts.

    Returns aggregated contributor information across platforms.
    """
    try:
        service = get_data_service()
        contributors = service.get_contributors(platform=platform)

        return [
            Contributor(
                name=contrib["name"],
                platform=contrib["platform"],
                pr_count=contrib["pr_count"],
            )
            for contrib in contributors
        ]

    except Exception as e:
        logger.error(f"Error fetching contributors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metrics/summary", response_model=MetricsSummary)
async def get_metrics_summary():
    """
    Get overall metrics summary.

    Returns comprehensive analytics metrics across all platforms.
    """
    try:
        service = get_data_service()
        metrics = service.get_metrics_summary()

        return MetricsSummary(**metrics)

    except Exception as e:
        logger.error(f"Error fetching metrics summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metrics/platforms", response_model=List[PlatformStats])
async def get_platform_stats():
    """
    Get statistics per platform.

    Returns platform-specific metrics for comparison.
    """
    try:
        service = get_data_service()
        stats = service.get_platform_stats()

        return [PlatformStats(**stat) for stat in stats]

    except Exception as e:
        logger.error(f"Error fetching platform stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cache/stats", response_model=CacheStats)
async def get_cache_stats():
    """
    Get cache statistics.

    Returns information about cache performance and usage.
    """
    try:
        service = get_data_service()
        stats = service.get_cache_stats()

        return CacheStats(**stats)

    except Exception as e:
        logger.error(f"Error fetching cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cache/invalidate")
async def invalidate_cache(
    namespace: Optional[str] = Query(None, description="Cache namespace to invalidate"),
):
    """
    Invalidate cache entries.

    Use this endpoint to force a refresh of cached data.
    - No namespace: Clears all cache
    - With namespace: Clears specific namespace (e.g., 'pull_requests')
    """
    try:
        service = get_data_service()
        count = service.invalidate_cache(namespace)

        return {
            "success": True,
            "message": f"Invalidated {count} cache entries",
            "namespace": namespace or "all",
        }

    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    # Get port from environment or use default
    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")

    logger.info(f"Starting PR Analytics API on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
