"""
Tests for mock data generation and dashboard compatibility.
"""

import pandas as pd
import pytest

from pr_analytics.core.mock_mode import MockDataProvider
from pr_analytics.utils.mock_data_generator import MockDataGenerator


class TestMockDataGeneration:
    """Test mock data generation produces dashboard-compatible data."""

    def test_mock_data_has_required_columns(self):
        """Test that mock data includes all required columns for dashboard."""
        generator = MockDataGenerator(seed=42)
        data = generator.generate_dashboard_data(count=10)

        df = pd.DataFrame(data)

        # Critical columns that dashboard expects
        required_columns = [
            "ID",  # Required for repository overview aggregation
            "PR ID",
            "Repository",
            "Title",
            "Created By",
            "Created Date",
            "Status",
            "Platform",
            "Total Reviewers",
            "Approval Count",
            "Total Comments",
        ]

        for col in required_columns:
            assert col in df.columns, f"Missing required column: {col}"

    def test_mock_data_id_column_is_numeric(self):
        """Test that ID column contains numeric values."""
        generator = MockDataGenerator(seed=42)
        data = generator.generate_dashboard_data(count=10)

        df = pd.DataFrame(data)

        assert "ID" in df.columns
        assert df["ID"].dtype in [int, "int64", "int32"]
        assert df["ID"].notna().all()
        assert (df["ID"] > 0).all()

    def test_mock_provider_data_has_id(self):
        """Test that MockDataProvider returns data with ID column."""
        provider = MockDataProvider()
        provider.clear_cache()  # Ensure fresh data

        df = provider.get_mock_data()

        assert "ID" in df.columns, "MockDataProvider must include 'ID' column"
        assert len(df) > 0, "MockDataProvider should return non-empty dataframe"

    def test_repository_overview_aggregation(self):
        """Test that mock data can be aggregated for repository overview."""
        generator = MockDataGenerator(seed=42)
        data = generator.generate_dashboard_data(count=20)

        df = pd.DataFrame(data)

        # This is the exact aggregation used in create_repository_overview
        try:
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

            assert len(repo_metrics) > 0
            assert (
                "ID" in repo_metrics.columns or repo_metrics.index.name == "Repository"
            )
        except KeyError as e:
            pytest.fail(f"Aggregation failed with KeyError: {e}")

    def test_mock_data_date_format(self):
        """Test that dates are in correct format."""
        generator = MockDataGenerator(seed=42)
        data = generator.generate_dashboard_data(count=10)

        df = pd.DataFrame(data)

        # Convert to datetime (as dashboard does)
        df["Created Date"] = pd.to_datetime(df["Created Date"])

        assert df["Created Date"].notna().all()
        assert df["Created Date"].dtype == "datetime64[ns]"

    def test_mock_data_platform_values(self):
        """Test that Platform column has valid values."""
        generator = MockDataGenerator(seed=42)
        data = generator.generate_dashboard_data(count=20)

        df = pd.DataFrame(data)

        assert "Platform" in df.columns
        valid_platforms = {"Azure DevOps", "GitHub"}
        assert set(df["Platform"].unique()).issubset(valid_platforms)

    def test_mock_data_consistency(self):
        """Test that mock data is consistent across regeneration with same seed."""
        generator1 = MockDataGenerator(seed=42)
        data1 = generator1.generate_dashboard_data(count=10)

        generator2 = MockDataGenerator(seed=42)
        data2 = generator2.generate_dashboard_data(count=10)

        df1 = pd.DataFrame(data1)
        df2 = pd.DataFrame(data2)

        # Should have same structure
        assert df1.columns.tolist() == df2.columns.tolist()
        assert len(df1) == len(df2)

        # Should have same IDs
        assert df1["ID"].tolist() == df2["ID"].tolist()
