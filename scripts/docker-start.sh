#!/bin/bash

# Docker Quick Start Script for PR Analytics
# This script helps you get started with the Docker deployment

set -e

echo "🐳 PR Analytics - Docker Quick Start"
echo "======================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed"
    echo "Please install Docker from: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: Docker Compose is not installed"
    echo "Please install Docker Compose from: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    echo ""
    echo "Creating .env from .env.example..."

    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ .env file created"
        echo ""
        echo "📝 Please edit .env file with your credentials:"
        echo "   - Azure DevOps: AZURE_DEVOPS_ORGANIZATION and AZURE_DEVOPS_PAT"
        echo "   - GitHub: GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_TYPE"
        echo ""
        read -p "Press Enter after you've configured .env file..."
    else
        echo "❌ Error: .env.example not found"
        exit 1
    fi
fi

echo "✅ Configuration file found"
echo ""

# Create data and cache directories
mkdir -p data cache
echo "✅ Created data and cache directories"
echo ""

# Build Docker image
echo "🔨 Building Docker image..."
docker-compose build

echo ""
echo "✅ Docker image built successfully"
echo ""

# Start dashboard
echo "🚀 Starting dashboard service..."
docker-compose up -d dashboard

echo ""
echo "✅ Dashboard started successfully"
echo ""

# Wait for service to be healthy
echo "⏳ Waiting for dashboard to be ready..."
sleep 5

# Check if service is running
if docker-compose ps | grep -q "dashboard.*Up"; then
    echo ""
    echo "✅ Dashboard is running!"
    echo ""
    echo "🌐 Access the dashboard at: http://localhost:8501"
    echo ""
    echo "📊 To collect data, run:"
    echo "   docker-compose run --rm cli"
    echo ""
    echo "📋 Useful commands:"
    echo "   docker-compose logs -f dashboard  # View logs"
    echo "   docker-compose ps                 # Check status"
    echo "   docker-compose down               # Stop services"
    echo ""
else
    echo "❌ Error: Dashboard failed to start"
    echo "Check logs with: docker-compose logs dashboard"
    exit 1
fi
