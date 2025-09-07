"""
Standalone PR Filtering Tests

Tests the filtering logic for PRs using mock data to verify:
- IAC PR filtering
- Personal approval filtering
- System account filtering
- Data processing accuracy
"""

import pytest
import logging
from typing import List, Dict, Any
from azure_pr_analytics.utils.mock_data_generator import MockDataGenerator
from azure_pr_analytics.processors.azure_devops_data_processor import (
    AzureDevOpsDataProcessor,
)
from azure_pr_analytics.processors.github_data_processor import GitHubDataProcessor


class MockConfig:
    """Mock configuration for testing."""

    def __init__(
        self, exclude_iac: bool = True, exclude_personal_approvals: bool = True
    ):
        self.exclude_iac = exclude_iac
        self.exclude_personal_approvals = exclude_personal_approvals
        self.system_accounts = ["system", "bot", "automation"]
        self.iac_keywords = [
            "terraform",
            "docker",
            "kubernetes",
            "ansible",
            "ci/cd",
            "pipeline",
            "deployment",
            "infrastructure",
            "config",
            "environment",
        ]


class TestPRFiltering:
    """Test cases for PR filtering functionality."""

    @pytest.fixture
    def mock_generator(self):
        """Create a mock data generator with fixed seed for reproducible tests."""
        return MockDataGenerator(seed=42)

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        return MockConfig()

    @pytest.fixture
    def logger(self):
        """Create a logger for testing."""
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)

    def test_azure_devops_iac_filtering(self, mock_generator, mock_config, logger):
        """Test that IAC PRs are properly filtered out in Azure DevOps data."""
        # Generate test data with IAC PRs
        test_data = mock_generator.generate_azure_devops_pr_data(
            count=20, include_iac=True, include_personal_approvals=False
        )

        # Count IAC PRs in raw data
        iac_count = sum(
            1
            for pr in test_data
            if any(
                keyword.lower() in pr["title"].lower()
                for keyword in mock_config.iac_keywords
            )
        )

        # Process data with IAC filtering enabled
        processor = AzureDevOpsDataProcessor(logger, mock_config)
        processed_data = processor.process_pull_requests(test_data)

        # Verify IAC PRs are filtered out
        remaining_iac = sum(
            1
            for pr in processed_data
            if any(
                keyword.lower() in pr["Title"].lower()
                for keyword in mock_config.iac_keywords
            )
        )

        assert (
            remaining_iac == 0
        ), f"Expected 0 IAC PRs after filtering, found {remaining_iac}"
        assert (
            len(processed_data) == len(test_data) - iac_count
        ), f"Expected {len(test_data) - iac_count} PRs after filtering, got {len(processed_data)}"

    def test_azure_devops_personal_approval_filtering(
        self, mock_generator, mock_config, logger
    ):
        """Test that personal approvals are properly filtered out in Azure DevOps data."""
        # Generate test data with personal approvals
        test_data = mock_generator.generate_azure_devops_pr_data(
            count=20, include_iac=False, include_personal_approvals=True
        )

        # Process data with personal approval filtering enabled
        processor = AzureDevOpsDataProcessor(logger, mock_config)
        processed_data = processor.process_pull_requests(test_data)

        # Verify no PR has self-approvals
        for pr in processed_data:
            creator_email = None
            # Find creator email from original data
            original_pr = next(p for p in test_data if p["pullRequestId"] == pr["ID"])
            creator_email = original_pr["createdBy"]["uniqueName"]

            approved_by = pr.get("Approved By", [])
            if approved_by:
                # Check that creator is not in the approved by list
                creator_in_approvals = any(
                    creator_email in str(approval) for approval in approved_by
                )
                assert (
                    not creator_in_approvals
                ), f"PR {pr['ID']} still contains self-approval from {creator_email}"

    def test_github_iac_filtering(self, mock_generator, mock_config, logger):
        """Test that IAC PRs are properly filtered out in GitHub data."""
        # Generate test data with IAC PRs
        test_data = mock_generator.generate_github_pr_data(
            count=20, include_iac=True, include_personal_approvals=False
        )

        # Count IAC PRs in raw data
        iac_count = sum(
            1
            for pr in test_data
            if any(
                keyword.lower() in pr["title"].lower()
                for keyword in mock_config.iac_keywords
            )
        )

        # Process data with IAC filtering enabled
        processor = GitHubDataProcessor(logger, mock_config)
        processed_data = processor.process_pull_requests(test_data)

        # Verify IAC PRs are filtered out
        remaining_iac = sum(
            1
            for pr in processed_data
            if any(
                keyword.lower() in pr["Title"].lower()
                for keyword in mock_config.iac_keywords
            )
        )

        assert (
            remaining_iac == 0
        ), f"Expected 0 IAC PRs after filtering, found {remaining_iac}"
        assert (
            len(processed_data) == len(test_data) - iac_count
        ), f"Expected {len(test_data) - iac_count} PRs after filtering, got {len(processed_data)}"

    def test_github_personal_approval_filtering(
        self, mock_generator, mock_config, logger
    ):
        """Test that personal approvals are properly filtered out in GitHub data."""
        # Generate test data with personal approvals
        test_data = mock_generator.generate_github_pr_data(
            count=20, include_iac=False, include_personal_approvals=True
        )

        # Process data with personal approval filtering enabled
        processor = GitHubDataProcessor(logger, mock_config)
        processed_data = processor.process_pull_requests(test_data)

        # Verify no PR has self-approvals
        for pr in processed_data:
            creator_login = None
            # Find creator login from original data
            original_pr = next(p for p in test_data if p["number"] == pr["ID"])
            creator_login = original_pr["user"]["login"]

            approved_by = pr.get("Approved By", [])
            if approved_by:
                # Check that creator is not in the approved by list
                creator_in_approvals = any(
                    creator_login in str(approval) for approval in approved_by
                )
                assert (
                    not creator_in_approvals
                ), f"PR {pr['ID']} still contains self-approval from {creator_login}"

    def test_filtering_disabled(self, mock_generator, logger):
        """Test that filtering can be disabled."""
        # Create config with filtering disabled
        config = MockConfig(exclude_iac=False, exclude_personal_approvals=False)

        # Generate test data with IAC and personal approvals
        test_data = mock_generator.generate_azure_devops_pr_data(
            count=10, include_iac=True, include_personal_approvals=True
        )

        # Process data with filtering disabled
        processor = AzureDevOpsDataProcessor(logger, config)
        processed_data = processor.process_pull_requests(test_data)

        # Should have same number of PRs (no filtering)
        assert len(processed_data) == len(
            test_data
        ), f"Expected {len(test_data)} PRs with filtering disabled, got {len(processed_data)}"

    def test_data_structure_consistency(self, mock_generator, mock_config, logger):
        """Test that processed data maintains consistent structure."""
        # Test both platforms
        azure_data = mock_generator.generate_azure_devops_pr_data(count=5)
        github_data = mock_generator.generate_github_pr_data(count=5)

        azure_processor = AzureDevOpsDataProcessor(logger, mock_config)
        github_processor = GitHubDataProcessor(logger, mock_config)

        azure_processed = azure_processor.process_pull_requests(azure_data)
        github_processed = github_processor.process_pull_requests(github_data)

        # Check that both platforms produce consistent field names
        expected_fields = {
            "ID",
            "Repository",
            "Title",
            "Description",
            "Created By",
            "Created Date",
            "Status",
            "Platform",
            "Approved By",
            "Total Reviewers",
        }

        for pr in azure_processed:
            assert expected_fields.issubset(
                set(pr.keys())
            ), f"Azure DevOps PR missing expected fields: {expected_fields - set(pr.keys())}"

        for pr in github_processed:
            assert expected_fields.issubset(
                set(pr.keys())
            ), f"GitHub PR missing expected fields: {expected_fields - set(pr.keys())}"

    def test_empty_data_handling(self, mock_config, logger):
        """Test that processors handle empty data gracefully."""
        azure_processor = AzureDevOpsDataProcessor(logger, mock_config)
        github_processor = GitHubDataProcessor(logger, mock_config)

        # Test empty lists
        assert azure_processor.process_pull_requests([]) == []
        assert github_processor.process_pull_requests([]) == []

    def test_malformed_data_handling(self, mock_config, logger):
        """Test that processors handle malformed data gracefully."""
        azure_processor = AzureDevOpsDataProcessor(logger, mock_config)
        github_processor = GitHubDataProcessor(logger, mock_config)

        # Test with malformed data (missing required fields)
        malformed_azure = [{"pullRequestId": 1}]  # Missing required fields
        malformed_github = [{"number": 1}]  # Missing required fields

        # Should not crash, might return empty or handle gracefully
        try:
            azure_result = azure_processor.process_pull_requests(malformed_azure)
            github_result = github_processor.process_pull_requests(malformed_github)
            # If it doesn't crash, that's good enough for this test
            assert isinstance(azure_result, list)
            assert isinstance(github_result, list)
        except Exception as e:
            # If it does crash, it should be a meaningful error
            assert "required field" in str(e).lower() or "missing" in str(e).lower()


