# PR Analytics API Documentation

## Overview

The PR Analytics API provides a RESTful interface for accessing pull request data from Azure DevOps and GitHub with intelligent caching and real-time data fetching.

## Quick Start

### Starting the API

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment variables (copy from .env.example)
cp .env.example .env
# Edit .env with your credentials

# Start the API server
python api_main.py
```

The API will be available at:
- **API Endpoint**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Configuration

Set these environment variables in your `.env` file:

```bash
# API Configuration
API_HOST=0.0.0.0        # API host (default: 0.0.0.0)
API_PORT=8000           # API port (default: 8000)
API_RELOAD=false        # Auto-reload on code changes (dev only)
CACHE_TTL=300           # Cache time-to-live in seconds (default: 300/5min)

# Data Source Configuration
# Azure DevOps
AZURE_DEVOPS_ORGANIZATION=your-org
AZURE_DEVOPS_PAT=your-token

# GitHub
GITHUB_TOKEN=your-token
GITHUB_OWNER=your-org-or-user
GITHUB_TYPE=org  # 'org' or 'user'
```

## API Endpoints

### Health Check

**GET /** - Check API health and status

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-09-29T21:00:00",
  "platforms": ["azure_devops", "github"],
  "cache_stats": {
    "entries": 5,
    "hits": 120,
    "misses": 10,
    "hit_rate": 92.31
  }
}
```

### Pull Requests

**GET /api/pull-requests** - Get pull requests with optional filters

**Query Parameters:**
- `platform` (optional): Filter by platform (`azure_devops`, `github`)
- `repository` (optional): Filter by repository name
- `creator` (optional): Filter by PR creator
- `status` (optional): Filter by status
- `days` (optional): Filter PRs from last N days (1-365)
- `start_date` (optional): Start date (YYYY-MM-DD)
- `end_date` (optional): End date (YYYY-MM-DD)
- `force_refresh` (optional): Force refresh from API (default: false)

**Example:**
```bash
# Get all PRs
curl http://localhost:8000/api/pull-requests

# Get Azure DevOps PRs from last 30 days
curl "http://localhost:8000/api/pull-requests?platform=azure_devops&days=30"

# Force refresh
curl "http://localhost:8000/api/pull-requests?force_refresh=true"
```

**Response:**
```json
[
  {
    "id": 12345,
    "repository": "my-repo",
    "title": "Add new feature",
    "created_by": "user@example.com",
    "created_date": "2025-09-15T10:30:00",
    "status": "Closed",
    "platform": "Azure Devops",
    "approval_count": 2,
    "total_comments": 5,
    "total_reviewers": 3,
    "description": "Feature description",
    "approved_by": ["reviewer1@example.com", "reviewer2@example.com"],
    "rejected_by": [],
    "commenters": ["reviewer1@example.com"],
    "total_threads": 2,
    "active_threads": 0,
    "resolved_threads": 2
  }
]
```

### Repositories

**GET /api/repositories** - Get list of repositories with PR counts

**Query Parameters:**
- `platform` (optional): Filter by platform

**Example:**
```bash
curl http://localhost:8000/api/repositories
```

**Response:**
```json
[
  {
    "name": "my-repo",
    "platform": "Azure Devops",
    "pr_count": 150
  }
]
```

### Contributors

**GET /api/contributors** - Get list of contributors with PR counts

**Query Parameters:**
- `platform` (optional): Filter by platform

**Example:**
```bash
curl http://localhost:8000/api/contributors
```

**Response:**
```json
[
  {
    "name": "user@example.com",
    "platform": "Azure Devops",
    "pr_count": 25
  }
]
```

### Metrics

**GET /api/metrics/summary** - Get overall metrics summary

**Example:**
```bash
curl http://localhost:8000/api/metrics/summary
```

**Response:**
```json
{
  "total_prs": 500,
  "total_repositories": 20,
  "total_contributors": 50,
  "total_reviewers": 75,
  "avg_approvals": 2.5,
  "avg_comments": 3.2,
  "avg_reviewers": 2.8,
  "platforms": ["azure_devops", "github"]
}
```

**GET /api/metrics/platforms** - Get platform-specific statistics

**Example:**
```bash
curl http://localhost:8000/api/metrics/platforms
```

**Response:**
```json
[
  {
    "platform": "Azure Devops",
    "pr_count": 300,
    "repository_count": 12,
    "contributor_count": 30
  }
]
```

### Export

**POST /api/export** - Export PR data to Excel

**Request Body:**
```json
{
  "filters": {
    "platform": "azure_devops",
    "days": 30
  },
  "filename": "pr_export.xlsx"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/export \
  -H "Content-Type: application/json" \
  -d '{"filters": {"days": 30}, "filename": "pr_export.xlsx"}'
```

**Response:**
```json
{
  "success": true,
  "filename": "pr_export.xlsx",
  "record_count": 150,
  "message": "Successfully exported 150 records to pr_export.xlsx"
}
```

**GET /api/export/download/{filename}** - Download exported Excel file

**Example:**
```bash
curl -O http://localhost:8000/api/export/download/pr_export.xlsx
```

### Cache Management

**GET /api/cache/stats** - Get cache statistics

**Example:**
```bash
curl http://localhost:8000/api/cache/stats
```

**Response:**
```json
{
  "entries": 5,
  "hits": 120,
  "misses": 10,
  "hit_rate": 92.31,
  "sets": 15,
  "invalidations": 2,
  "expirations": 3
}
```

**POST /api/cache/invalidate** - Invalidate cache entries

**Query Parameters:**
- `namespace` (optional): Cache namespace to invalidate (e.g., `pull_requests`, `repositories`)

**Example:**
```bash
# Clear all cache
curl -X POST http://localhost:8000/api/cache/invalidate

# Clear specific namespace
curl -X POST "http://localhost:8000/api/cache/invalidate?namespace=pull_requests"
```

**Response:**
```json
{
  "success": true,
  "message": "Invalidated 5 cache entries",
  "namespace": "pull_requests"
}
```

## Caching

- **Default TTL**: 5 minutes (300 seconds)
- **Cache Hit Rate**: Aim for >80% for optimal performance
- **Force Refresh**: Use `force_refresh=true` parameter or invalidate cache endpoint
- Adjust `CACHE_TTL` environment variable based on your needs

## Troubleshooting

**API won't start:** Check `.env` configuration and port 8000 availability

**Dashboard not connecting:** Verify API is running with `curl http://localhost:8000/`

**Slow performance:** Check cache hit rate at `/api/cache/stats`, increase `CACHE_TTL` if needed

## Examples

### Python Client Example

```python
import requests

# Get PRs from last 7 days
response = requests.get(
    "http://localhost:8000/api/pull-requests",
    params={"days": 7, "platform": "azure_devops"}
)
prs = response.json()

# Export to Excel
response = requests.post(
    "http://localhost:8000/api/export",
    json={"filters": {"days": 30}, "filename": "monthly_report.xlsx"}
)
result = response.json()
print(f"Exported {result['record_count']} records")
```

### Dashboard Integration Example

```python
from azure_pr_analytics.dashboard.api_client import APIClient

# Initialize client
client = APIClient("http://localhost:8000")

# Check availability
if client.is_available():
    # Get pull requests
    df = client.get_pull_requests(days=30)

    # Get metrics
    metrics = client.get_metrics_summary()

    # Export to Excel
    result = client.export_to_excel(
        filters={"days": 30},
        filename="export.xlsx"
    )
```

---

**Interactive API Documentation:** http://localhost:8000/docs (when API is running)
