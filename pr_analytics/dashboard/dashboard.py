"""
PR Data Visualizer Dashboard

A Streamlit web application for visualizing Pull Request data from Azure DevOps and GitHub.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from pr_analytics.core.mock_mode import get_mock_provider, is_mock_mode
from pr_analytics.core.safe_data_parser import (
    safe_count_items,
    safe_parse_dict,
    safe_parse_list,
)

# Cache file for persistent PR storage
CACHE_FILE = Path(".cache/pr_data_cache.json")
CACHE_METADATA_FILE = Path(".cache/pr_cache_metadata.json")


def _load_cached_prs() -> tuple[list, str | None]:
    """Load cached PRs from disk."""
    if not CACHE_FILE.exists():
        return [], None
    
    try:
        with open(CACHE_FILE, "r") as f:
            cached_prs = json.load(f)
        
        last_fetch = None
        if CACHE_METADATA_FILE.exists():
            with open(CACHE_METADATA_FILE, "r") as f:
                metadata = json.load(f)
                last_fetch = metadata.get("last_fetch_date")
        
        return cached_prs, last_fetch
    except Exception:
        return [], None


def _save_cached_prs(prs: list, last_fetch_date: str) -> None:
    """Save PRs to disk cache."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(CACHE_FILE, "w") as f:
        json.dump(prs, f)
    
    with open(CACHE_METADATA_FILE, "w") as f:
        json.dump({"last_fetch_date": last_fetch_date}, f)


def _fetch_new_prs(since_date: str | None = None, progress_container=None) -> list:
    """Fetch new PRs since the given date (or all if None).

    NOTE: since_date is accepted for future incremental fetching but not yet
    passed to the underlying API clients.
    """
    from pr_analytics.clients.azure_devops_client import AzureDevOpsClient
    from pr_analytics.clients.github_client import GitHubClient
    from pr_analytics.core.config import Config
    from pr_analytics.processors.unified_data_processor import UnifiedDataProcessor
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import logging
    import threading

    config = Config()
    logger = logging.getLogger(__name__)
    processor = UnifiedDataProcessor(logger, config)

    all_pr_data = []
    all_repositories = []
    clients_info = []

    if "azure_devops" in config.platforms:
        client = AzureDevOpsClient(config, logger)
        repos = client.fetch_all_repositories()
        for repo in repos:
            all_repositories.append(("azure_devops", repo, client))
        clients_info.append(("azure_devops", client))

    if "github" in config.platforms:
        client = GitHubClient(config, logger)
        repos = client.fetch_all_repositories()
        for repo in repos:
            all_repositories.append(("github", repo, client))
        clients_info.append(("github", client))

    if not all_repositories:
        return []

    total_repos = len(all_repositories)
    raw_prs_by_platform = {"azure_devops": [], "github": []}
    completed_count = [0]
    lock = threading.Lock()
    
    def fetch_repo_prs(args):
        platform, repo, client = args
        repo_name = repo.get("name", "Unknown")
        repo_prs = client.fetch_pull_requests_for_repository(repo)
        for pr in repo_prs:
            pr["repository_name"] = repo_name
        return platform, repo_name, repo_prs
    
    max_workers = min(8, total_repos)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_repo_prs, args): args for args in all_repositories}
        
        for future in as_completed(futures):
            try:
                platform, repo_name, repo_prs = future.result()
                with lock:
                    raw_prs_by_platform[platform].extend(repo_prs)
                    completed_count[0] += 1
                    if progress_container:
                        progress = completed_count[0] / total_repos
                        progress_container.progress(progress, text=f"📂 Fetched {repo_name} ({completed_count[0]}/{total_repos})")
            except Exception as e:
                logger.warning(f"Failed to fetch repo: {e}")
                with lock:
                    completed_count[0] += 1

    for platform, client in clients_info:
        raw_prs = raw_prs_by_platform.get(platform, [])
        if raw_prs:
            if progress_container:
                progress_container.progress(1.0, text=f"⚙️ Processing {len(raw_prs)} PRs from {platform}...")
            processed = processor.process_pull_requests(raw_prs, platform)
            all_pr_data.extend(processed)

    return all_pr_data


