"""Integration tests for API clients with mocking."""

import unittest
from unittest.mock import Mock, patch, MagicMock
import requests
import json
import sys
from pathlib import Path

# Add azure_pr_analytics directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure_pr_analytics.clients.azure_devops_client import AzureDevOpsClient
from azure_pr_analytics.clients.github_client import GitHubClient
from azure_pr_analytics.core.config import Config


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

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_fetch_repositories_success(self, mock_get):
        """Test successful repository fetching."""
        # Mock API response
        mock_response_data = {
            "value": [
                {
                    "id": "repo-1",
                    "name": "test-repo-1",
                    "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-1",
                },
                {
                    "id": "repo-2",
                    "name": "test-repo-2",
                    "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-2",
                },
            ]
        }

        mock_get.return_value = MockResponse(mock_response_data)

        # Execute test
        repositories = self.client.fetch_all_repositories()

        # Verify results
        self.assertEqual(len(repositories), 2)
        self.assertEqual(repositories[0]["name"], "test-repo-1")
        self.assertEqual(repositories[1]["name"], "test-repo-2")

        # Verify API call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("git/repositories", call_args[0][0])

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_fetch_repositories_failure(self, mock_get):
        """Test repository fetching failure."""
        # Mock failed response
        mock_get.return_value = MockResponse({}, status_code=401)

        # Execute test
        repositories = self.client.fetch_all_repositories()

        # Verify empty result on failure
        self.assertEqual(repositories, [])
        self.mock_logger.error.assert_called()

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_fetch_pull_requests_success(self, mock_get):
        """Test successful pull request fetching."""
        # Mock repository data
        test_repository = {
            "id": "repo-1",
            "name": "test-repo",
            "url": "https://dev.azure.com/test-org/test-project/_apis/git/repositories/repo-1",
        }

        # Mock PR API response
        mock_pr_response = {
            "value": [
                {
                    "pullRequestId": 123,
                    "title": "Test PR",
                    "description": "Test description",
                    "createdBy": {
                        "displayName": "John Doe",
                        "uniqueName": "john@example.com",
                    },
                    "creationDate": "2023-01-01T00:00:00Z",
                    "status": "completed",
                    "repository": test_repository,
                    "reviewers": [],
                }
            ]
        }

        mock_get.return_value = MockResponse(mock_pr_response)

        # Execute test
        pull_requests = self.client.fetch_pull_requests_for_repository(test_repository)

        # Verify results
        self.assertEqual(len(pull_requests), 1)
        self.assertEqual(pull_requests[0]["pullRequestId"], 123)
        self.assertEqual(pull_requests[0]["title"], "Test PR")

        # Verify API call
        mock_get.assert_called()
        call_args = mock_get.call_args
        self.assertIn("pullrequests", call_args[0][0])

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_fetch_pull_requests_with_pagination(self, mock_get):
        """Test pull request fetching with pagination."""
        test_repository = {"id": "repo-1", "name": "test-repo"}

        # Mock paginated responses
        page1_response = {
            "value": [{"pullRequestId": 1, "title": "PR 1"}],
            "continuationToken": "token123",
        }

        page2_response = {"value": [{"pullRequestId": 2, "title": "PR 2"}]}

        # Configure mock to return different responses for each call
        mock_get.side_effect = [
            MockResponse(page1_response),
            MockResponse(page2_response),
        ]

        # Execute test
        pull_requests = self.client.fetch_pull_requests_for_repository(test_repository)

        # Verify results from both pages
        self.assertEqual(len(pull_requests), 2)
        self.assertEqual(pull_requests[0]["pullRequestId"], 1)
        self.assertEqual(pull_requests[1]["pullRequestId"], 2)

        # Verify multiple API calls were made
        self.assertEqual(mock_get.call_count, 2)

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_rate_limit_handling(self, mock_get):
        """Test rate limit handling."""
        # Mock rate limit response followed by success
        rate_limit_response = MockResponse(
            {}, status_code=429, headers={"Retry-After": "1"}
        )
        success_response = MockResponse({"value": []})

        mock_get.side_effect = [rate_limit_response, success_response]

        with patch("time.sleep") as mock_sleep:
            repositories = self.client.fetch_repositories()

            # Verify sleep was called for rate limiting
            mock_sleep.assert_called_with(1)

            # Verify retry was successful
            self.assertEqual(repositories, [])

    def test_session_configuration(self):
        """Test that session is properly configured."""
        session = self.client.session

        # Verify authentication header
        self.assertIn("Authorization", session.headers)
        self.assertTrue(session.headers["Authorization"].startswith("Basic"))

        # Verify content type
        self.assertEqual(session.headers["Content-Type"], "application/json")

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_error_recovery(self, mock_get):
        """Test error recovery and retry logic."""
        # Mock network error followed by success
        mock_get.side_effect = [
            requests.ConnectionError("Network error"),
            MockResponse({"value": []}),
        ]

        with patch("time.sleep"):
            repositories = self.client.fetch_all_repositories()

            # Verify retry was attempted
            self.assertEqual(mock_get.call_count, 2)
            self.assertEqual(repositories, [])


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

    @patch("azure_pr_analytics.clients.github_client.requests.Session.get")
    def test_fetch_repositories_success(self, mock_get):
        """Test successful GitHub repository fetching."""
        # Mock GitHub API response
        mock_response_data = [
            {
                "id": 123,
                "name": "test-repo-1",
                "full_name": "test-org/test-repo-1",
                "private": False,
                "html_url": "https://github.com/test-org/test-repo-1",
            },
            {
                "id": 456,
                "name": "test-repo-2",
                "full_name": "test-org/test-repo-2",
                "private": True,
                "html_url": "https://github.com/test-org/test-repo-2",
            },
        ]

        mock_get.return_value = MockResponse(mock_response_data)

        # Execute test
        repositories = self.client.fetch_all_repositories()

        # Verify results
        self.assertEqual(len(repositories), 2)
        self.assertEqual(repositories[0]["name"], "test-repo-1")
        self.assertEqual(repositories[1]["name"], "test-repo-2")

        # Verify API call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("orgs/test-org/repos", call_args[0][0])

    @patch("azure_pr_analytics.clients.github_client.requests.Session.get")
    def test_fetch_pull_requests_success(self, mock_get):
        """Test successful GitHub pull request fetching."""
        # Mock repository data
        test_repository = {
            "id": 123,
            "name": "test-repo",
            "full_name": "test-org/test-repo",
        }

        # Mock PR API response
        mock_pr_response = [
            {
                "id": 789,
                "number": 42,
                "title": "Test GitHub PR",
                "body": "Test description",
                "user": {"login": "developer"},
                "created_at": "2023-01-01T00:00:00Z",
                "state": "closed",
                "merged": True,
                "base": {"ref": "main"},
                "head": {"ref": "feature-branch"},
            }
        ]

        mock_get.return_value = MockResponse(mock_pr_response)

        # Execute test
        pull_requests = self.client.fetch_pull_requests_for_repository(test_repository)

        # Verify results
        self.assertEqual(len(pull_requests), 1)
        self.assertEqual(pull_requests[0]["id"], 789)
        self.assertEqual(pull_requests[0]["title"], "Test GitHub PR")
        self.assertEqual(pull_requests[0]["repository_name"], "test-repo")

        # Verify API call
        mock_get.assert_called()
        call_args = mock_get.call_args
        self.assertIn("repos/test-org/test-repo/pulls", call_args[0][0])

    @patch("azure_pr_analytics.clients.github_client.requests.Session.get")
    def test_github_pagination_with_link_header(self, mock_get):
        """Test GitHub pagination using Link headers."""
        test_repository = {
            "id": 123,
            "name": "test-repo",
            "full_name": "test-org/test-repo",
        }

        # Mock paginated responses
        page1_response = MockResponse(
            [{"id": 1, "title": "PR 1"}],
            headers={
                "Link": '<https://api.github.com/repos/test-org/test-repo/pulls?page=2>; rel="next"'
            },
        )

        page2_response = MockResponse([{"id": 2, "title": "PR 2"}])

        mock_get.side_effect = [page1_response, page2_response]

        # Execute test
        pull_requests = self.client.fetch_pull_requests_for_repository(test_repository)

        # Verify results from both pages
        self.assertEqual(len(pull_requests), 2)
        self.assertEqual(pull_requests[0]["id"], 1)
        self.assertEqual(pull_requests[1]["id"], 2)

        # Verify multiple API calls were made
        self.assertEqual(mock_get.call_count, 2)

    @patch("azure_pr_analytics.clients.github_client.requests.Session.get")
    def test_github_rate_limit_handling(self, mock_get):
        """Test GitHub rate limit handling."""
        # Mock rate limit response with proper headers
        rate_limit_response = MockResponse(
            {"message": "API rate limit exceeded"},
            status_code=403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + 3600),
            },
        )

        success_response = MockResponse([])

        mock_get.side_effect = [rate_limit_response, success_response]

        with patch("time.sleep") as mock_sleep:
            repositories = self.client.fetch_all_repositories()

            # Verify sleep was called for rate limiting
            mock_sleep.assert_called()

            # Verify retry was successful
            self.assertEqual(repositories, [])

    @patch("azure_pr_analytics.clients.github_client.requests.Session.get")
    def test_fetch_pr_reviews_and_comments(self, mock_get):
        """Test fetching PR reviews and comments."""
        test_repository = {
            "id": 123,
            "name": "test-repo",
            "full_name": "test-org/test-repo",
        }

        # Mock PR response
        pr_response = [
            {
                "id": 789,
                "number": 42,
                "title": "Test PR",
                "user": {"login": "developer"},
                "created_at": "2023-01-01T00:00:00Z",
                "state": "closed",
            }
        ]

        # Mock reviews response
        reviews_response = [
            {
                "id": 101,
                "user": {"login": "reviewer1"},
                "state": "APPROVED",
                "submitted_at": "2023-01-02T00:00:00Z",
            }
        ]

        # Mock comments response
        comments_response = [
            {
                "id": 201,
                "user": {"login": "commenter"},
                "body": "Great work!",
                "created_at": "2023-01-01T12:00:00Z",
            }
        ]

        # Configure mock responses
        mock_get.side_effect = [
            MockResponse(pr_response),  # PRs
            MockResponse(reviews_response),  # Reviews
            MockResponse(comments_response),  # Comments
        ]

        # Execute test
        pull_requests = self.client.fetch_pull_requests_for_repository(test_repository)

        # Verify PR data was enhanced with reviews and comments
        self.assertEqual(len(pull_requests), 1)
        pr = pull_requests[0]

        self.assertIn("reviews", pr)
        self.assertIn("comments", pr)
        self.assertEqual(len(pr["reviews"]), 1)
        self.assertEqual(len(pr["comments"]), 1)

        # Verify multiple API calls were made
        self.assertEqual(mock_get.call_count, 3)

    def test_parse_link_header(self):
        """Test parsing GitHub Link headers."""
        link_header = '<https://api.github.com/repos/test/repo/pulls?page=2>; rel="next", <https://api.github.com/repos/test/repo/pulls?page=5>; rel="last"'

        links = self.client._parse_link_header(link_header)

        self.assertIn("next", links)
        self.assertIn("last", links)
        self.assertEqual(
            links["next"], "https://api.github.com/repos/test/repo/pulls?page=2"
        )
        self.assertEqual(
            links["last"], "https://api.github.com/repos/test/repo/pulls?page=5"
        )

    def test_session_configuration(self):
        """Test that GitHub session is properly configured."""
        session = self.client.session

        # Verify authentication header
        self.assertIn("Authorization", session.headers)
        self.assertTrue(session.headers["Authorization"].startswith("Bearer"))

        # Verify user agent
        self.assertIn("User-Agent", session.headers)


