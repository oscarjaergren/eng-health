"""
PR Data Visualizer Dashboard

A Streamlit web application for visualizing Pull Request data from Azure DevOps and GitHub.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from pr_analytics.core.mock_mode import get_mock_provider, is_mock_mode
from pr_analytics.core.safe_data_parser import (
    safe_count_items,
    safe_parse_dict,
    safe_parse_list,
)
from pr_analytics.dashboard.api_client import APIClient

# Add pr_analytics directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))


def load_data_from_api(
    api_client: APIClient, force_refresh: bool = False
) -> pd.DataFrame:
    """Load and preprocess PR data from API."""
    try:
        # Fetch data from API
        df = api_client.get_pull_requests(force_refresh=force_refresh)

        if df.empty:
            return df

        return preprocess_dataframe(df)
    except Exception as e:
        st.error(f"Error loading data from API: {e}")
        return pd.DataFrame()


def load_mock_data() -> pd.DataFrame:
    """Load and preprocess mock PR data."""
    try:
        mock_provider = get_mock_provider()
        # Clear cache to ensure we get fresh data with latest schema
        mock_provider.clear_cache()
        df = mock_provider.get_mock_data()
        return preprocess_dataframe(df)
    except Exception as e:
        st.error(f"Error loading mock data: {e}")
        return pd.DataFrame()


def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Preprocess dataframe with common transformations."""
    if df.empty:
        return df

    # Convert Created Date to datetime
    df["Created Date"] = pd.to_datetime(df["Created Date"])

    # Extract datetime components for analysis
    df["Year"] = df["Created Date"].dt.year
    df["Month"] = df["Created Date"].dt.month
    df["Day"] = df["Created Date"].dt.day
    df["Weekday"] = df["Created Date"].dt.day_name()
    df["Hour"] = df["Created Date"].dt.hour

    # Create year-month column for time series
    df["Year-Month"] = df["Created Date"].dt.to_period("M")

    # Clean up reviewer data
    if "Assigned To" in df.columns:
        df["Reviewer Count"] = df["Assigned To"].apply(lambda x: safe_count_items(x))
    elif "Total Reviewers" in df.columns:
        df["Reviewer Count"] = df["Total Reviewers"]
    else:
        df["Reviewer Count"] = 0

    return df


def create_repository_overview(df: pd.DataFrame):
    """Create repository overview visualizations."""
    st.caption(
        "💡 Compare repositories by PR activity, approvals, and comments to identify the most and least active repos"
    )

    # Calculate repository metrics for stats
    repo_metrics_for_stats = (
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
    repo_metrics_for_stats.columns = [
        "PR Count",
        "Avg Approvals",
        "Avg Comments",
        "Avg Reviewers",
    ]

    # Repository stats at top
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Repositories", len(df["Repository"].unique()))

    with col2:
        st.metric("Total PRs", len(df))

    with col3:
        avg_prs = len(df) / len(df["Repository"].unique())
        st.metric(
            "Avg PRs per Repo",
            f"{avg_prs:.1f}",
            help="Average number of PRs per repository. Shows how active repos are on average.",
        )

    with col4:
        most_active = repo_metrics_for_stats["PR Count"].idxmax()
        most_active_count = int(repo_metrics_for_stats.loc[most_active, "PR Count"])
        st.metric("Most Active Repo", most_active, f"{most_active_count} PRs")

    st.markdown("---")

    # Interactive controls
    col1, col2 = st.columns(2)
    with col1:
        view_type = st.selectbox(
            "📈 View Type",
            ["Top Repos", "Bottom Repos"],
            help="Show most active repos (highest PR count) or least active repos (lowest PR count)",
        )

    with col2:
        num_repos = st.slider(
            "📊 Number of Repos",
            min_value=5,
            max_value=50,
            value=20,
            step=5,
            help="How many repositories to display",
        )

    # Calculate repository metrics
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
    repo_metrics.columns = [
        "PR Count",
        "Avg Approvals",
        "Avg Comments",
        "Avg Reviewers",
    ]

    # Sort by PR Count
    sort_column = "PR Count"

    # Apply view type filtering
    if view_type == "Top Repos":
        repo_data = repo_metrics.sort_values(sort_column, ascending=False).head(
            num_repos
        )
        title_prefix = f"🏆 Top {num_repos}"
    else:  # Bottom Repos
        repo_data = repo_metrics.sort_values(sort_column, ascending=True).head(
            num_repos
        )
        title_prefix = f"📉 Bottom {num_repos}"

    # Create the chart
    chart_values = repo_data[sort_column]
    fig = px.bar(
        x=chart_values.values,
        y=chart_values.index,
        orientation="h",
        title=f"{title_prefix} Repositories by PR Count",
        labels={"x": "PR Count", "y": "Repository"},
        color=chart_values.values,
        color_continuous_scale=("viridis" if view_type == "Top Repos" else "reds"),
    )
    fig.update_layout(height=max(400, num_repos * 20), showlegend=False)
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, width="stretch")