def _fetch_and_cache_prs(progress_container=None) -> list:
    """Fetch PR data with incremental caching and progress display."""
    cached_prs, last_fetch_date = _load_cached_prs()
    new_prs = _fetch_new_prs(since_date=last_fetch_date, progress_container=progress_container)
    
    if progress_container:
        progress_container.progress(1.0, text="✅ Syncing complete!")
    
    if not cached_prs:
        now = datetime.now().isoformat()
        _save_cached_prs(new_prs, now)
        return new_prs
    
    existing_ids = {pr.get("ID", pr.get("id")): pr for pr in cached_prs}
    
    for pr in new_prs:
        pr_id = pr.get("ID", pr.get("id"))
        existing_ids[pr_id] = pr
    
    merged_prs = list(existing_ids.values())
    now = datetime.now().isoformat()
    _save_cached_prs(merged_prs, now)
    
    return merged_prs


def load_pr_data() -> pd.DataFrame:
    """Load PR data from cache or fetch from Azure DevOps/GitHub."""
    try:
        cached_prs, last_fetch = _load_cached_prs()
        
        if cached_prs:
            pr_data = cached_prs
        else:
            progress_bar = st.progress(0, text="🔄 Connecting to Azure DevOps/GitHub...")
            pr_data = _fetch_and_cache_prs(progress_container=progress_bar)
            progress_bar.empty()

        if not pr_data:
            return pd.DataFrame()

        return _convert_prs_to_dataframe(pr_data)
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()


def _convert_prs_to_dataframe(pr_data: list) -> pd.DataFrame:
    """Convert PR data list to DataFrame."""
    if not pr_data:
        return pd.DataFrame()
    
    first_item = pr_data[0] if pr_data else {}
    if "Repository" in first_item or "ID" in first_item:
        return pd.DataFrame(pr_data)
    
    records = []
    for pr in pr_data:
        record = {
            "ID": pr.get("id"),
            "Repository": pr.get("repository"),
            "Title": pr.get("title"),
            "Created By": pr.get("created_by"),
            "Created Date": pr.get("created_date"),
            "State": pr.get("status"),
            "Platform": pr.get("platform"),
            "Approvers": pr.get("approvers", []),
            "Total Approvals": pr.get("total_approvals", 0),
            "Total Reviewers": pr.get("total_reviewers", 0),
            "Comments": pr.get("comments", 0),
            "Assigned To": pr.get("reviewers", []),
            "Project": pr.get("project", ""),
        }
        records.append(record)
    
    return pd.DataFrame(records)


def _check_direct_mode_available() -> bool:
    """Check if direct mode is available (credentials configured)."""
    azure_configured = (
        os.getenv("AZURE_DEVOPS_ORGANIZATION") and os.getenv("AZURE_DEVOPS_PAT")
    )
    github_configured = os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_OWNER")
    return azure_configured or github_configured


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

    if df.empty:
        st.info("No data matches the current filters. Adjust the date range or other filters in the sidebar.")
        return

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
        unique_repos = len(df["Repository"].unique())
        avg_prs = len(df) / unique_repos if unique_repos > 0 else 0
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
    st.plotly_chart(fig, use_container_width=True)