class TestAPIClientErrorHandling(unittest.TestCase):
    """Test error handling across API clients."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.max_parallel_workers = 4
        self.mock_logger = Mock()

    @patch("azure_pr_analytics.clients.azure_devops_client.requests.Session.get")
    def test_azure_devops_network_error_recovery(self, mock_get):
        """Test Azure DevOps client network error recovery."""
        client = AzureDevOpsClient(
            self.mock_config, self.mock_logger, enable_cache=False
        )

        # Mock network errors followed by success
        mock_get.side_effect = [
            requests.ConnectionError("Connection failed"),
            requests.Timeout("Request timeout"),
            MockResponse({"value": []}),
        ]

        with patch("time.sleep"):
            result = client.fetch_all_repositories()

            # Verify retries were attempted
            self.assertEqual(mock_get.call_count, 3)
            self.assertEqual(result, [])

    @patch("azure_pr_analytics.clients.github_client.requests.Session.get")
    def test_github_authentication_error(self, mock_get):
        """Test GitHub client authentication error handling."""
        client = GitHubClient(self.mock_config, self.mock_logger, enable_cache=False)

        # Mock authentication error
        mock_get.return_value = MockResponse(
            {"message": "Bad credentials"}, status_code=401
        )

        result = client.fetch_all_repositories()

        # Verify empty result and error logging
        self.assertEqual(result, [])
        self.mock_logger.error.assert_called()

    def test_invalid_configuration_handling(self):
        """Test handling of invalid configuration."""
        invalid_config = Mock()
        invalid_config.azure_devops_organization = None
        invalid_config.azure_devops_token = None
        invalid_config.max_parallel_workers = 4

        # This should not raise an exception
        client = AzureDevOpsClient(invalid_config, self.mock_logger)
        self.assertIsNotNone(client)


if __name__ == "__main__":
    # Import time for rate limit tests
    import time

    # Create test suite
    test_suite = unittest.TestSuite()

    # Add test cases
    test_classes = [
        TestAzureDevOpsClientIntegration,
        TestGitHubClientIntegration,
        TestAPIClientErrorHandling,
    ]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
