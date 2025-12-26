"""
Integration tests for dashboard data loading and processing.
"""

import os

import pandas as pd
import pytest

from pr_analytics.dashboard.dashboard import load_mock_data, preprocess_dataframe


class TestDashboardIntegration:
    """Test dashboard data loading and processing with mock data."""

    def test_load_mock_data_in_mock_mode(self):
        """Test loading data in mock mode returns valid dataframe."""
        os.environ["MOCK_MODE"] = "true"

        try:
            df = load_mock_data()

            assert not df.empty, "Loaded dataframe should not be empty"
            assert "ID" in df.columns, "Dataframe must have 'ID' column"
            assert len(df) > 0, "Should have at least one row"
        finally:
            os.environ.pop("MOCK_MODE", None)

    def test_preprocess_dataframe_adds_time_columns(self):
        """Test that preprocessing adds required time-based columns."""
        # Create minimal test data
        test_data = {
            "ID": [1, 2, 3],
            "Created Date": [
                "2024-01-01 10:00:00",
                "2024-01-02 14:30:00",
                "2024-01-03 09:15:00",
            ],
            "Total Reviewers": [2, 3, 1],
        }
        df = pd.DataFrame(test_data)

        processed_df = preprocess_dataframe(df)

        # Check that time columns were added
        assert "Year" in processed_df.columns
        assert "Month" in processed_df.columns
        assert "Day" in processed_df.columns
        assert "Weekday" in processed_df.columns
        assert "Hour" in processed_df.columns
        assert "Year-Month" in processed_df.columns

        # Verify values
        assert processed_df["Year"].iloc[0] == 2024
        assert processed_df["Month"].iloc[0] == 1
        assert processed_df["Hour"].iloc[0] == 10

    def test_repository_overview_aggregation_with_mock_data(self):
        """Test that repository overview aggregation works with mock data."""
        os.environ["MOCK_MODE"] = "true"

        try:
            df = load_mock_data()

            # Perform the exact aggregation from create_repository_overview
            repo_metrics = (
                df.groupby("Repository")
                .agg(
                    {
                        "ID": "count",
                        "Approval Count": "mean",
                        "Total Comments": "mean",
                        "Total Reviewers": "mean",
                    }
                )
                .round(2)
            )

            assert len(repo_metrics) > 0, "Should have repository metrics"
            assert repo_metrics["ID"].sum() == len(
                df
            ), "PR count should match total rows"
        except KeyError as e:
            pytest.fail(f"Repository aggregation failed: {e}")
        finally:
            os.environ.pop("MOCK_MODE", None)

    def test_mock_data_has_all_dashboard_required_columns(self):
        """Test that mock data includes all columns needed by dashboard."""
        os.environ["MOCK_MODE"] = "true"

        try:
            df = load_mock_data()

            # Columns used in various dashboard visualizations
            critical_columns = [
                "ID",  # Repository overview
                "Repository",  # Grouping
                "Created Date",  # Time series
                "Platform",  # Platform filter
                "Approval Count",  # Metrics
                "Total Comments",  # Metrics
                "Total Reviewers",  # Metrics
                "Created By",  # Contributors
                "Status",  # Filtering
            ]

            missing_columns = [col for col in critical_columns if col not in df.columns]
            assert not missing_columns, f"Missing critical columns: {missing_columns}"
        finally:
            os.environ.pop("MOCK_MODE", None)