def create_temporal_analysis(df: pd.DataFrame):
    """Create temporal analysis visualizations."""
    st.caption(
        "💡 Discover when PRs are created - time trends, busiest days of the week, and peak hours"
    )

    # Stats at top
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total PRs", len(df))

    with col2:
        date_range_days = (df["Created Date"].max() - df["Created Date"].min()).days
        st.metric(
            "Date Range",
            f"{date_range_days} days",
            help="Time period covered by the data",
        )

    with col3:
        busiest_day = df["Weekday"].value_counts().idxmax()
        busiest_count = df["Weekday"].value_counts().max()
        st.metric("Busiest Day", busiest_day, f"{busiest_count} PRs")

    with col4:
        busiest_hour = df["Hour"].value_counts().idxmax()
        busiest_hour_count = df["Hour"].value_counts().max()
        st.metric("Peak Hour", f"{busiest_hour}:00", f"{busiest_hour_count} PRs")

    st.markdown("---")

    # Time series of PR creation
    monthly_counts = df.groupby("Year-Month").size()

    fig = px.line(
        x=monthly_counts.index.astype(str),
        y=monthly_counts.values,
        title="PR Creation Over Time",
        labels={"x": "Year-Month", "y": "Number of PRs"},
        markers=True,
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        # Day of week analysis
        weekday_counts = df["Weekday"].value_counts()
        weekday_order = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        weekday_counts = weekday_counts.reindex(weekday_order)

        fig = px.bar(
            x=weekday_counts.index,
            y=weekday_counts.values,
            title="PRs by Day of Week",
            labels={"x": "Day of Week", "y": "Number of PRs"},
            color=weekday_counts.values,
            color_continuous_scale="blues",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Hour of day analysis
        hourly_counts = df["Hour"].value_counts().sort_index()

        fig = px.bar(
            x=hourly_counts.index,
            y=hourly_counts.values,
            title="PRs by Hour of Day",
            labels={"x": "Hour", "y": "Number of PRs"},
            color=hourly_counts.values,
            color_continuous_scale="oranges",
        )
        st.plotly_chart(fig, use_container_width=True)


def create_contributor_analysis(df: pd.DataFrame):
    """Create contributor analysis visualizations."""
    st.caption(
        "💡 See who creates the most PRs and how reviewers are distributed across pull requests"
    )

    # Stats at top
    col1, col2, col3 = st.columns(3)

    with col1:
        total_contributors = len(df["Created By"].unique())
        st.metric(
            "Total Contributors",
            total_contributors,
            help="Number of unique people who have created PRs",
        )

    with col2:
        avg_prs_per_contributor = len(df) / total_contributors
        st.metric(
            "Avg PRs per Contributor",
            f"{avg_prs_per_contributor:.1f}",
            help="Average number of PRs each person creates (total PRs / total people). Skewed by very active contributors.",
        )

    with col3:
        median_prs = df["Created By"].value_counts().median()
        st.metric(
            "Median PRs per Contributor",
            f"{median_prs:.1f}",
            help="Typical number of PRs per person (middle value). Better represents the 'normal' contributor since it's not affected by outliers.",
        )

    st.markdown("---")

    # Top contributors
    contributor_counts = df["Created By"].value_counts().head(15)

    fig = px.bar(
        x=contributor_counts.values,
        y=contributor_counts.index,
        orientation="h",
        title="Top 15 PR Contributors",
        labels={"x": "Number of PRs", "y": "Contributor"},
        color=contributor_counts.values,
        color_continuous_scale="plasma",
    )
    fig.update_layout(height=500, showlegend=False)
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, use_container_width=True)


def create_repository_heatmap(df: pd.DataFrame):
    """Create a repository activity heatmap."""
    st.caption(
        "💡 Find the most worked on repositories over time - visualize activity patterns across repos and months"
    )

    # Create repository-month matrix
    repo_month_data = (
        df.groupby(["Repository", "Year-Month"]).size().unstack(fill_value=0)
    )

    # Select top repositories for better visualization
    top_repos = df["Repository"].value_counts().head(20).index
    heatmap_data = repo_month_data.loc[top_repos]

    fig = px.imshow(
        heatmap_data.values,
        x=heatmap_data.columns.astype(str),
        y=heatmap_data.index,
        title="Repository Activity Heatmap (Top 20 Repos)",
        labels={"x": "Year-Month", "y": "Repository", "color": "PR Count"},
        color_continuous_scale="viridis",
    )
    fig.update_layout(height=600)
    st.plotly_chart(fig, use_container_width=True)


def create_interactive_filters(df: pd.DataFrame):
    """Show filtered data summary and detailed view."""
    st.caption(
        "💡 Explore the raw PR data with customizable column views - useful for detailed investigation"
    )
    st.info("Use the filters in the sidebar to refine the data shown across all tabs.")

    # Display filtered results summary
    st.subheader(f"Current Dataset ({len(df)} PRs)")

    if len(df) > 0:
        # Quick stats for the filtered data
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total PRs", len(df))

        with col2:
            st.metric("Repositories", len(df["Repository"].unique()))

        with col3:
            st.metric("Contributors", len(df["Created By"].unique()))

        with col4:
            avg_reviewers = df["Reviewer Count"].mean()
            st.metric(
                "Avg Reviewers",
                f"{avg_reviewers:.1f}",
                help="Average number of reviewers assigned per PR in the filtered dataset.",
            )

        # Show detailed data table
        st.subheader("📋 Detailed PR Data")

        # Select columns to display
        available_columns = df.columns.tolist()
        default_columns = [
            "Repository",
            "Title",
            "Created By",
            "Created Date",
            "Status",
            "Reviewer Count",
        ]
        display_columns = [col for col in default_columns if col in available_columns]

        selected_columns = st.multiselect(
            "Select columns to display:",
            available_columns,
            default=display_columns,
            key="column_selector",
        )

        if selected_columns:
            st.dataframe(df[selected_columns], use_container_width=True, height=400)
        else:
            st.warning("Please select at least one column to display.")
    else:
        st.warning(
            "No data matches the current filters. Try adjusting the filters in the sidebar."
        )


def create_review_analytics(df: pd.DataFrame):
    """Create comprehensive review analytics and engagement metrics."""
    st.caption(
        "💡 See who reviews the most, who leaves comments, and who isn't participating in code reviews"
    )

    # Check if we have the detailed review data
    if "Approved By" not in df.columns:
        st.warning(
            """
        ⚠️ **Enhanced Review Data Not Available**

        The current data doesn't include detailed review information (comments, approvals, etc.).
        To get these insights, please re-run the main extraction script:

        ```bash
        python src/main.py
        ```

        **What you'll get with the enhanced data:**
        - Who approves the most PRs
        - Who leaves the most comments
        - Review discussion patterns
        - Approval/rejection analytics
        - Comment thread analysis
        """
        )

        # Show basic analytics with current data
        st.subheader("📊 Basic Review Analytics (Current Data)")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total PRs", len(df))
        with col2:
            st.metric("Total Contributors", len(df["Created By"].unique()))
        with col3:
            avg_reviewers = (
                df["Reviewer Count"].mean() if "Reviewer Count" in df.columns else 0
            )
            st.metric(
                "Avg Reviewers/PR",
                f"{avg_reviewers:.1f}",
                help="Average number of reviewers assigned to each pull request.",
            )

        return

    # Enhanced analytics when detailed data is available
    st.caption(
        "💡 See who reviews the most, who leaves comments, and who isn't participating in code reviews"
    )

    # Extract reviewer data
    approval_counts = {}
    comment_counts = {}
    rejection_counts = {}

    for _, row in df.iterrows():
        # Process approvers
        approved_by_value = row.get("Approved By")
        # Handle list/array values properly to avoid ambiguity error
        if isinstance(approved_by_value, list):
            has_approvers = len(approved_by_value) > 0
        elif pd.isna(approved_by_value):
            has_approvers = False
        else:
            has_approvers = bool(approved_by_value)

        if has_approvers:
            approvers = safe_parse_list(approved_by_value)
            for approver in approvers:
                clean_approver = approver.split(" (")[
                    0
                ]  # Remove "(with suggestions)" part
                approval_counts[clean_approver] = (
                    approval_counts.get(clean_approver, 0) + 1
                )

        # Process commenters - use the new Comment Counts data
        comment_counts_value = row.get("Comment Counts")
        # Handle list/array values properly to avoid ambiguity error
        if isinstance(comment_counts_value, list):
            has_comment_counts = len(comment_counts_value) > 0
        elif pd.isna(comment_counts_value):
            has_comment_counts = False
        else:
            has_comment_counts = bool(comment_counts_value)

        if has_comment_counts:
            pr_comment_counts = safe_parse_dict(comment_counts_value)
            if isinstance(pr_comment_counts, dict):
                for commenter, count in pr_comment_counts.items():
                    comment_counts[commenter] = comment_counts.get(commenter, 0) + count
        else:
            # Fallback to old method if Comment Counts not available
            commenters_value = row.get("Commenters")
            # Handle list/array values properly to avoid ambiguity error
            if isinstance(commenters_value, list):
                has_commenters = len(commenters_value) > 0
            elif pd.isna(commenters_value):
                has_commenters = False
            else:
                has_commenters = bool(commenters_value)

            if has_commenters:
                commenters = safe_parse_list(commenters_value)
                for commenter in commenters:
                    comment_counts[commenter] = comment_counts.get(commenter, 0) + 1

        # Process rejections
        rejected_by_value = row.get("Rejected By")
        # Handle list/array values properly to avoid ambiguity error
        if isinstance(rejected_by_value, list):
            has_rejectors = len(rejected_by_value) > 0
        elif pd.isna(rejected_by_value):
            has_rejectors = False
        else:
            has_rejectors = bool(rejected_by_value)

        if has_rejectors:
            rejectors = safe_parse_list(rejected_by_value)
            for rejector in rejectors:
                rejection_counts[rejector] = rejection_counts.get(rejector, 0) + 1

    # Top Metrics Row - Per Person Statistics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if approval_counts:
            approval_values = list(approval_counts.values())
            median_approvals = pd.Series(approval_values).median()
            st.metric(
                "Median Approvals per Person",
                f"{median_approvals:.1f}",
                help="Typical number of approvals a reviewer gives. The middle value - half of reviewers approve more, half approve less.",
            )
        else:
            st.metric("Median Approvals per Person", "0")

    with col2:
        if approval_counts:
            approval_values = list(approval_counts.values())
            avg_approvals = pd.Series(approval_values).mean()
            st.metric(
                "Average Approvals per Person",
                f"{avg_approvals:.1f}",
                help="Mean number of approvals per reviewer. If much higher than median, some reviewers are approving way more than others.",
            )
        else:
            st.metric("Average Approvals per Person", "0")

    with col3:
        if comment_counts:
            comment_values = list(comment_counts.values())
            median_comments = pd.Series(comment_values).median()
            st.metric(
                "Median Comments per Person",
                f"{median_comments:.1f}",
                help="Typical number of comments a person leaves on PRs. The middle value - half comment more, half comment less.",
            )
        else:
            st.metric("Median Comments per Person", "0")

    with col4:
        if comment_counts:
            comment_values = list(comment_counts.values())
            avg_comments = pd.Series(comment_values).mean()
            st.metric(
                "Average Comments per Person",
                f"{avg_comments:.1f}",
                help="Mean number of comments per person. If much higher than median, a few people are leaving most of the comments.",
            )
        else:
            st.metric("Average Comments per Person", "0")

    # Second row - PR Coverage Metrics
    st.markdown("#### 📊 Review Coverage per PR")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if "Reviewer Count" in df.columns:
            median_reviewers_per_pr = df["Reviewer Count"].median()
            st.metric(
                "Median Reviewers per PR",
                f"{median_reviewers_per_pr:.1f}",
                help="Typical number of reviewers assigned to each PR. The middle value - shows normal review coverage.",
            )
        else:
            st.metric("Median Reviewers per PR", "0")

    with col2:
        if "Reviewer Count" in df.columns:
            avg_reviewers_per_pr = df["Reviewer Count"].mean()
            st.metric(
                "Average Reviewers per PR",
                f"{avg_reviewers_per_pr:.1f}",
                help="Mean number of reviewers per PR. If higher than median, some PRs have many more reviewers than typical.",
            )
        else:
            st.metric("Average Reviewers per PR", "0")

    with col3:
        if "Reviewer Count" in df.columns:
            prs_with_no_reviewers = (df["Reviewer Count"] == 0).sum()
            st.metric(
                "PRs with No Reviewers",
                prs_with_no_reviewers,
                help="Number of PRs that have no assigned reviewers - potential blind spots in code review.",
            )
        else:
            st.metric("PRs with No Reviewers", "0")

    with col4:
        if "Reviewer Count" in df.columns:
            prs_with_multiple = (df["Reviewer Count"] >= 2).sum()
            pct_multiple = (prs_with_multiple / len(df) * 100) if len(df) > 0 else 0
            st.metric(
                "PRs with 2+ Reviewers",
                f"{pct_multiple:.0f}%",
                help="Percentage of PRs with at least 2 reviewers - indicates good review coverage.",
            )
        else:
            st.metric("PRs with 2+ Reviewers", "0%")

    st.markdown("---")

    # Interactive Analysis Section - Side by Side Graphs
    st.subheader("🔍 Interactive Reviewer Analysis")

    # Left column: Approvers and Commenters
    col_left, col_right = st.columns(2)

    with col_left:
        # Approvers Chart
        if approval_counts:
            sorted_approvals = sorted(
                approval_counts.items(), key=lambda x: x[1], reverse=True
            )
            people, counts = zip(*sorted_approvals)

            fig = px.bar(
                x=list(counts),
                y=[person.split("@")[0] for person in people],
                orientation="h",
                title="👍 Approvers by Approvals",
                labels={"x": "Number of Approvals", "y": "Person"},
                color=list(counts),
                color_continuous_scale="greens",
            )
            fig.update_layout(
                height=max(400, len(sorted_approvals) * 25),
                showlegend=False,
                title_font_size=16,
            )
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No approvers data available")

        # Commenters Chart
        if comment_counts:
            sorted_comments = sorted(
                comment_counts.items(), key=lambda x: x[1], reverse=True
            )
            people, counts = zip(*sorted_comments)

            fig = px.bar(
                x=list(counts),
                y=[person.split("@")[0] for person in people],
                orientation="h",
                title="💬 Commenters by Comments",
                labels={"x": "Number of Comments", "y": "Person"},
                color=list(counts),
                color_continuous_scale="blues",
            )
            fig.update_layout(
                height=max(400, len(sorted_comments) * 25),
                showlegend=False,
                title_font_size=16,
            )
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No commenters data available")

    with col_right:
        # Rejectors Chart
        if rejection_counts:
            sorted_rejections = sorted(
                rejection_counts.items(), key=lambda x: x[1], reverse=True
            )
            people, counts = zip(*sorted_rejections)

            fig = px.bar(
                x=list(counts),
                y=[person.split("@")[0] for person in people],
                orientation="h",
                title="� Rejectors by Rejections",
                labels={"x": "Number of Rejections", "y": "Person"},
                color=list(counts),
                color_continuous_scale="reds",
            )
            fig.update_layout(
                height=max(400, len(sorted_rejections) * 25),
                showlegend=False,
                title_font_size=16,
            )
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No rejectors data available")


def main():
    """Main dashboard function."""
    st.set_page_config(
        page_title="PR Data Visualizer",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("📊 Multi-Platform PR Data Dashboard")
    st.markdown("---")

    # Data source selection
    data_mode = os.getenv("DATA_MODE", "api").lower()  # 'api' or 'excel'

    # Initialize API client
    api_client = APIClient()

    # Sidebar: Data source and refresh controls
    with st.sidebar:
        st.header("🔧 Data Source")

        # Check API availability
        api_available = api_client.is_available()

        if api_available:
            st.success("✅ API Connected")

            # Show cache stats
            cache_stats = api_client.get_cache_stats()
            if cache_stats:
                with st.expander("📊 Cache Statistics"):
                    st.metric("Cache Entries", cache_stats.get("entries", 0))
                    st.metric("Hit Rate", f"{cache_stats.get('hit_rate', 0)}%")
                    st.metric(
                        "Hits / Misses",
                        f"{cache_stats.get('hits', 0)} / {cache_stats.get('misses', 0)}",
                    )

            # Refresh button
            if st.button("🔄 Refresh Data", help="Force refresh data from APIs"):
                with st.spinner("Fetching fresh data..."):
                    api_client.invalidate_cache()
                    st.rerun()

        else:
            st.warning("⚠️ API Unavailable - Using Mock Mode fallback")
            data_mode = "mock"

    # Load data based on mode
    if api_available and data_mode == "api":
        st.info("🚀 Real-time data mode - Connected to API")
        force_refresh = st.sidebar.checkbox("Force API Refresh", value=False)
        df = load_data_from_api(api_client, force_refresh=force_refresh)
    elif is_mock_mode() or data_mode == "mock":
        df = load_mock_data()
    else:
        st.error("❌ API unavailable and mock mode not enabled")
        st.markdown(
            """
        ### How to get started:

        **Option 1: Use API Mode (Recommended)**
        1. Start the API: `python api_main.py`
        2. The dashboard will automatically connect

        **Option 2: Use Mock Mode**
        1. Set environment variable: `MOCK_MODE=true`
        2. Run the dashboard: `streamlit run dashboard_main.py --mock`

        ### Supported Platforms:
        - **Azure DevOps**: Configure AZURE_DEVOPS_ORGANIZATION, AZURE_DEVOPS_PAT
        - **GitHub**: Configure GITHUB_TOKEN, GITHUB_OWNER
        - **Both**: Configure all variables to extract from both platforms
        """
        )
        return

    if not df.empty:
        # Add global filters in sidebar
        st.sidebar.subheader(
            "📊 Filters",
            help="Default exclusions: IAC PRs and personal approvals are automatically filtered out to focus on meaningful peer code reviews.",
        )

        # Platform filter (if multiple platforms exist)
        if "Platform" in df.columns and len(df["Platform"].unique()) > 1:
            platforms = ["All"] + sorted(df["Platform"].unique().tolist())
            selected_platform = st.sidebar.selectbox(
                "Select Platform", platforms, key="main_platform_filter"
            )
            if selected_platform != "All":
                df = df[df["Platform"] == selected_platform]

        # Date range filter
        if "Created Date" in df.columns:
            df["Created Date"] = pd.to_datetime(df["Created Date"])
            min_date = df["Created Date"].min().date()
            max_data_date = df["Created Date"].max().date()
            today = datetime.today().date()
            # Allow selection up to today + 1 day to avoid edge cases
            max_allowed = max(today + timedelta(days=1), max_data_date)

            try:
                date_range = st.sidebar.date_input(
                    "Select Date Range",
                    value=(
                        min_date,
                        today,
                    ),  # Default to today instead of max_value
                    min_value=min_date,
                    max_value=max_allowed,
                    key="main_date_filter",
                )

                # Handle both single date and date range selections
                if isinstance(date_range, tuple) and len(date_range) == 2:
                    start_date, end_date = date_range
                    df = df[
                        (df["Created Date"].dt.date >= start_date)
                        & (df["Created Date"].dt.date <= end_date)
                    ]
                elif hasattr(date_range, "__len__") and len(date_range) == 1:
                    # Single date selected, treat as same start and end date
                    single_date = (
                        date_range[0] if isinstance(date_range, tuple) else date_range
                    )
                    df = df[df["Created Date"].dt.date == single_date]
                elif (
                    not isinstance(date_range, (list, tuple)) and date_range is not None
                ):
                    # Single date object
                    df = df[df["Created Date"].dt.date == date_range]

            except Exception as e:
                st.sidebar.error(f"Date filter error: {str(e)}")
                # Continue with unfiltered data

        # Repository filter
        if "Repository" in df.columns:
            repos = ["All"] + sorted(df["Repository"].unique().tolist())
            selected_repo = st.sidebar.selectbox(
                "Select Repository", repos, key="main_repo_filter"
            )
            if selected_repo != "All":
                df = df[df["Repository"] == selected_repo]

        # Contributor filter
        if "Created By" in df.columns:
            contributors = ["All"] + sorted(df["Created By"].unique().tolist())
            selected_contributor = st.sidebar.selectbox(
                "Select Contributor", contributors, key="main_contributor_filter"
            )
            if selected_contributor != "All":
                df = df[df["Created By"] == selected_contributor]

        # Show data summary (after filtering)
        total_prs = len(df)
        st.sidebar.metric("📈 Filtered PRs", total_prs)

        # Platform breakdown in sidebar
        if "Platform" in df.columns and len(df["Platform"].unique()) > 1:
            st.sidebar.subheader("🔧 Platform Breakdown")
            platform_counts = df["Platform"].value_counts()
            for platform, count in platform_counts.items():
                st.sidebar.metric(f"{platform}", count)

        if "Approved By" in df.columns:
            # Count PRs with approvals (excluding empty lists)
            approved_prs = sum(
                1
                for approvals in df["Approved By"]
                if approvals and safe_count_items(approvals) > 0
            )
            st.sidebar.metric("👍 PRs with Approvals", approved_prs)

        # Create tabs for different views
        tabs = st.tabs(
            [
                "📊 Repository Analysis",
                "📅 Temporal Analysis",
                "👥 Contributors",
                " Review Analytics",
                "🔍 Interactive Analysis",
            ]
        )

        with tabs[0]:
            create_repository_overview(df)
            st.markdown("---")
            create_repository_heatmap(df)

        with tabs[1]:
            create_temporal_analysis(df)

        with tabs[2]:
            create_contributor_analysis(df)

        with tabs[3]:
            create_review_analytics(df)

        with tabs[4]:
            create_interactive_filters(df)

    else:
        st.info("📊 No data available to display")


if __name__ == "__main__":
    main()
