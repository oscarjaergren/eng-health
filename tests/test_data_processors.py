"""Unit tests for data processors."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from azure_pr_analytics.processors.azure_devops_data_processor import (
    AzureDevOpsDataProcessor,
)
from azure_pr_analytics.processors.base_data_processor import BaseDataProcessor
from azure_pr_analytics.processors.github_data_processor import GitHubDataProcessor
from azure_pr_analytics.processors.unified_data_processor import UnifiedDataProcessor

# Add azure_pr_analytics directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBaseDataProcessor(unittest.TestCase):
    """Test cases for BaseDataProcessor."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()

        # Create a concrete implementation for testing
        class ConcreteProcessor(BaseDataProcessor):
            def process_pull_request_data(self, pr_data):
                return pr_data

        self.processor = ConcreteProcessor(self.mock_logger)

    def test_initialization(self):
        """Test processor initialization."""
        self.assertIsNotNone(self.processor.logger)
        self.assertEqual(self.processor.processed_data, [])

    def test_validate_pr_data_valid(self):
        """Test validation with valid PR data."""
        valid_pr = {
            "id": 123,
            "title": "Test PR",
            "created_date": "2023-01-01T00:00:00Z",
            "status": "completed",
        }

        result = self.processor._validate_pr_data(valid_pr)
        self.assertTrue(result)

    def test_validate_pr_data_invalid(self):
        """Test validation with invalid PR data."""
        # Missing required fields
        invalid_pr = {"title": "Test PR"}

        result = self.processor._validate_pr_data(invalid_pr)
        self.assertFalse(result)

    def test_validate_pr_data_none(self):
        """Test validation with None input."""
        result = self.processor._validate_pr_data(None)
        self.assertFalse(result)

    def test_sanitize_string_normal(self):
        """Test string sanitization with normal input."""
        test_string = "Normal string"
        result = self.processor._sanitize_string(test_string)
        self.assertEqual(result, "Normal string")

    def test_sanitize_string_with_html(self):
        """Test string sanitization with HTML tags."""
        test_string = "<script>alert('xss')</script>Normal content"
        result = self.processor._sanitize_string(test_string)
        self.assertNotIn("<script>", result)
        self.assertIn("Normal content", result)

    def test_sanitize_string_none(self):
        """Test string sanitization with None input."""
        result = self.processor._sanitize_string(None)
        self.assertEqual(result, "")

    def test_safe_get_nested_value_exists(self):
        """Test getting nested value that exists."""
        data = {"user": {"profile": {"name": "John Doe"}}}

        result = self.processor._safe_get_nested_value(
            data, ["user", "profile", "name"]
        )
        self.assertEqual(result, "John Doe")

    def test_safe_get_nested_value_missing(self):
        """Test getting nested value that doesn't exist."""
        data = {"user": {"profile": {}}}

        result = self.processor._safe_get_nested_value(
            data, ["user", "profile", "name"], "Default"
        )
        self.assertEqual(result, "Default")

    def test_safe_get_nested_value_none_data(self):
        """Test getting nested value from None data."""
        result = self.processor._safe_get_nested_value(None, ["key"], "Default")
        self.assertEqual(result, "Default")


