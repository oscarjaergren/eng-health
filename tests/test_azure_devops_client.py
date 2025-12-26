"""Tests for the refactored Azure DevOps client."""

import logging
import os

# Add parent directory to path for imports
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pr_analytics.clients.azure_devops_client import AzureDevOpsClient


class MockConfig:
    """Mock configuration for testing."""

    def __init__(self, token="test_token", max_parallel_workers=4):
        self.token = token
        self.max_parallel_workers = max_parallel_workers
        self.azure_devops_organization = "test-org"
        self.azure_devops_project = "test-project"
        self.repositories_url = (
            "https://dev.azure.com/test-org/_apis/git/repositories?api-version=7.1"
        )


class TestAzureDevOpsClient(unittest.TestCase):
    """Test cases for AzureDevOpsClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.logger = logging.getLogger(__name__)
        self.config = MockConfig()
        self.client = AzureDevOpsClient(
            config=self.config, logger=self.logger, enable_cache=False
        )

    def test_initialization(self):
        """Test client initialization."""
        self.assertEqual(self.client.config, self.config)
        self.assertEqual(self.client.logger, self.logger)
        self.assertIsNotNone(self.client.session)
        self.assertEqual(
            self.client.session.headers["Accept"],
            f"application/json; api-version={AzureDevOpsClient.API_VERSION}",
        )

    @patch("requests.Session.request")
    def test_get_repositories_success(self, mock_request):
        """Test successful repository fetch."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [
                {
                    "id": "repo1",
                    "name": "test-repo",
                    "project": {"name": "test-project"},
                },
                {
                    "id": "repo2",
                    "name": "another-repo",
                    "project": {"name": "test-project"},
                },
            ]
        }
        mock_request.return_value = mock_response

        # Call the method
        repos = self.client.fetch_all_repositories()

        # Assertions
        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[0]["name"], "test-repo")
        mock_request.assert_called_once()

    @patch("requests.Session.request")
    def test_fetch_pull_requests_for_repository(self, mock_request):
        """Test fetching pull requests."""
        # Setup mock response - empty to end pagination
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": []}
        mock_request.return_value = mock_response

        # Call the method
        test_repo = {
            "id": "test-repo",
            "name": "test-repo",
            "project": {"name": "test-project"},
        }
        prs = self.client.fetch_pull_requests_for_repository(repository=test_repo)

        # Assertions - returns empty list
        self.assertEqual(len(prs), 0)

    @patch("requests.Session.request")
    def test_get_pull_request_details(self, mock_request):
        """Test fetching pull request details."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "pullRequestId": 123,
            "title": "Test PR",
            "description": "Test description",
        }
        mock_request.return_value = mock_response

        # Call the method
        pr = self.client.get_pull_request_details(
            organization="test-org",
            project="test-project",
            repository="test-repo",
            pull_request_id=123,
        )

        # Assertions
        self.assertEqual(pr["title"], "Test PR")
        mock_request.assert_called_once()

    @patch("requests.Session.request")
    def test_rate_limiting(self, mock_request):
        """Test rate limit handling."""
        # Mock response returns empty on rate limit
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {
            "Retry-After": "1",
        }
        mock_request.return_value = rate_limit_response

        # Call the method
        repos = self.client.fetch_all_repositories()

        # Returns empty list on rate limit
        self.assertEqual(len(repos), 0)

    @patch("requests.Session.request")
    def test_error_handling(self, mock_request):
        """Test error handling."""
        # Setup mock to return None (simulating error)
        mock_request.return_value = None

        # Call the method and verify it handles the error
        repos = self.client.fetch_all_repositories()
        self.assertEqual(repos, [])


if __name__ == "__main__":
    unittest.main()
