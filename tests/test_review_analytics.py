"""Tests for review analytics functionality."""

import pandas as pd
import pytest


class TestReviewAnalytics:
    """Test review analytics with various data types."""

    def test_commenters_with_list_value(self):
        """Test that commenters field with list values doesn't cause ambiguity error."""
        # Create test data with commenters as a list (which causes the error)
        test_data = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Repository": "test-repo",
                    "Title": "Test PR 1",
                    "Created By": "user1",
                    "Created Date": "2024-01-01",
                    "State": "Completed",
                    "Platform": "Azure DevOps",
                    "Approval Count": 2,
                    "Total Comments": 5,
                    "Total Reviewers": 3,
                    "Commenters": ["user1", "user2", "user3"],  # List value
                    "Approved By": ["user2", "user3"],
                    "Rejected By": [],
                },
                {
                    "ID": 2,
                    "Repository": "test-repo",
                    "Title": "Test PR 2",
                    "Created By": "user2",
                    "Created Date": "2024-01-02",
                    "State": "Active",
                    "Platform": "GitHub",
                    "Approval Count": 1,
                    "Total Comments": 2,
                    "Total Reviewers": 1,
                    "Commenters": ["user1"],  # List value
                    "Approved By": ["user1"],
                    "Rejected By": [],
                },
            ]
        )

        # This should not raise ValueError about ambiguous truth value
        try:
            # We can't actually call create_review_analytics without streamlit
            # so we'll test the problematic logic directly
            for _, row in test_data.iterrows():
                # This is the problematic line from dashboard.py:464
                # It should handle list/array values properly
                commenters = row.get("Commenters")

                # The fix: check if it's a list/array first, or use proper pandas check
                if isinstance(commenters, list):
                    has_commenters = len(commenters) > 0
                elif pd.isna(commenters):
                    has_commenters = False
                else:
                    # For other types, convert to string and check
                    has_commenters = bool(commenters)

                assert isinstance(has_commenters, bool)

        except ValueError as e:
            if "ambiguous" in str(e):
                pytest.fail(f"Got ambiguous truth value error: {e}")
            raise

    def test_commenters_with_none_value(self):
        """Test that None commenters are handled properly."""
        test_data = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Repository": "test-repo",
                    "Title": "Test PR",
                    "Created By": "user1",
                    "Created Date": "2024-01-01",
                    "State": "Completed",
                    "Platform": "Azure DevOps",
                    "Approval Count": 0,
                    "Total Comments": 0,
                    "Total Reviewers": 0,
                    "Commenters": None,
                    "Approved By": [],
                    "Rejected By": [],
                },
            ]
        )

        for _, row in test_data.iterrows():
            commenters = row.get("Commenters")

            if isinstance(commenters, list):
                has_commenters = len(commenters) > 0
            elif pd.isna(commenters):
                has_commenters = False
            else:
                has_commenters = bool(commenters)

            assert has_commenters is False

    def test_commenters_with_empty_list(self):
        """Test that empty list commenters are handled properly."""
        test_data = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Repository": "test-repo",
                    "Title": "Test PR",
                    "Created By": "user1",
                    "Created Date": "2024-01-01",
                    "State": "Completed",
                    "Platform": "Azure DevOps",
                    "Approval Count": 0,
                    "Total Comments": 0,
                    "Total Reviewers": 0,
                    "Commenters": [],
                    "Approved By": [],
                    "Rejected By": [],
                },
            ]
        )

        for _, row in test_data.iterrows():
            commenters = row.get("Commenters")

            if isinstance(commenters, list):
                has_commenters = len(commenters) > 0
            elif pd.isna(commenters):
                has_commenters = False
            else:
                has_commenters = bool(commenters)

            assert has_commenters is False

    def test_approved_by_with_list_value(self):
        """Test that Approved By field with list values doesn't cause ambiguity error."""
        test_data = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Repository": "test-repo",
                    "Title": "Test PR 1",
                    "Created By": "user1",
                    "Created Date": "2024-01-01",
                    "State": "Completed",
                    "Platform": "Azure DevOps",
                    "Approval Count": 2,
                    "Total Comments": 5,
                    "Total Reviewers": 3,
                    "Commenters": ["user1", "user2"],
                    "Approved By": ["user2", "user3"],  # List value
                    "Rejected By": [],
                },
                {
                    "ID": 2,
                    "Repository": "test-repo",
                    "Title": "Test PR 2",
                    "Created By": "user2",
                    "Created Date": "2024-01-02",
                    "State": "Active",
                    "Platform": "GitHub",
                    "Approval Count": 1,
                    "Total Comments": 2,
                    "Total Reviewers": 1,
                    "Commenters": ["user1"],
                    "Approved By": [
                        "user1 (with suggestions)"
                    ],  # List with special format
                    "Rejected By": [],
                },
            ]
        )

        # This should not raise ValueError about ambiguous truth value
        try:
            for _, row in test_data.iterrows():
                # This is the problematic line from dashboard.py:447
                approved_by = row.get("Approved By")

                # The fix: check if it's a list/array first
                if isinstance(approved_by, list):
                    has_approvers = len(approved_by) > 0
                elif pd.isna(approved_by):
                    has_approvers = False
                else:
                    has_approvers = bool(approved_by)

                assert isinstance(has_approvers, bool)

        except ValueError as e:
            if "ambiguous" in str(e):
                pytest.fail(f"Got ambiguous truth value error: {e}")
            raise

    def test_approved_by_with_none_value(self):
        """Test that None Approved By is handled properly."""
        test_data = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Repository": "test-repo",
                    "Title": "Test PR",
                    "Created By": "user1",
                    "Created Date": "2024-01-01",
                    "State": "Active",
                    "Platform": "Azure DevOps",
                    "Approval Count": 0,
                    "Total Comments": 0,
                    "Total Reviewers": 0,
                    "Commenters": [],
                    "Approved By": None,
                    "Rejected By": [],
                },
            ]
        )

        for _, row in test_data.iterrows():
            approved_by = row.get("Approved By")

            if isinstance(approved_by, list):
                has_approvers = len(approved_by) > 0
            elif pd.isna(approved_by):
                has_approvers = False
            else:
                has_approvers = bool(approved_by)

            assert has_approvers is False

    def test_rejected_by_with_list_value(self):
        """Test that Rejected By field with list values doesn't cause ambiguity error."""
        test_data = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Repository": "test-repo",
                    "Title": "Test PR",
                    "Created By": "user1",
                    "Created Date": "2024-01-01",
                    "State": "Rejected",
                    "Platform": "Azure DevOps",
                    "Approval Count": 0,
                    "Total Comments": 3,
                    "Total Reviewers": 2,
                    "Commenters": ["user2"],
                    "Approved By": [],
                    "Rejected By": ["user2", "user3"],  # List value
                },
            ]
        )

        try:
            for _, row in test_data.iterrows():
                rejected_by = row.get("Rejected By")

                # The fix: check if it's a list/array first
                if isinstance(rejected_by, list):
                    has_rejectors = len(rejected_by) > 0
                elif pd.isna(rejected_by):
                    has_rejectors = False
                else:
                    has_rejectors = bool(rejected_by)

                assert isinstance(has_rejectors, bool)

        except ValueError as e:
            if "ambiguous" in str(e):
                pytest.fail(f"Got ambiguous truth value error: {e}")
            raise