class TestAzureDevOpsDataProcessor(unittest.TestCase):
    """Test cases for AzureDevOpsDataProcessor."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.processor = AzureDevOpsDataProcessor(self.mock_logger)

    def test_process_pull_request_data_valid(self):
        """Test processing valid Azure DevOps PR data."""
        mock_pr_data = [
            {
                "id": 123,
                "title": "Test PR",
                "createdBy": {
                    "displayName": "John Doe",
                    "uniqueName": "john@example.com",
                },
                "creationDate": "2023-01-01T00:00:00Z",
                "status": "completed",
                "repository": {"name": "test-repo"},
                "reviewers": [
                    {
                        "displayName": "Jane Smith",
                        "uniqueName": "jane@example.com",
                        "vote": 10,
                    }
                ],
            }
        ]

        result = self.processor.process_pull_request_data(mock_pr_data)

        self.assertEqual(len(result), 1)
        processed_pr = result[0]

        self.assertEqual(processed_pr["PR ID"], 123)
        self.assertEqual(processed_pr["Title"], "Test PR")
        self.assertEqual(processed_pr["Created By"], "John Doe")
        self.assertEqual(processed_pr["Repository"], "test-repo")
        self.assertIn("Jane Smith", processed_pr["Assigned To"])

    def test_process_pull_request_data_empty(self):
        """Test processing empty PR data."""
        result = self.processor.process_pull_request_data([])
        self.assertEqual(result, [])

    def test_process_pull_request_data_invalid(self):
        """Test processing invalid PR data."""
        invalid_data = [{"invalid": "data"}]

        result = self.processor.process_pull_request_data(invalid_data)
        self.assertEqual(result, [])

        # Check that error was logged
        self.mock_logger.warning.assert_called()

    def test_extract_reviewer_info_approved(self):
        """Test extracting reviewer info for approved review."""
        reviewer = {
            "displayName": "John Doe",
            "uniqueName": "john@example.com",
            "vote": 10,
        }

        name, status = self.processor._extract_reviewer_info(reviewer)

        self.assertEqual(name, "John Doe")
        self.assertEqual(status, "Approved")

    def test_extract_reviewer_info_rejected(self):
        """Test extracting reviewer info for rejected review."""
        reviewer = {
            "displayName": "Jane Smith",
            "uniqueName": "jane@example.com",
            "vote": -10,
        }

        name, status = self.processor._extract_reviewer_info(reviewer)

        self.assertEqual(name, "Jane Smith")
        self.assertEqual(status, "Rejected")

    def test_extract_reviewer_info_waiting(self):
        """Test extracting reviewer info for waiting review."""
        reviewer = {
            "displayName": "Bob Wilson",
            "uniqueName": "bob@example.com",
            "vote": 0,
        }

        name, status = self.processor._extract_reviewer_info(reviewer)

        self.assertEqual(name, "Bob Wilson")
        self.assertEqual(status, "Waiting for author")


class TestGitHubDataProcessor(unittest.TestCase):
    """Test cases for GitHubDataProcessor."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.processor = GitHubDataProcessor(self.mock_logger)

    def test_process_pull_request_data_valid(self):
        """Test processing valid GitHub PR data."""
        mock_pr_data = [
            {
                "id": 456,
                "title": "GitHub Test PR",
                "user": {"login": "johndoe"},
                "created_at": "2023-01-01T00:00:00Z",
                "state": "closed",
                "merged": True,
                "repository_name": "test-repo",
                "reviews": [
                    {
                        "user": {"login": "janesmith"},
                        "state": "APPROVED",
                        "submitted_at": "2023-01-02T00:00:00Z",
                    }
                ],
            }
        ]

        result = self.processor.process_pull_request_data(mock_pr_data)

        self.assertEqual(len(result), 1)
        processed_pr = result[0]

        self.assertEqual(processed_pr["PR ID"], 456)
        self.assertEqual(processed_pr["Title"], "GitHub Test PR")
        self.assertEqual(processed_pr["Created By"], "johndoe")
        self.assertEqual(processed_pr["Repository"], "test-repo")
        self.assertEqual(processed_pr["Status"], "Merged")

    def test_convert_github_review_state(self):
        """Test GitHub review state conversion."""
        test_cases = [
            ("APPROVED", "Approved"),
            ("CHANGES_REQUESTED", "Rejected"),
            ("COMMENTED", "Commented"),
            ("DISMISSED", "Waiting for author"),
            ("UNKNOWN_STATE", "Waiting for author"),
        ]

        for github_state, expected_status in test_cases:
            result = self.processor._convert_github_review_state(github_state)
            self.assertEqual(result, expected_status)

    def test_extract_github_status_open(self):
        """Test extracting GitHub PR status for open PR."""
        pr_data = {"state": "open", "merged": False}
        result = self.processor._extract_github_status(pr_data)
        self.assertEqual(result, "Active")

    def test_extract_github_status_merged(self):
        """Test extracting GitHub PR status for merged PR."""
        pr_data = {"state": "closed", "merged": True}
        result = self.processor._extract_github_status(pr_data)
        self.assertEqual(result, "Merged")

    def test_extract_github_status_closed(self):
        """Test extracting GitHub PR status for closed PR."""
        pr_data = {"state": "closed", "merged": False}
        result = self.processor._extract_github_status(pr_data)
        self.assertEqual(result, "Abandoned")