class TestMockDataGenerator:
    """Test cases for the mock data generator itself."""

    def test_reproducible_generation(self):
        """Test that the same seed produces the same data."""
        gen1 = MockDataGenerator(seed=123)
        gen2 = MockDataGenerator(seed=123)

        data1 = gen1.generate_azure_devops_pr_data(count=5)
        data2 = gen2.generate_azure_devops_pr_data(count=5)

        # Should generate identical data with same seed
        assert len(data1) == len(data2)
        for pr1, pr2 in zip(data1, data2):
            assert pr1["pullRequestId"] == pr2["pullRequestId"]
            assert pr1["title"] == pr2["title"]

    def test_data_counts(self):
        """Test that generator produces requested number of PRs."""
        generator = MockDataGenerator(seed=42)

        azure_data = generator.generate_azure_devops_pr_data(count=10)
        github_data = generator.generate_github_pr_data(count=15)
        mixed_data = generator.generate_mixed_data(azure_count=5, github_count=7)

        assert len(azure_data) == 10
        assert len(github_data) == 15
        assert len(mixed_data["azure_devops"]) == 5
        assert len(mixed_data["github"]) == 7

    def test_iac_inclusion_control(self):
        """Test that IAC PR inclusion can be controlled."""
        generator = MockDataGenerator(seed=42)

        # Generate data with IAC
        with_iac = generator.generate_azure_devops_pr_data(count=50, include_iac=True)
        without_iac = generator.generate_azure_devops_pr_data(
            count=50, include_iac=False
        )

        # Count IAC PRs
        iac_keywords = [
            "terraform",
            "docker",
            "kubernetes",
            "ansible",
            "ci/cd",
            "pipeline",
        ]
        iac_count_with = sum(
            1
            for pr in with_iac
            if any(keyword.lower() in pr["title"].lower() for keyword in iac_keywords)
        )
        iac_count_without = sum(
            1
            for pr in without_iac
            if any(keyword.lower() in pr["title"].lower() for keyword in iac_keywords)
        )

        # Should have IAC PRs when enabled, none when disabled
        assert iac_count_with > 0, "Should have IAC PRs when include_iac=True"
        assert iac_count_without == 0, "Should have no IAC PRs when include_iac=False"

    def test_excel_format_generation(self):
        """Test that Excel-compatible format is generated correctly."""
        generator = MockDataGenerator(seed=42)
        excel_data = generator.generate_excel_compatible_data(count=5)

        assert len(excel_data) == 5

        # Check required fields for dashboard compatibility
        required_fields = [
            "PR ID",
            "Repository",
            "Title",
            "Created By",
            "Created Date",
            "Status",
            "Platform",
            "Approved By",
            "Total Reviewers",
        ]

        for pr in excel_data:
            for field in required_fields:
                assert field in pr, f"Missing required field: {field}"


