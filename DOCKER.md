# Docker Deployment Guide

Quick reference for deploying the PR Analytics tool using Docker.

## Quick Start

```bash
# 1. Clone and configure
git clone <repository-url>
cd azure-devops-pr-analytics
cp .env.example .env
# Edit .env with your credentials

# 2. Start the dashboard
docker-compose up -d dashboard

# 3. Collect data
docker-compose run --rm cli

# 4. Access dashboard
# Open http://localhost:8501 in your browser
```

## Architecture

```
┌─────────────────────────────────────────┐
│         Single Docker Image             │
├─────────────────────────────────────────┤
│  Python 3.11 + Dependencies             │
│  - Azure DevOps Client                  │
│  - GitHub Client                        │
│  - Data Processors                      │
│  - Streamlit Dashboard                  │
└─────────────────────────────────────────┘
           │                    │
           ▼                    ▼
    ┌──────────────┐    ┌──────────────┐
    │  Dashboard   │    │  CLI Service │
    │  (Always On) │    │  (On Demand) │
    └──────────────┘    └──────────────┘
           │                    │
           └────────┬───────────┘
                    ▼
            ┌──────────────────┐
            │  Shared Volumes  │
            │  - data/         │
            │  - cache/        │
            └──────────────────┘
```

## Services

### Dashboard Service
- **Purpose**: Web interface for visualizing PR analytics
- **Port**: 8501 (configurable)
- **Auto-start**: Yes (unless stopped)
- **Health Check**: Built-in Streamlit health endpoint

### CLI Service
- **Purpose**: Collect PR data from Azure DevOps/GitHub
- **Run Mode**: On-demand or scheduled
- **Profile**: `tools` (doesn't start by default)

## Common Commands

### Starting Services

```bash
# Start dashboard only (recommended)
docker-compose up -d dashboard

# Start all services (if you modify profiles)
docker-compose --profile tools up -d
```

### Data Collection

```bash
# Run CLI once and remove container
docker-compose run --rm cli

# Run CLI and keep container (for debugging)
docker-compose run cli
```

### Monitoring

```bash
# View live logs
docker-compose logs -f dashboard

# View last 100 lines
docker-compose logs --tail=100 dashboard

# Check service status
docker-compose ps

# Check health status
docker inspect pr-analytics-dashboard | grep -A 10 Health
```

### Maintenance

```bash
# Restart dashboard
docker-compose restart dashboard

# Rebuild after code changes
docker-compose build
docker-compose up -d dashboard

# Update to latest code
git pull
docker-compose build --no-cache
docker-compose up -d dashboard

# Stop all services
docker-compose down

# Remove everything (including volumes)
docker-compose down -v
```

## Data Management

### Volume Mounts

| Local Path | Container Path | Purpose |
|------------|----------------|---------|
| `./data/` | `/app/data/` | Excel output files |
| `./cache/` | `/app/cache/` | API response cache |

### Backup Data

```bash
# Backup data directory
tar -czf pr-analytics-backup-$(date +%Y%m%d).tar.gz data/ cache/

# Restore data
tar -xzf pr-analytics-backup-20250129.tar.gz
```

### Clear Cache

```bash
# Stop services
docker-compose down

# Clear cache
rm -rf cache/*

# Restart
docker-compose up -d dashboard
```

## Configuration

### Environment Variables

Create `.env` file with:

```bash
# Azure DevOps (optional)
AZURE_DEVOPS_ORGANIZATION=your-org
AZURE_DEVOPS_PAT=your-token

# GitHub (optional)
GITHUB_TOKEN=your-token
GITHUB_OWNER=your-org-or-username
GITHUB_TYPE=org

# Common
OUTPUT_FILENAME=pr_data.xlsx
MAX_PARALLEL_WORKERS=16
```

### Custom Port

Edit `docker-compose.yml`:

```yaml
services:
  dashboard:
    ports:
      - "8502:8501"  # Use port 8502 instead
```

### Resource Limits

Add to `docker-compose.yml`:

```yaml
services:
  dashboard:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

## Automation

### Scheduled Data Collection

#### Linux/macOS (cron)

```bash
# Edit crontab
crontab -e

# Add entry (runs daily at 2 AM)
0 2 * * * cd /path/to/azure-devops-pr-analytics && docker-compose run --rm cli >> /var/log/pr-analytics.log 2>&1
```

#### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., Daily at 2:00 AM)
4. Action: Start a program
   - Program: `docker-compose`
   - Arguments: `run --rm cli`
   - Start in: `C:\path\to\azure-devops-pr-analytics`

#### Docker-based Scheduler

Add to `docker-compose.yml`:

```yaml
  scheduler:
    image: mcuadros/ofelia:latest
    depends_on:
      - dashboard
    command: daemon --docker
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    labels:
      ofelia.job-run.collect-data.schedule: "0 2 * * *"
      ofelia.job-run.collect-data.container: "pr-analytics-cli"
```

## Troubleshooting

### Dashboard Won't Start

```bash
# Check logs
docker-compose logs dashboard

# Common issues:
# 1. Port already in use - change port in docker-compose.yml
# 2. Missing .env file - copy from .env.example
# 3. Build failed - check dependencies in requirements.txt
```

### CLI Fails to Collect Data

```bash
# Run with verbose output
docker-compose run --rm cli

# Check environment variables
docker-compose run --rm cli env | grep -E 'AZURE|GITHUB'

# Test API connectivity
docker-compose run --rm cli python -c "import requests; print(requests.get('https://dev.azure.com').status_code)"
```

### Permission Denied (Linux/macOS)

```bash
# Fix ownership of data directories
sudo chown -R $USER:$USER data/ cache/

# Or run with current user
docker-compose run --rm --user $(id -u):$(id -g) cli
```

### Out of Memory

```bash
# Reduce parallel workers in .env
MAX_PARALLEL_WORKERS=8

# Add memory limits in docker-compose.yml (see Configuration section)
```

### Slow Performance

```bash
# Increase parallel workers
MAX_PARALLEL_WORKERS=32

# Use more CPU
# Edit docker-compose.yml to increase CPU limits

# Check cache usage
du -sh cache/
```

## Security Best Practices

1. **Never commit `.env` file** - It contains sensitive tokens
2. **Use environment-specific files** - `.env.production`, `.env.staging`
3. **Rotate tokens regularly** - Update PATs/tokens periodically
4. **Restrict network access** - Use Docker networks and firewalls
5. **Regular updates** - Keep base image and dependencies updated

```bash
# Update base image
docker pull python:3.11-slim
docker-compose build --no-cache
```

## Production Deployment

### Reverse Proxy Setup (Nginx)

```nginx
server {
    listen 80;
    server_name pr-analytics.example.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### HTTPS with Let's Encrypt

```bash
# Install certbot
apt-get install certbot python3-certbot-nginx

# Get certificate
certbot --nginx -d pr-analytics.example.com

# Auto-renewal is configured automatically
```

### Monitoring

```bash
# Add Prometheus metrics
# Install Streamlit Prometheus exporter
pip install streamlit-prometheus

# Monitor with:
docker stats pr-analytics-dashboard
```

## Support

For issues, please check:
1. Docker logs: `docker-compose logs`
2. Application logs in `data/` directory
3. GitHub Issues for known problems
4. README.md for general documentation