class TestUnifiedDataProcessor(unittest.TestCase):
    """Test cases for UnifiedDataProcessor."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.mock_azure_processor = Mock()
        self.mock_github_processor = Mock()

        with patch(
            "azure_pr_analytics.processors.unified_data_processor.AzureDevOpsDataProcessor",
            return_value=self.mock_azure_processor,
        ), patch(
            "azure_pr_analytics.processors.unified_data_processor.GitHubDataProcessor",
            return_value=self.mock_github_processor,
        ):
            self.processor = UnifiedDataProcessor(self.mock_logger)

    def test_process_mixed_data(self):
        """Test processing mixed Azure DevOps and GitHub data."""
        azure_data = [{"platform": "azure_devops", "id": 1}]
        github_data = [{"platform": "github", "id": 2}]

        self.mock_azure_processor.process_pull_request_data.return_value = [
            {"PR ID": 1, "Platform": "Azure DevOps"}
        ]
        self.mock_github_processor.process_pull_request_data.return_value = [
            {"PR ID": 2, "Platform": "GitHub"}
        ]

        result = self.processor.process_pull_request_data(azure_data + github_data)

        self.assertEqual(len(result), 2)
        self.mock_azure_processor.process_pull_request_data.assert_called_once()
        self.mock_github_processor.process_pull_request_data.assert_called_once()

    def test_identify_platform_azure(self):
        """Test platform identification for Azure DevOps data."""
        azure_pr = {"createdBy": {"displayName": "User"}}
        result = self.processor._identify_platform(azure_pr)
        self.assertEqual(result, "azure_devops")

    def test_identify_platform_github(self):
        """Test platform identification for GitHub data."""
        github_pr = {"user": {"login": "user"}}
        result = self.processor._identify_platform(github_pr)
        self.assertEqual(result, "github")

    def test_identify_platform_unknown(self):
        """Test platform identification for unknown data."""
        unknown_pr = {"unknown_field": "value"}
        result = self.processor._identify_platform(unknown_pr)
        self.assertEqual(result, "unknown")

    def test_save_to_excel_success(self):
        """Test successful Excel file saving."""
        test_data = [
            {"PR ID": 1, "Title": "Test PR 1"},
            {"PR ID": 2, "Title": "Test PR 2"},
        ]

        with patch("pandas.DataFrame.to_excel") as mock_to_excel:
            result = self.processor.save_to_excel(test_data, "test_output.xlsx")

            self.assertTrue(result)
            mock_to_excel.assert_called_once()

    def test_save_to_excel_failure(self):
        """Test Excel file saving failure."""
        test_data = [{"PR ID": 1, "Title": "Test PR"}]

        with patch("pandas.DataFrame.to_excel", side_effect=Exception("Write error")):
            result = self.processor.save_to_excel(test_data, "test_output.xlsx")

            self.assertFalse(result)
            self.mock_logger.error.assert_called()


class TestDataProcessorIntegration(unittest.TestCase):
    """Integration tests for data processors."""

    def setUp(self):
        """Set up integration test fixtures."""
        self.mock_logger = Mock()

    def test_end_to_end_azure_processing(self):
        """Test end-to-end Azure DevOps data processing."""
        processor = AzureDevOpsDataProcessor(self.mock_logger)

        # Simulate realistic Azure DevOps PR data
        sample_data = [
            {
                "id": 123,
                "title": "Add new feature",
                "description": "This PR adds a new feature to the application",
                "createdBy": {
                    "displayName": "John Developer",
                    "uniqueName": "john.developer@company.com",
                },
                "creationDate": "2023-06-15T10:30:00Z",
                "closedDate": "2023-06-16T14:20:00Z",
                "status": "completed",
                "repository": {"name": "main-application", "id": "repo-123"},
                "reviewers": [
                    {
                        "displayName": "Jane Reviewer",
                        "uniqueName": "jane.reviewer@company.com",
                        "vote": 10,
                        "isRequired": True,
                    },
                    {
                        "displayName": "Bob Approver",
                        "uniqueName": "bob.approver@company.com",
                        "vote": 5,
                        "isRequired": False,
                    },
                ],
                "targetRefName": "refs/heads/main",
                "sourceRefName": "refs/heads/feature/new-feature",
            }
        ]

        result = processor.process_pull_request_data(sample_data)

        # Verify the processed result
        self.assertEqual(len(result), 1)

        processed_pr = result[0]
        self.assertEqual(processed_pr["PR ID"], 123)
        self.assertEqual(processed_pr["Title"], "Add new feature")
        self.assertEqual(processed_pr["Created By"], "John Developer")
        self.assertEqual(processed_pr["Repository"], "main-application")
        self.assertEqual(processed_pr["Status"], "Completed")
        self.assertIn("Jane Reviewer", processed_pr["Assigned To"])
        self.assertIn("Bob Approver", processed_pr["Assigned To"])

    def test_end_to_end_github_processing(self):
        """Test end-to-end GitHub data processing."""
        processor = GitHubDataProcessor(self.mock_logger)

        # Simulate realistic GitHub PR data
        sample_data = [
            {
                "id": 456,
                "number": 42,
                "title": "Fix critical bug",
                "body": "This PR fixes a critical bug in the payment system",
                "user": {"login": "developer123"},
                "created_at": "2023-06-15T10:30:00Z",
                "updated_at": "2023-06-16T14:20:00Z",
                "closed_at": "2023-06-16T14:20:00Z",
                "merged_at": "2023-06-16T14:20:00Z",
                "state": "closed",
                "merged": True,
                "repository_name": "payment-service",
                "base": {"ref": "main"},
                "head": {"ref": "bugfix/payment-issue"},
                "reviews": [
                    {
                        "id": 789,
                        "user": {"login": "reviewer1"},
                        "state": "APPROVED",
                        "submitted_at": "2023-06-16T12:00:00Z",
                    },
                    {
                        "id": 790,
                        "user": {"login": "reviewer2"},
                        "state": "CHANGES_REQUESTED",
                        "submitted_at": "2023-06-16T11:00:00Z",
                    },
                ],
            }
        ]

        result = processor.process_pull_request_data(sample_data)

        # Verify the processed result
        self.assertEqual(len(result), 1)

        processed_pr = result[0]
        self.assertEqual(processed_pr["PR ID"], 456)
        self.assertEqual(processed_pr["Title"], "Fix critical bug")
        self.assertEqual(processed_pr["Created By"], "developer123")
        self.assertEqual(processed_pr["Repository"], "payment-service")
        self.assertEqual(processed_pr["Status"], "Merged")
        self.assertIn("reviewer1", processed_pr["Assigned To"])
        self.assertIn("reviewer2", processed_pr["Assigned To"])


if __name__ == "__main__":
    # Create test suite
    test_suite = unittest.TestSuite()

    # Add test cases
    test_classes = [
        TestBaseDataProcessor,
        TestAzureDevOpsDataProcessor,
        TestGitHubDataProcessor,
        TestUnifiedDataProcessor,
        TestDataProcessorIntegration,
    ]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
