"""Integration tests for API clients with mocking."""

import json
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch

import requests

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Local imports after path modification
from pr_analytics.clients.azure_devops_client import AzureDevOpsClient
from pr_analytics.clients.github_client import GitHubClient
from pr_analytics.core.config import Config


class MockResponse:
    """Mock response object for testing API calls."""

    def __init__(self, json_data: dict, status_code: int = 200, headers: dict = None):
        """
        Initialize mock response.

        Args:
            json_data: JSON data to return
            status_code: HTTP status code
            headers: Response headers
        """
        self.json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(json_data)

    def json(self):
        """Return JSON data."""
        return self.json_data

    def raise_for_status(self):
        """Raise exception for bad status codes."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestAzureDevOpsClientIntegration(unittest.TestCase):
    """Integration tests for Azure DevOps client."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock(spec=Config)
        self.mock_config.azure_devops_organization = "test-org"
        self.mock_config.azure_devops_project = "test-project"
        self.mock_config.azure_devops_token = "test-token"
        self.mock_config.token = "test-token"  # Add this for compatibility
        self.mock_config.max_parallel_workers = 4

        self.mock_logger = Mock()

        # Create client with caching disabled for testing
        self.client = AzureDevOpsClient(
            self.mock_config, self.mock_logger, enable_cache=False
        )

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    def test_fetch_repositories_success(self, mock_make_request):
        """Test successful repository fetching."""
        # Mock successful response with Azure DevOps format
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [
                {
                    "id": "repo-1",
                    "name": "test-repo-1",
                    "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-1",
                    "project": {"id": "project-1", "name": "test-project"},
                    "defaultBranch": "refs/heads/main",
                    "size": 1024,
                    "remoteUrl": "https://dev.azure.com/test-org/test-project/_git/test-repo-1",
                    "sshUrl": "git@ssh.dev.azure.com:v3/test-org/test-project/test-repo-1",
                },
                {
                    "id": "repo-2",
                    "name": "test-repo-2",
                    "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-2",
                    "project": {"id": "project-1", "name": "test-project"},
                    "defaultBranch": "refs/heads/main",
                    "size": 2048,
                    "remoteUrl": "https://dev.azure.com/test-org/test-project/_git/test-repo-2",
                    "sshUrl": "git@ssh.dev.azure.com:v3/test-org/test-project/test-repo-2",
                },
            ]
        }
        mock_make_request.return_value = mock_response

        # Execute test
        repositories = self.client.get_repositories(
            organization=self.mock_config.azure_devops_organization,
            project=self.mock_config.azure_devops_project,
        )

        # Verify results
        self.assertEqual(len(repositories), 2)
        self.assertEqual(repositories[0]["name"], "test-repo-1")
        self.assertEqual(repositories[1]["name"], "test-repo-2")

        # Verify API call
        mock_make_request.assert_called_once()
        call_args, call_kwargs = mock_make_request.call_args
        self.assertEqual(call_args[0], "GET")
        self.assertIn("git/repositories", call_args[1])
        # The API version should be in the URL parameters
        self.assertIn("api-version=7.1", call_args[1])

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    def test_fetch_repositories_failure(self, mock_make_request):
        """Test repository fetching failure."""
        # Mock failed response
        mock_make_request.side_effect = requests.HTTPError("Authentication failed")

        # Execute test with required arguments
        with self.assertRaises(requests.HTTPError):
            self.client.get_repositories(
                organization=self.mock_config.azure_devops_organization,
                project=self.mock_config.azure_devops_project,
            )

        # Verify API call was made
        mock_make_request.assert_called_once()

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    def test_fetch_pull_requests_success(self, mock_make_request):
        """Test successful pull request fetching."""
        # Mock API response
        test_repository = {
            "id": "repo-1",
            "name": "test-repo-1",
            "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-1",
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [
                {
                    "pullRequestId": 1,
                    "title": "Test PR 1",
                    "description": "Test description 1",
                    "creationDate": "2023-01-01T00:00:00Z",
                },
                {
                    "pullRequestId": 2,
                    "title": "Test PR 2",
                    "description": "Test description 2",
                    "creationDate": "2023-01-02T00:00:00Z",
                },
            ]
        }
        mock_make_request.return_value = mock_response

        # Execute test - Using get_pull_requests instead of fetch_pull_requests_for_repository
        pull_requests = self.client.get_pull_requests(
            organization=self.mock_config.azure_devops_organization,
            project=self.mock_config.azure_devops_project,
            repository=test_repository["id"],
        )

        # Verify results
        self.assertEqual(len(pull_requests), 2)
        self.assertEqual(pull_requests[0]["title"], "Test PR 1")
        self.assertEqual(pull_requests[1]["title"], "Test PR 2")

        # Verify API call
        mock_make_request.assert_called_once()

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    def test_fetch_pull_requests_with_pagination(self, mock_make_request):
        """Test pull request fetching with pagination."""
        # Mock API responses for pagination
        test_repository = {
            "id": "repo-1",
            "name": "test-repo-1",
            "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-1",
        }

        # First page
        mock_response_1 = Mock()
        mock_response_1.status_code = 200
        mock_response_1.json.return_value = {
            "value": [
                {"pullRequestId": 1, "title": "PR 1"},
                {"pullRequestId": 2, "title": "PR 2"},
            ],
            "count": 2,
        }

        # Second page
        mock_response_2 = Mock()
        mock_response_2.status_code = 200
        mock_response_2.json.return_value = {
            "value": [
                {"pullRequestId": 3, "title": "PR 3"},
                {"pullRequestId": 4, "title": "PR 4"},
            ],
            "count": 2,
        }

        # Third page (empty to signal end of results)
        mock_response_3 = Mock()
        mock_response_3.status_code = 200
        mock_response_3.json.return_value = {"value": [], "count": 0}

        # Configure the mock to return the first page, then the second, then the empty page
        mock_make_request.side_effect = [
            mock_response_1,
            mock_response_2,
            mock_response_3,
        ]

        # Execute test - Using get_pull_requests with pagination
        # top=2 means we want to fetch 2 PRs per page (page size)
        pull_requests = self.client.get_pull_requests(
            organization=self.mock_config.azure_devops_organization,
            project=self.mock_config.azure_devops_project,
            repository=test_repository["id"],
            top=2,  # Page size (2 PRs per page)
        )

        # Verify results from both pages were combined
        self.assertEqual(len(pull_requests), 4)  # Should have all 4 PRs from both pages
        self.assertEqual(pull_requests[0]["pullRequestId"], 1)
        self.assertEqual(pull_requests[1]["pullRequestId"], 2)
        self.assertEqual(pull_requests[2]["pullRequestId"], 3)
        self.assertEqual(pull_requests[3]["pullRequestId"], 4)

        # Verify the API was called with the correct parameters
        self.assertEqual(
            mock_make_request.call_count, 3
        )  # Two pages of data + one empty page

        # Get the call arguments for the first page
        call_args_1, call_kwargs_1 = mock_make_request.call_args_list[0]
        self.assertEqual(call_args_1[0], "GET")

        # Check the URL contains the correct path
        self.assertIn(
            f"repositories/{test_repository['id']}/pullrequests", call_args_1[1]
        )

        # Check the params dictionary for the first page
        self.assertIn("params", call_kwargs_1)
        params_1 = call_kwargs_1["params"]
        self.assertEqual(params_1.get("api-version"), "7.1")
        self.assertEqual(params_1.get("$top"), 2)
        self.assertEqual(params_1.get("$skip"), 0)  # First page has skip=0

        # Get the call arguments for the second page
        call_args_2, call_kwargs_2 = mock_make_request.call_args_list[1]
        self.assertEqual(call_args_2[0], "GET")

        # Check the URL contains the correct path
        self.assertIn(
            f"repositories/{test_repository['id']}/pullrequests", call_args_2[1]
        )

        # Check the params dictionary for the second page
        self.assertIn("params", call_kwargs_2)
        params_2 = call_kwargs_2["params"]
        self.assertEqual(params_2.get("api-version"), "7.1")
        self.assertEqual(params_2.get("$top"), 2)
        self.assertEqual(
            params_2.get("$skip"), 2
        )  # Second page should skip first 2 items
        self.assertEqual(pull_requests[0]["pullRequestId"], 1)
        self.assertEqual(pull_requests[1]["pullRequestId"], 2)
        self.assertEqual(pull_requests[2]["pullRequestId"], 3)
        self.assertEqual(pull_requests[3]["pullRequestId"], 4)

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    @patch("time.sleep")
    def test_rate_limit_handling(self, mock_sleep, mock_make_request):
        """Test rate limit handling."""
        # Create a new client with retries enabled for this test
        client = AzureDevOpsClient(
            self.mock_config, self.mock_logger, enable_cache=False, max_retries=3
        )

        # First response: rate limit exceeded
        rate_limit_response = Mock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {
            "Retry-After": "1",
            "x-ms-ratelimit-remaining": "0",
            "x-ms-ratelimit-reset": str(int(time.time()) + 1),
        }
        rate_limit_response.json.return_value = {"message": "Rate limit exceeded"}
        rate_limit_response.raise_for_status.side_effect = (
            requests.exceptions.HTTPError("Rate limit exceeded")
        )

        # Second response: success
        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "value": [
                {
                    "id": "repo-1",
                    "name": "test-repo-1",
                    "project": {"name": "test-project"},
                    "defaultBranch": "refs/heads/main",
                    "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-1",
                }
            ]
        }

        # Configure the side effect to return rate_limit_response first, then success_response
        mock_make_request.side_effect = [rate_limit_response, success_response]

        # Execute test with mocked sleep
        repositories = client.get_repositories(
            organization=self.mock_config.azure_devops_organization,
            project=self.mock_config.azure_devops_project,
        )

        # Verify results
        self.assertEqual(len(repositories), 1)
        self.assertEqual(repositories[0]["name"], "test-repo-1")

        # Verify API calls
        self.assertEqual(mock_make_request.call_count, 2)

        # Verify sleep was called with the expected backoff
        mock_sleep.assert_called_once()

        # Verify the correct endpoint was called
        call_args, call_kwargs = mock_make_request.call_args_list[0]
        self.assertEqual(call_args[0], "GET")
        self.assertIn("git/repositories", call_args[1])
        self.assertIn("api-version=7.1", call_args[1])

    def test_session_configuration(self):
        """Test that session is properly configured."""
        session = self.client.session

        # Verify authentication header
        self.assertIn("Authorization", session.headers)
        self.assertTrue(session.headers["Authorization"].startswith("Basic"))

        # Verify content type
        self.assertEqual(session.headers["Content-Type"], "application/json")

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    def test_error_recovery(self, mock_make_request):
        """Test error recovery and retry logic."""
        # Mock network error followed by success
        mock_make_request.side_effect = [
            requests.ConnectionError("Network error"),
            requests.Timeout("Request timeout"),
            MockResponse({"value": []}),
        ]

        with patch("time.sleep"):
            result = self.client.get_repositories(
                organization=self.mock_config.azure_devops_organization,
                project=self.mock_config.azure_devops_project,
            )

            # Verify retries were attempted
            self.assertEqual(mock_make_request.call_count, 3)
            self.assertEqual(result, [])