def create_temporal_analysis(df: pd.DataFrame):
    """Create temporal analysis visualizations."""
    st.caption(
        "💡 Discover when PRs are created - time trends, busiest days of the week, and peak hours"
    )

    if df.empty:
        st.info("No data matches the current filters. Adjust the date range or other filters in the sidebar.")
        return

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
        weekday_value_counts = df["Weekday"].value_counts()
        busiest_day = weekday_value_counts.idxmax()
        busiest_count = weekday_value_counts.max()
        st.metric("Busiest Day", busiest_day, f"{busiest_count} PRs")

    with col4:
        hour_value_counts = df["Hour"].value_counts()
        busiest_hour = hour_value_counts.idxmax()
        busiest_hour_count = hour_value_counts.max()
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

    if df.empty:
        st.info("No data matches the current filters. Adjust the date range or other filters in the sidebar.")
        return

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
        avg_prs_per_contributor = len(df) / total_contributors if total_contributors > 0 else 0
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

    if df.empty:
        st.info("No data matches the current filters. Adjust the date range or other filters in the sidebar.")
        return

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

    if df.empty:
        st.info("No data matches the current filters. Adjust the date range or other filters in the sidebar.")
        return

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

    # Initialize session state for sync trigger
    if "trigger_sync" not in st.session_state:
        st.session_state.trigger_sync = False
    if "trigger_full_reset" not in st.session_state:
        st.session_state.trigger_full_reset = False

    # Sidebar: Data source and refresh controls
    with st.sidebar:
        st.header("🔧 Data Source")

        # Check if direct mode is possible (env vars configured)
        direct_mode_available = _check_direct_mode_available()

        if direct_mode_available:
            st.success("✅ Connected to Azure DevOps/GitHub")
            
            # Show cache info
            cached_prs, last_fetch = _load_cached_prs()
            if cached_prs:
                st.caption(f"📦 {len(cached_prs)} PRs cached")
                if last_fetch:
                    st.caption(f"Last sync: {last_fetch[:16]}")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Sync", help="Fetch new PRs only"):
                    st.session_state.trigger_sync = True
                    st.rerun()
            with col2:
                if st.button("🗑️ Full Reset", help="Clear cache and refetch all"):
                    if CACHE_FILE.exists():
                        CACHE_FILE.unlink()
                    if CACHE_METADATA_FILE.exists():
                        CACHE_METADATA_FILE.unlink()
                    st.session_state.trigger_full_reset = True
                    st.rerun()
            data_mode = "direct"
        elif is_mock_mode():
            st.info("🎭 Mock Mode Enabled")
            data_mode = "mock"
        else:
            st.warning("⚠️ Using Mock Mode (No credentials configured)")
            data_mode = "mock"

    # Load data based on mode
    df = pd.DataFrame()
    if data_mode == "direct":
        # Check if we need to sync
        if st.session_state.trigger_sync or st.session_state.trigger_full_reset:
            st.session_state.trigger_sync = False
            st.session_state.trigger_full_reset = False
            progress_bar = st.progress(0, text="🔄 Connecting to Azure DevOps/GitHub...")
            pr_data = _fetch_and_cache_prs(progress_container=progress_bar)
            progress_bar.empty()
            if pr_data:
                df = _convert_prs_to_dataframe(pr_data)
                df = preprocess_dataframe(df)
        else:
            df = load_pr_data()
            if not df.empty:
                df = preprocess_dataframe(df)
    else:
        st.success("🎭 Running in Mock Mode")
        df = load_mock_data()

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
            df["Created Date"] = pd.to_datetime(df["Created Date"], errors="coerce")
            # Normalize timezone - convert to UTC then remove timezone for consistent comparisons
            if df["Created Date"].dt.tz is not None:
                df["Created Date"] = df["Created Date"].dt.tz_convert("UTC").dt.tz_localize(None)
            
            # Drop NaT values for date range calculation
            valid_dates = df["Created Date"].dropna()
            if len(valid_dates) > 0:
                min_date = valid_dates.min().date()
                max_data_date = valid_dates.max().date()
            else:
                min_date = datetime.today().date() - timedelta(days=365)
                max_data_date = datetime.today().date()
            today = datetime.today().date()
            # Allow selection up to today + 1 day to avoid edge cases
            max_allowed = max(today + timedelta(days=1), max_data_date)

            try:
                date_range = st.sidebar.date_input(
                    "Select Date Range",
                    value=(
                        min_date,
                        max_data_date,  # Use actual max date instead of today
                    ),
                    min_value=min_date,
                    max_value=max_allowed,
                    key="main_date_filter",
                )

                # Handle both single date and date range selections
                if isinstance(date_range, tuple) and len(date_range) == 2:
                    start_date, end_date = date_range
                    # Convert dates to datetime for comparison (timezone-naive)
                    start_dt = pd.Timestamp(start_date)
                    end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    mask = (df["Created Date"] >= start_dt) & (df["Created Date"] <= end_dt)
                    # Also include rows with NaT dates to avoid losing data
                    mask = mask | df["Created Date"].isna()
                    df = df[mask]
                elif hasattr(date_range, "__len__") and len(date_range) == 1:
                    # Single date selected, treat as same start and end date
                    single_date = (
                        date_range[0] if isinstance(date_range, tuple) else date_range
                    )
                    start_dt = pd.Timestamp(single_date)
                    end_dt = pd.Timestamp(single_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    df = df[(df["Created Date"] >= start_dt) & (df["Created Date"] <= end_dt)]
                elif (
                    not isinstance(date_range, (list, tuple)) and date_range is not None
                ):
                    # Single date object
                    start_dt = pd.Timestamp(date_range)
                    end_dt = pd.Timestamp(date_range) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    df = df[(df["Created Date"] >= start_dt) & (df["Created Date"] <= end_dt)]

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

        if total_prs == 0:
            st.sidebar.warning("⚠️ No PRs match the current filters")

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
