#!/usr/bin/env python3
"""
Test script to verify IAC and personal approval filtering functionality.
"""

import sys
import logging
from src.data_processor import DataProcessor
from src.config import Config


def create_test_data():
    """Create test PR data to verify filtering."""
    return [
        {
            # Normal code PR - should be included
            'pullRequestId': 1,
            'repository_name': 'MyApp',
            'title': 'Add user authentication feature',
            'description': 'Implementing OAuth2 authentication',
            'creationDate': '2024-01-01T10:00:00Z',
            'status': 'completed',
            'createdBy': {'uniqueName': 'alice@company.com'},
            'reviewers': [
                {'uniqueName': 'bob@company.com', 'vote': 10, 'isRequired': True},
                {'uniqueName': 'charlie@company.com', 'vote': 10, 'isRequired': True}
            ],
            'threads': []
        },
        {
            # IAC PR - should be excluded
            'pullRequestId': 2,
            'repository_name': 'Infrastructure',
            'title': 'Update terraform configuration for new environment',
            'description': 'Adding new staging environment with terraform scripts',
            'creationDate': '2024-01-02T10:00:00Z',
            'status': 'completed',
            'createdBy': {'uniqueName': 'bob@company.com'},
            'reviewers': [
                {'uniqueName': 'alice@company.com', 'vote': 10, 'isRequired': True}
            ],
            'threads': []
        },
        {
            # PR with personal approval - approval should be filtered
            'pullRequestId': 3,
            'repository_name': 'MyApp',
            'title': 'Fix bug in payment processing',
            'description': 'Fixing null pointer exception',
            'creationDate': '2024-01-03T10:00:00Z',
            'status': 'completed',
            'createdBy': {'uniqueName': 'charlie@company.com'},
            'reviewers': [
                {'uniqueName': 'charlie@company.com', 'vote': 10, 'isRequired': True},  # Self-approval
                {'uniqueName': 'alice@company.com', 'vote': 10, 'isRequired': True}
            ],
            'threads': []
        },
        {
            # Docker-related PR - should be excluded as IAC
            'pullRequestId': 4,
            'repository_name': 'MyApp',
            'title': 'Update Dockerfile for better caching',
            'description': 'Optimizing Docker build process',
            'creationDate': '2024-01-04T10:00:00Z',
            'status': 'completed',
            'createdBy': {'uniqueName': 'alice@company.com'},
            'reviewers': [
                {'uniqueName': 'bob@company.com', 'vote': 10, 'isRequired': True}
            ],
            'threads': []
        }
    ]


def test_filtering():
    """Test the filtering functionality."""
    print("🧪 Testing PR filtering functionality...\n")
    
    # Setup logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Create mock config
    class MockConfig:
        exclude_iac = True
        exclude_personal_approvals = True
    
    config = MockConfig()
    
    # Create processor
    processor = DataProcessor(logger, config)
    
    # Test data
    test_data = create_test_data()
    print(f"📊 Test data contains {len(test_data)} PRs:")
    for pr in test_data:
        print(f"  - PR #{pr['pullRequestId']}: {pr['title']}")
    print()
    
    # Process data
    processed_data = processor.process_pull_requests(test_data)
    
    print(f"✅ After filtering: {len(processed_data)} PRs remain:")
    for pr in processed_data:
        approvals = pr.get('Approved By', [])
        approval_count = len(approvals) if approvals else 0
        print(f"  - PR #{pr['ID']}: {pr['Title']} (Approvals: {approval_count})")
    print()
    
    # Test results
    expected_results = 2  # PR #1 and PR #3 (but PR #3 should have filtered personal approval)
    actual_results = len(processed_data)
    
    if actual_results == expected_results:
        print("✅ Filtering test PASSED!")
        
        # Check personal approval filtering
        pr3_data = next((pr for pr in processed_data if pr['ID'] == 3), None)
        if pr3_data:
            approvals = pr3_data.get('Approved By', [])
            if len(approvals) == 1 and 'alice@company.com' in str(approvals):
                print("✅ Personal approval filtering PASSED!")
            else:
                print(f"❌ Personal approval filtering FAILED! Expected 1 approval from alice, got: {approvals}")
        else:
            print("❌ Could not find PR #3 in results")
    else:
        print(f"❌ Filtering test FAILED! Expected {expected_results} PRs, got {actual_results}")
    
    return actual_results == expected_results


if __name__ == "__main__":
    success = test_filtering()
    sys.exit(0 if success else 1)