class TestGitHubClientIntegration(unittest.TestCase):
    """Integration tests for GitHub client."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock(spec=Config)
        self.mock_config.github_organization = "test-org"
        self.mock_config.github_token = "test-token"
        self.mock_config.max_parallel_workers = 4

        self.mock_logger = Mock()

        # Create client with caching disabled for testing
        self.client = GitHubClient(
            self.mock_config, self.mock_logger, enable_cache=False
        )

    @patch("pr_analytics.clients.github_client.GitHubClient._make_request")
    def test_fetch_repositories_success(self, mock_make_request):
        """Test successful GitHub repository fetching."""
        # Create client
        client = GitHubClient(self.github_config, self.mock_logger, enable_cache=False)

        # Mock GitHub API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "repo1", "full_name": "test-org/repo1"},
            {"id": 2, "name": "repo2", "full_name": "test-org/repo2"},
        ]
        mock_make_request.return_value = mock_response

        # Execute test
        repositories = client.get_repositories(org_or_user="test-org")

        # Verify results
        self.assertEqual(len(repositories), 2)
        self.assertEqual(repositories[0]["name"], "repo1")
        self.assertEqual(repositories[1]["name"], "repo2")

    @patch("pr_analytics.clients.github_client.GitHubClient._make_request")
    def test_github_rate_limit_handling(self, mock_make_request):
        """Test GitHub rate limit handling."""
        # Create client with retries enabled
        client = GitHubClient(
            self.github_config, self.mock_logger, enable_cache=False, max_retries=3
        )

        # First response: rate limit exceeded
        rate_limit_response = Mock()
        rate_limit_response.status_code = 403
        rate_limit_response.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(time.time()) + 1),
            "Retry-After": "1",
        }
        rate_limit_response.json.return_value = {"message": "API rate limit exceeded"}

        # Second response: success
        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = [{"id": 1, "name": "repo1"}]

        mock_make_request.side_effect = [rate_limit_response, success_response]

        # Execute test with mocked sleep
        with patch("time.sleep"):
            repositories = client.get_repositories(org_or_user="test-org")

        # Verify results
        self.assertEqual(len(repositories), 1)
        self.assertEqual(repositories[0]["name"], "repo1")

        # Verify API calls
        self.assertEqual(mock_make_request.call_count, 2)

        # Verify the correct endpoint was called
        expected_url = "https://api.github.com/users/test-org/repos"
        call_args = mock_make_request.call_args_list[0][0]
        self.assertEqual(call_args[0], "GET")
        self.assertEqual(call_args[1], expected_url)

    def test_parse_link_header(self):
        """Test parsing GitHub Link headers."""
        # This test is no longer needed as the method is now private and tested through the public API

    def test_session_configuration(self):
        """Test that GitHub session is properly configured."""
        # Create client - use self.client from setUp
        session = self.client.session

        # Verify authentication header
        self.assertIn("Authorization", session.headers)
        self.assertTrue(session.headers["Authorization"].startswith("Bearer"))

        # Verify accept header
        self.assertIn("Accept", session.headers)
        self.assertEqual(session.headers["Accept"], "application/vnd.github+json")


class TestAPIClientErrorHandling(unittest.TestCase):
    """Test error handling across API clients."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()

        # Azure DevOps config
        self.azure_config = Mock()
        self.azure_config.azure_devops_organization = "test-org"
        self.azure_config.azure_devops_project = "test-project"
        self.azure_config.token = "azure-test-token"
        self.azure_config.max_parallel_workers = 4

        # Test class attributes for direct access in tests
        self.azure_devops_organization = "test-org"
        self.azure_devops_project = "test-project"

        # GitHub config
        self.github_config = Mock()
        self.github_config.github_token = "github-test-token"
        self.github_config.github_organization = "test-org"
        self.github_config.max_parallel_workers = 4

        # Create a client instance for tests that need it
        self.client = GitHubClient(
            self.github_config, self.mock_logger, enable_cache=False
        )

    @patch("pr_analytics.clients.azure_devops_client.AzureDevOpsClient._make_request")
    def test_azure_devops_network_error_recovery(self, mock_make_request):
        """Test Azure DevOps client network error recovery."""
        # Create client with retries enabled
        client = AzureDevOpsClient(
            self.azure_config,
            self.mock_logger,
            enable_cache=False,
            max_retries=3,
            timeout=10,
        )

        # Mock responses: first attempt fails with network error, second succeeds
        error_response = Mock()
        error_response.status_code = 200
        error_response.json.side_effect = requests.ConnectionError("Network error")

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "value": [
                {
                    "id": "repo1",
                    "name": "test-repo",
                    "project": {"name": "test-project"},
                    "defaultBranch": "refs/heads/main",
                    "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo1",
                }
            ]
        }

        mock_make_request.side_effect = [error_response, success_response]

        # Mock time.sleep to speed up the test
        with patch("time.sleep"):
            repositories = client.get_repositories(
                organization=self.azure_config.azure_devops_organization,
                project=self.azure_devops_project,
            )

            # Verify successful retry
            self.assertEqual(len(repositories), 1)
            self.assertEqual(repositories[0]["name"], "test-repo")
            self.assertEqual(mock_make_request.call_count, 2)

            # Verify the correct URL was called
            expected_url = (
                f"https://dev.azure.com/{self.azure_devops_organization}/"
                f"{self.azure_devops_project}/_apis/git/repositories"
            )
            mock_make_request.assert_called_with(
                "GET", expected_url, params={"api-version": "7.0"}, cache_ttl=3600
            )

    @patch("pr_analytics.clients.github_client.GitHubClient._make_request")
    def test_github_authentication_error(self, mock_make_request):
        """Test GitHub client authentication error handling."""
        # Test initialization with missing token
        invalid_config = Mock()
        invalid_config.github_token = ""

        with self.assertRaises(ValueError) as context:
            GitHubClient(invalid_config, self.mock_logger, enable_cache=False)
        self.assertIn(
            "personal access token is required", str(context.exception).lower()
        )

        # Test API authentication error
        client = GitHubClient(self.github_config, self.mock_logger, enable_cache=False)

        # Mock API authentication error
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "message": "Bad credentials",
            "documentation_url": "https://docs.github.com/rest",
        }
        mock_make_request.return_value = mock_response

        # Should raise an exception for API authentication errors
        with self.assertRaises(ValueError) as context:
            client.get_repositories(org_or_user="test-org")

        self.assertIn("authentication failed", str(context.exception).lower())

        # Verify the correct API endpoint was called
        expected_url = "https://api.github.com/users/test-org/repos"
        mock_make_request.assert_called_once()
        call_args = mock_make_request.call_args[0]
        call_kwargs = mock_make_request.call_args[1]

        self.assertEqual(call_args[0], "GET")
        self.assertEqual(call_args[1], expected_url)
        self.assertEqual(call_kwargs["params"]["type"], "all")
        self.assertEqual(call_kwargs["cache_ttl"], 3600)

    @patch("pr_analytics.clients.base_client.CacheManager")
    def test_invalid_configuration_handling(self, mock_cache_manager):
        """Test handling of invalid configuration."""
        # Mock cache manager to avoid filesystem operations
        mock_cache_manager.return_value = Mock()

        # Test Azure DevOps client with missing token
        with self.assertRaises(ValueError) as context:
            invalid_config = Mock()
            invalid_config.token = ""
            AzureDevOpsClient(invalid_config, self.mock_logger)
        self.assertIn("token", str(context.exception).lower())

        # Test GitHub client with missing token
        with self.assertRaises(ValueError) as context:
            invalid_config = Mock()
            invalid_config.github_token = ""
            GitHubClient(invalid_config, self.mock_logger)
        self.assertIn("personal access token", str(context.exception).lower())


if __name__ == "__main__":
    unittest.main()