def run_filtering_tests():
    """
    Run filtering tests manually without pytest.
    Useful for quick validation during development.
    """
    print("🧪 Running PR Filtering Tests...")

    # Setup
    generator = MockDataGenerator(seed=42)
    config = MockConfig()
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

    # Test 1: Azure DevOps IAC Filtering
    print("\n1️⃣ Testing Azure DevOps IAC Filtering...")
    azure_data = generator.generate_azure_devops_pr_data(count=20, include_iac=True)
    iac_count = sum(
        1
        for pr in azure_data
        if any(
            keyword.lower() in pr["title"].lower() for keyword in config.iac_keywords
        )
    )

    processor = AzureDevOpsDataProcessor(logger, config)
    processed = processor.process_pull_requests(azure_data)

    remaining_iac = sum(
        1
        for pr in processed
        if any(
            keyword.lower() in pr["Title"].lower() for keyword in config.iac_keywords
        )
    )

    print(f"   📊 Original PRs: {len(azure_data)}, IAC PRs: {iac_count}")
    print(f"   ✅ After filtering: {len(processed)} PRs, IAC PRs: {remaining_iac}")
    assert remaining_iac == 0, "IAC filtering failed"

    # Test 2: GitHub Personal Approval Filtering
    print("\n2️⃣ Testing GitHub Personal Approval Filtering...")
    github_data = generator.generate_github_pr_data(
        count=20, include_personal_approvals=True
    )
    github_processor = GitHubDataProcessor(logger, config)
    github_processed = github_processor.process_pull_requests(github_data)

    personal_approvals_found = 0
    for pr in github_processed:
        original_pr = next(p for p in github_data if p["number"] == pr["ID"])
        creator_login = original_pr["user"]["login"]
        approved_by = pr.get("Approved By", [])
        if any(creator_login in str(approval) for approval in approved_by):
            personal_approvals_found += 1

    print(f"   📊 Processed {len(github_processed)} GitHub PRs")
    print(f"   ✅ Personal approvals found: {personal_approvals_found}")
    assert personal_approvals_found == 0, "Personal approval filtering failed"

    # Test 3: Data Structure Consistency
    print("\n3️⃣ Testing Data Structure Consistency...")
    expected_fields = {"ID", "Repository", "Title", "Created By", "Platform"}

    for pr in processed[:3]:  # Check first 3 PRs
        missing_fields = expected_fields - set(pr.keys())
        assert not missing_fields, f"Missing fields: {missing_fields}"

    print(f"   ✅ All PRs have required fields: {expected_fields}")

    print("\n🎉 All filtering tests passed!")
    return True


if __name__ == "__main__":
    # Run tests manually if script is executed directly
    run_filtering_tests()
