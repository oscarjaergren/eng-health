"""
Pydantic models for API request/response validation.

This module defines the data models used in the API for validation and documentation.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PullRequestFilter(BaseModel):
    """Filter parameters for pull request queries."""

    platform: Optional[str] = Field(
        None, description="Filter by platform (azure_devops, github)"
    )
    repository: Optional[str] = Field(None, description="Filter by repository name")
    creator: Optional[str] = Field(None, description="Filter by PR creator")
    status: Optional[str] = Field(None, description="Filter by PR status")
    days: Optional[int] = Field(
        None, description="Filter PRs from last N days", ge=1, le=365
    )
    start_date: Optional[str] = Field(
        None, description="Filter PRs from this date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, description="Filter PRs until this date (YYYY-MM-DD)"
    )
    exclude_iac: Optional[bool] = Field(True, description="Exclude IAC-related PRs")


class PullRequestSummary(BaseModel):
    """Summary representation of a pull request."""

    id: int = Field(..., description="Pull request ID")
    repository: str = Field(..., description="Repository name")
    title: str = Field(..., description="PR title")
    created_by: str = Field(..., description="PR creator")
    created_date: str = Field(..., description="Creation date")
    status: str = Field(..., description="PR status")
    platform: str = Field(..., description="Platform (Azure DevOps or GitHub)")
    approval_count: int = Field(0, description="Number of approvals")
    total_comments: int = Field(0, description="Total comments")
    total_reviewers: int = Field(0, description="Total reviewers")


class PullRequestDetail(PullRequestSummary):
    """Detailed representation of a pull request."""

    description: Optional[str] = Field(None, description="PR description")
    approved_by: List[str] = Field(
        default_factory=list, description="List of approvers"
    )
    rejected_by: List[str] = Field(
        default_factory=list, description="List of rejectors"
    )
    commenters: List[str] = Field(
        default_factory=list, description="List of commenters"
    )
    total_threads: int = Field(0, description="Total discussion threads")
    active_threads: int = Field(0, description="Active discussion threads")
    resolved_threads: int = Field(0, description="Resolved discussion threads")


class Repository(BaseModel):
    """Repository information."""

    name: str = Field(..., description="Repository name")
    platform: str = Field(..., description="Platform (Azure DevOps or GitHub)")
    pr_count: int = Field(0, description="Total number of PRs")


class Contributor(BaseModel):
    """Contributor information."""

    name: str = Field(..., description="Contributor name")
    pr_count: int = Field(0, description="Number of PRs created")
    platform: str = Field(..., description="Primary platform")


class MetricsSummary(BaseModel):
    """Overall metrics summary."""

    total_prs: int = Field(0, description="Total pull requests")
    total_repositories: int = Field(0, description="Total repositories")
    total_contributors: int = Field(0, description="Total contributors")
    total_reviewers: int = Field(0, description="Total unique reviewers")
    avg_approvals: float = Field(0.0, description="Average approvals per PR")
    avg_comments: float = Field(0.0, description="Average comments per PR")
    avg_reviewers: float = Field(0.0, description="Average reviewers per PR")
    platforms: List[str] = Field(
        default_factory=list, description="Configured platforms"
    )


class PlatformStats(BaseModel):
    """Statistics for a specific platform."""

    platform: str = Field(..., description="Platform name")
    pr_count: int = Field(0, description="Number of PRs")
    repository_count: int = Field(0, description="Number of repositories")
    contributor_count: int = Field(0, description="Number of contributors")


class CacheStats(BaseModel):
    """Cache statistics."""

    entries: int = Field(0, description="Number of cached entries")
    hits: int = Field(0, description="Cache hits")
    misses: int = Field(0, description="Cache misses")
    hit_rate: float = Field(0.0, description="Cache hit rate percentage")
    sets: int = Field(0, description="Cache sets")
    invalidations: int = Field(0, description="Cache invalidations")
    expirations: int = Field(0, description="Cache expirations")


class ExportRequest(BaseModel):
    """Request to export data to Excel."""

    filters: Optional[PullRequestFilter] = Field(None, description="Filters to apply")
    filename: Optional[str] = Field("pr_data.xlsx", description="Output filename")


class ExportResponse(BaseModel):
    """Response from export operation."""

    success: bool = Field(..., description="Whether export was successful")
    filename: str = Field(..., description="Generated filename")
    record_count: int = Field(0, description="Number of records exported")
    message: str = Field(..., description="Status message")


class HealthCheck(BaseModel):
    """API health check response."""

    status: str = Field(..., description="API status")
    version: str = Field(..., description="API version")
    timestamp: str = Field(..., description="Current timestamp")
    platforms: List[str] = Field(
        default_factory=list, description="Configured platforms"
    )
    cache_stats: Dict[str, Any] = Field(
        default_factory=dict, description="Cache statistics"
    )


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    timestamp: str = Field(..., description="Error timestamp")
