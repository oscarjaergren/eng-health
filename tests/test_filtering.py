#!/usr/bin/env python3
"""
Legacy Filtering Test (Deprecated)

This file has been superseded by test_pr_filtering.py which provides comprehensive
filtering tests using the mock data generator utility. This file is kept for
backward compatibility but should not be used for new tests.

For new filtering tests, use:
- azure_pr_analytics.utils.mock_data_generator for generating test data
- tests.test_pr_filtering for comprehensive filtering test suite
"""

import logging
import sys
import warnings

from azure_pr_analytics.processors.azure_devops_data_processor import (
    AzureDevOpsDataProcessor,
)
from azure_pr_analytics.utils.mock_data_generator import MockDataGenerator


def create_test_data():
    """
    Create test PR data to verify filtering.

    DEPRECATED: Use MockDataGenerator instead for more comprehensive test data.
    """
    warnings.warn(
        "create_test_data() is deprecated. Use MockDataGenerator for better test data generation.",
        DeprecationWarning,
        stacklevel=2,
    )
    return [
        {
            # Normal code PR - should be included
            "pullRequestId": 1,
            "repository_name": "MyApp",
            "title": "Add user authentication feature",
            "description": "Implementing OAuth2 authentication",
            "creationDate": "2024-01-01T10:00:00Z",
            "status": "completed",
            "createdBy": {"uniqueName": "alice@company.com"},
            "reviewers": [
                {"uniqueName": "bob@company.com", "vote": 10, "isRequired": True},
                {"uniqueName": "charlie@company.com", "vote": 10, "isRequired": True},
            ],
            "threads": [],
        },
        {
            # IAC PR - should be excluded
            "pullRequestId": 2,
            "repository_name": "Infrastructure",
            "title": "Update terraform configuration for new environment",
            "description": "Adding new staging environment with terraform scripts",
            "creationDate": "2024-01-02T10:00:00Z",
            "status": "completed",
            "createdBy": {"uniqueName": "bob@company.com"},
            "reviewers": [
                {"uniqueName": "alice@company.com", "vote": 10, "isRequired": True}
            ],
            "threads": [],
        },
        {
            # PR with personal approval - approval should be filtered
            "pullRequestId": 3,
            "repository_name": "MyApp",
            "title": "Fix bug in payment processing",
            "description": "Fixing null pointer exception",
            "creationDate": "2024-01-03T10:00:00Z",
            "status": "completed",
            "createdBy": {"uniqueName": "charlie@company.com"},
            "reviewers": [
                {
                    "uniqueName": "charlie@company.com",
                    "vote": 10,
                    "isRequired": True,
                },  # Self-approval
                {"uniqueName": "alice@company.com", "vote": 10, "isRequired": True},
            ],
            "threads": [],
        },
        {
            # Docker-related PR - should be excluded as IAC
            "pullRequestId": 4,
            "repository_name": "MyApp",
            "title": "Update Dockerfile for better caching",
            "description": "Optimizing Docker build process",
            "creationDate": "2024-01-04T10:00:00Z",
            "status": "completed",
            "createdBy": {"uniqueName": "alice@company.com"},
            "reviewers": [
                {"uniqueName": "bob@company.com", "vote": 10, "isRequired": True}
            ],
            "threads": [],
        },
    ]


def test_filtering():
    """
    Legacy filtering test function.

    DEPRECATED: Use tests.test_pr_filtering.run_filtering_tests() instead
    for comprehensive filtering tests with mock data.
    """
    warnings.warn(
        "test_filtering() is deprecated. Use tests.test_pr_filtering for comprehensive tests.",
        DeprecationWarning,
        stacklevel=2,
    )

    print("⚠️ DEPRECATED: This test function is deprecated.")
    print("📖 Please use the new comprehensive test suite:")
    print("   python -m tests.test_pr_filtering")
    print("   or")
    print("   pytest tests/test_pr_filtering.py")
    print()
    print("🧪 Running legacy test for compatibility...\n")

    # Setup logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Create mock config
    class MockConfig:
        exclude_iac = True
        exclude_personal_approvals = True
        system_accounts = ["system", "bot", "automation"]
        iac_keywords = [
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

    config = MockConfig()

    # Use the new mock data generator for better test data
    generator = MockDataGenerator(seed=42)
    test_data = generator.generate_azure_devops_pr_data(
        count=10, include_iac=True, include_personal_approvals=True
    )

    # Create processor using the new structure
    processor = AzureDevOpsDataProcessor(logger, config)
    print(f"📊 Generated test data contains {len(test_data)} PRs")

    # Process data
    processed_data = processor.process_pull_requests(test_data)

    print(f"✅ After filtering: {len(processed_data)} PRs remain")

    # Basic validation
    if len(processed_data) > 0:
        print("✅ Basic filtering test PASSED!")
        print("📖 For comprehensive testing, run: python -m tests.test_pr_filtering")
        return True
    else:
        print("❌ Basic filtering test FAILED!")
        return False


def run_new_tests():
    """Run the new comprehensive filtering tests."""
    try:
        from tests.test_pr_filtering import run_filtering_tests

        print("🚀 Running new comprehensive filtering tests...")
        return run_filtering_tests()
    except ImportError as e:
        print(f"❌ Could not import new test module: {e}")
        print("📖 Make sure you're running from the project root directory")
        return False


if __name__ == "__main__":
    print("🧪 Legacy Filtering Test")
    print("=" * 50)

    # Run legacy test with deprecation warning
    legacy_result = test_filtering()

    print("\n" + "=" * 50)
    print("🆕 Running New Comprehensive Tests")
    print("=" * 50)

    # Try to run new tests
    new_result = run_new_tests()

    print("\n" + "=" * 50)
    print("📊 Test Summary")
    print("=" * 50)
    print(f"Legacy test: {'✅ PASSED' if legacy_result else '❌ FAILED'}")
    print(f"New tests: {'✅ PASSED' if new_result else '❌ FAILED'}")

    if new_result:
        print("\n🎉 All tests completed successfully!")
        print("💡 Consider migrating to the new test structure for future development.")
    else:
        print("\n⚠️ Some tests failed. Please check the output above.")

    sys.exit(0 if (legacy_result and new_result) else 1)
