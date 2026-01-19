"""
PR Data Visualizer Dashboard

A Streamlit web application for visualizing Pull Request data from Azure DevOps and GitHub.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env file
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
    """Fetch new PRs since the given date (or all if None)."""
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

    # First, gather all repositories from all platforms
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

    # Parallel fetch with progress tracking
    total_repos = len(all_repositories)
    raw_prs_by_platform = {"azure_devops": [], "github": []}
    completed_count = [0]  # Use list for mutable counter in closure
    lock = threading.Lock()
    
    def fetch_repo_prs(args):
        platform, repo, client = args
        repo_name = repo.get("name", "Unknown")
        repo_prs = client.fetch_pull_requests_for_repository(repo)
        for pr in repo_prs:
            pr["repository_name"] = repo_name
        return platform, repo_name, repo_prs
    
    # Use ThreadPoolExecutor for parallel repo fetching (I/O bound)
    max_workers = min(8, total_repos)  # Limit to avoid overwhelming the API
    
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

    # Process all PRs by platform
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
    from datetime import datetime
    
    # Load existing cached data
    cached_prs, last_fetch_date = _load_cached_prs()
    
    # Fetch all PRs with progress
    new_prs = _fetch_new_prs(since_date=last_fetch_date, progress_container=progress_container)
    
    if progress_container:
        progress_container.progress(1.0, text="✅ Syncing complete!")
    
    if not cached_prs:
        # First time - save everything
        now = datetime.now().isoformat()
        _save_cached_prs(new_prs, now)
        return new_prs
    
    # Merge: use PR ID to dedupe, keeping newer versions
    existing_ids = {pr.get("id"): pr for pr in cached_prs}
    
    new_count = 0
    for pr in new_prs:
        pr_id = pr.get("id")
        if pr_id not in existing_ids:
            new_count += 1
        existing_ids[pr_id] = pr  # Update with latest data
    
    merged_prs = list(existing_ids.values())
    
    # Save updated cache
    now = datetime.now().isoformat()
    _save_cached_prs(merged_prs, now)
    
    return merged_prs


def load_pr_data() -> pd.DataFrame:
    """Load PR data from cache or fetch from Azure DevOps/GitHub."""
    try:
        # Check if we have cached data
        cached_prs, last_fetch = _load_cached_prs()
        
        if cached_prs:
            # Use cached data (fast path)
            pr_data = cached_prs
        else:
            # No cache - need to fetch with progress
            progress_bar = st.progress(0, text="🔄 Connecting to Azure DevOps/GitHub...")
            pr_data = _fetch_and_cache_prs(progress_container=progress_bar)
            progress_bar.empty()

        if not pr_data:
            return pd.DataFrame()

        # Use the unified converter that handles both formats
        return _convert_prs_to_dataframe(pr_data)
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()


def _convert_prs_to_dataframe(pr_data: list) -> pd.DataFrame:
    """Convert PR data list to DataFrame."""
    if not pr_data:
        return pd.DataFrame()
    
    # Check if data is already in dashboard format (uppercase keys)
    first_item = pr_data[0] if pr_data else {}
    if "Repository" in first_item or "ID" in first_item:
        # Data is already in dashboard format, just convert to DataFrame
        return pd.DataFrame(pr_data)
    
    # Convert from API format (lowercase keys) to dashboard format
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


# Add pr_analytics directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))


def load_mock_data() -> pd.DataFrame:
    """Load and preprocess mock PR data."""
    try:
        st.info("🎭 Running in Mock Mode - Using generated test data")
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
    st.header("📊 Repository Overview")

    if df.empty or "Repository" not in df.columns:
        st.info("📭 No repository data available to display.")
        return

    # Interactive controls
    col1, col2, col3 = st.columns(3)
    with col1:
        view_type = st.selectbox(
            "📈 View Type",
            ["Top Performers", "Bottom Performers", "Full Range"],
            help="Choose whether to show most active, least active, or all repositories",
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

    with col3:
        sort_by = st.selectbox(
            "📋 Sort By",
            ["PR Count", "Avg Approvals", "Avg Comments"],
            help="Metric to sort repositories by",
        )

    # Calculate repository metrics - use column names that exist in data
    approval_col = "Total Approvals" if "Total Approvals" in df.columns else "Approval Count"
    comments_col = "Comments" if "Comments" in df.columns else "Total Comments"
    
    agg_dict = {"ID": "count", "Total Reviewers": "mean"}
    if approval_col in df.columns:
        agg_dict[approval_col] = "mean"
    if comments_col in df.columns:
        agg_dict[comments_col] = "mean"
    
    repo_metrics = (
        df.groupby("Repository")
        .agg(agg_dict)
        .round(2)
    )
    
    # Rename columns for display
    rename_map = {"ID": "PR Count", "Total Reviewers": "Avg Reviewers"}
    if approval_col in agg_dict:
        rename_map[approval_col] = "Avg Approvals"
    if comments_col in agg_dict:
        rename_map[comments_col] = "Avg Comments"
    repo_metrics.rename(columns=rename_map, inplace=True)

    # Sort based on selection
    sort_column = sort_by.replace(" ", "_").lower()
    if sort_column == "pr_count":
        sort_column = "PR Count"
    elif sort_column == "avg_approvals":
        sort_column = "Avg Approvals"
    elif sort_column == "avg_comments":
        sort_column = "Avg Comments"

    # Apply view type filtering
    if view_type == "Top Performers":
        repo_data = repo_metrics.sort_values(sort_column, ascending=False).head(
            num_repos
        )
        title_prefix = f"🏆 Top {num_repos}"
    elif view_type == "Bottom Performers":
        repo_data = repo_metrics.sort_values(sort_column, ascending=True).head(
            num_repos
        )
        title_prefix = f"📉 Bottom {num_repos}"
    else:  # Full Range
        repo_data = repo_metrics.sort_values(sort_column, ascending=False).head(
            num_repos
        )
        title_prefix = f"📊 All {num_repos}"

    # Create the chart using DataFrame
    chart_df = repo_data[[sort_column]].reset_index()
    chart_df.columns = ["Repository", sort_by]
    
    fig = px.bar(
        chart_df,
        x=sort_by,
        y="Repository",
        orientation="h",
        title=f"{title_prefix} Repositories by {sort_by}",
        color=sort_by,
        color_continuous_scale=(
            "viridis" if view_type != "Bottom Performers" else "reds"
        ),
    )
    fig.update_layout(height=max(400, num_repos * 20), showlegend=False)
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, width="stretch")

    # Show detailed metrics table
    st.subheader(f"📋 Detailed Metrics - {title_prefix} Repositories")
    st.dataframe(repo_data, width="stretch")

    # Repository stats
    col1, col2, col3, col4 = st.columns(4)

    unique_repos = df["Repository"].nunique()
    total_prs = len(df)
    
    with col1:
        st.metric("Total Repositories", unique_repos)

    with col2:
        st.metric("Total PRs", total_prs)

    with col3:
        avg_prs = total_prs / unique_repos if unique_repos > 0 else 0
        st.metric("Avg PRs per Repo", f"{avg_prs:.1f}")

    with col4:
        if not repo_metrics.empty and "PR Count" in repo_metrics.columns:
            most_active = repo_metrics["PR Count"].idxmax()
            most_active_count = int(repo_metrics.loc[most_active, "PR Count"])
            st.metric("Most Active Repo", most_active, f"{most_active_count} PRs")
        else:
            st.metric("Most Active Repo", "N/A")


def create_temporal_analysis(df: pd.DataFrame):
    """Create temporal analysis visualizations."""
    st.header("📅 Temporal Analysis")

    if df.empty or "Year-Month" not in df.columns:
        st.info("📭 No temporal data available to display.")
        return

    # Time series of PR creation - convert Period to string for JSON serialization
    monthly_counts = df.groupby("Year-Month").size().reset_index(name="Count")
    monthly_counts["Year-Month"] = monthly_counts["Year-Month"].astype(str)
    monthly_counts.columns = ["Year-Month", "Number of PRs"]

    fig = px.line(
        monthly_counts,
        x="Year-Month",
        y="Number of PRs",
        title="PR Creation Over Time",
        markers=True,
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, width="stretch")

    col1, col2 = st.columns(2)

    with col1:
        # Day of week analysis
        if "Weekday" in df.columns:
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
            weekday_counts = weekday_counts.reindex(weekday_order).fillna(0)
            weekday_df = pd.DataFrame({
                "Day": weekday_counts.index,
                "Count": weekday_counts.values
            })

            fig = px.bar(
                weekday_df,
                x="Day",
                y="Count",
                title="PRs by Day of Week",
                color="Count",
                color_continuous_scale="blues",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No weekday data available")

    with col2:
        # Hour of day analysis
        if "Hour" in df.columns:
            hourly_counts = df["Hour"].value_counts().sort_index()
            hourly_df = pd.DataFrame({
                "Hour": hourly_counts.index,
                "Count": hourly_counts.values
            })

            fig = px.bar(
                hourly_df,
                x="Hour",
                y="Count",
                title="PRs by Hour of Day",
                color="Count",
                color_continuous_scale="oranges",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No hourly data available")


def create_contributor_analysis(df: pd.DataFrame):
    """Create contributor analysis visualizations."""
    st.header("👥 Contributor Analysis")

    if df.empty or "Created By" not in df.columns:
        st.info("📭 No contributor data available to display.")
        return

    # Top contributors
    contributor_counts = df["Created By"].value_counts().head(15)
    contrib_df = pd.DataFrame({
        "Count": contributor_counts.values,
        "Contributor": contributor_counts.index
    })

    fig = px.bar(
        contrib_df,
        x="Count",
        y="Contributor",
        orientation="h",
        title="Top 15 PR Contributors",
        color="Count",
        color_continuous_scale="plasma",
    )
    fig.update_layout(height=500, showlegend=False)
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, width="stretch")

    # Reviewer analysis
    col1, col2 = st.columns(2)

    with col1:
        # Distribution of reviewer counts
        if "Reviewer Count" in df.columns:
            reviewer_dist = df["Reviewer Count"].value_counts().sort_index()
            reviewer_df = pd.DataFrame({
                "Reviewers": reviewer_dist.index,
                "Count": reviewer_dist.values
            })

            fig = px.bar(
                reviewer_df,
                x="Reviewers",
                y="Count",
                title="Distribution of Reviewer Counts",
                color="Count",
                color_continuous_scale="greens",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No reviewer count data available")

    with col2:
        # Contributor stats
        st.subheader("Contributor Stats")
        total_contributors = len(df["Created By"].unique())
        avg_prs_per_contributor = len(df) / total_contributors if total_contributors > 0 else 0
        median_prs = df["Created By"].value_counts().median()

        st.metric("Total Contributors", total_contributors)
        st.metric("Avg PRs per Contributor", f"{avg_prs_per_contributor:.1f}")
        st.metric("Median PRs per Contributor", f"{median_prs:.1f}" if pd.notna(median_prs) else "N/A")


def create_repository_heatmap(df: pd.DataFrame):
    """Create a repository activity heatmap."""
    st.header("🔥 Repository Activity Heatmap")

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
    st.plotly_chart(fig, width="stretch")


def create_interactive_filters(df: pd.DataFrame):
    """Show filtered data summary and detailed view."""
    st.header("🔍 Detailed Analysis")

    st.info(
        "💡 Use the filters in the sidebar to refine the data shown across all tabs."
    )

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
            st.metric("Avg Reviewers", f"{avg_reviewers:.1f}")

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
            st.dataframe(df[selected_columns], width="stretch", height=400)
        else:
            st.warning("Please select at least one column to display.")
    else:
        st.warning(
            "No data matches the current filters. Try adjusting the filters in the sidebar."
        )


def create_review_analytics(df: pd.DataFrame):
    """Create comprehensive review analytics and engagement metrics."""
    st.header("💬 Review Analytics & Engagement")

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
            st.metric("Avg Reviewers/PR", f"{avg_reviewers:.1f}")

        return

    # Enhanced analytics when detailed data is available

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

    # Top Metrics Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        total_approvals = sum(approval_counts.values())
        st.metric("Total Approvals", total_approvals)

    with col2:
        comments_col = "Comments" if "Comments" in df.columns else "Total Comments"
        total_comments = (
            df[comments_col].sum() if comments_col in df.columns else 0
        )
        st.metric("Total Comments", int(total_comments))

    with col3:
        total_threads = (
            df["Total Threads"].sum() if "Total Threads" in df.columns else 0
        )
        st.metric("Discussion Threads", int(total_threads))

    with col4:
        unique_reviewers = len(set(approval_counts.keys()) | set(comment_counts.keys()))
        st.metric("Active Reviewers", unique_reviewers)

    st.markdown("---")

    # Interactive Analysis Section
    st.subheader("🔍 Interactive Reviewer Analysis")

    # Control panel
    col1, col2, col3 = st.columns(3)
    with col1:
        analysis_type = st.selectbox(
            "📊 Analysis Type",
            ["Approvers", "Commenters", "Rejectors"],
            help="Choose which reviewer activity to analyze",
        )

    with col2:
        view_perspective = st.selectbox(
            "📈 View Perspective",
            ["Top Performers", "Bottom Performers", "Full Spectrum"],
            help="Show most active, least active, or complete view",
        )

    with col3:
        num_people = st.slider(
            "👥 Number of People",
            min_value=5,
            max_value=30,
            value=15,
            step=5,
            help="How many people to display in the analysis",
        )

    # Get the appropriate data based on analysis type
    if analysis_type == "Approvers":
        data_dict = approval_counts
        metric_name = "Approvals"
        icon = "👍"
        color_scale = "greens"
    elif analysis_type == "Commenters":
        data_dict = comment_counts
        metric_name = "Comments"
        icon = "💬"
        color_scale = "blues"
    else:  # Rejectors
        data_dict = rejection_counts
        metric_name = "Rejections"
        icon = "👎"
        color_scale = "reds"

    # Sort and filter data based on perspective
    if not data_dict:
        st.warning(
            f"No {analysis_type.lower()} data available. This might indicate an issue with data collection."
        )
        return

    sorted_data = sorted(data_dict.items(), key=lambda x: x[1], reverse=True)

    if view_perspective == "Top Performers":
        display_data = sorted_data[:num_people]
        title_prefix = f"🏆 Top {num_people}"
        chart_color = color_scale
    elif view_perspective == "Bottom Performers":
        # Get bottom performers (those with least activity)
        display_data = sorted_data[-num_people:]
        display_data.reverse()  # Show lowest first
        title_prefix = f"📉 Bottom {num_people}"
        chart_color = "greys"
    else:  # Full Spectrum
        display_data = sorted_data[:num_people]
        title_prefix = f"📊 All {num_people}"
        chart_color = color_scale

    # Create the visualization
    if display_data:
        people, counts = zip(*display_data)
        
        chart_df = pd.DataFrame({
            "Count": list(counts),
            "Person": [person.split("@")[0] for person in people]
        })

        fig = px.bar(
            chart_df,
            x="Count",
            y="Person",
            orientation="h",
            title=f"{title_prefix} {analysis_type} by {metric_name} {icon}",
            color="Count",
            color_continuous_scale=chart_color,
        )
        fig.update_layout(
            height=max(400, num_people * 25), showlegend=False, title_font_size=16
        )
        fig.update_yaxes(categoryorder="total ascending")
        st.plotly_chart(fig, width="stretch")

        # Detailed breakdown
        st.subheader(f"📋 Detailed Breakdown - {title_prefix} {analysis_type}")

        breakdown_df = pd.DataFrame(
            [
                {"Person": person, f"{metric_name}": count}
                for person, count in display_data
            ]
        )
        st.dataframe(breakdown_df, width="stretch", hide_index=True)

        # Additional insights
        if len(display_data) > 0:
            avg_activity = sum(counts) / len(counts)
            max_activity = max(counts)
            min_activity = min(counts)

            st.subheader("📈 Insights")
            insight_col1, insight_col2, insight_col3 = st.columns(3)

            with insight_col1:
                st.metric(f"Average {metric_name}", f"{avg_activity:.1f}")
            with insight_col2:
                st.metric(f"Highest {metric_name}", max_activity)
            with insight_col3:
                st.metric(f"Lowest {metric_name}", min_activity)
    else:
        st.warning(f"No data available for {analysis_type.lower()}.")

    # Special Comment Analytics Section
    if analysis_type == "Commenters" and comment_counts:
        st.markdown("---")
        st.subheader("💬 Comment Activity Insights")

        # Quick stats
        total_people_commenting = len(comment_counts)
        total_comments_made = sum(comment_counts.values())
        avg_comments_per_person = (
            total_comments_made / total_people_commenting
            if total_people_commenting > 0
            else 0
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total People Commenting", total_people_commenting)
        with col2:
            st.metric("Total Comments Made", total_comments_made)
        with col3:
            st.metric(
                "Avg Comments per Person",
                f"{avg_comments_per_person:.1f}",
            )

        # Most vs Least Active Commenters
        st.markdown("### 🏆 Top vs 📉 Least Active Commenters")

        sorted_commenters = sorted(
            comment_counts.items(), key=lambda x: x[1], reverse=True
        )

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**🏆 Most Active (Top 5)**")
            top_5 = sorted_commenters[:5]
            for i, (person, count) in enumerate(top_5, 1):
                clean_name = person.split("@")[0]
                st.write(f"{i}. **{clean_name}**: {count} comments")

        with col2:
            st.markdown("**📉 Least Active (Bottom 5)**")
            bottom_5 = sorted_commenters[-5:]
            bottom_5.reverse()  # Show lowest first
            for i, (person, count) in enumerate(bottom_5, 1):
                clean_name = person.split("@")[0]
                st.write(f"{i}. **{clean_name}**: {count} comments")

        # Comment distribution insights
        if len(sorted_commenters) >= 3:
            high_activity = [
                count for _, count in sorted_commenters[: len(sorted_commenters) // 3]
            ]
            low_activity = [
                count for _, count in sorted_commenters[-len(sorted_commenters) // 3 :]
            ]

            st.markdown("### 📊 Activity Distribution")
            dist_col1, dist_col2 = st.columns(2)

            with dist_col1:
                high_avg = (
                    sum(high_activity) / len(high_activity) if high_activity else 0
                )
                st.metric("Top 1/3 Average", f"{high_avg:.1f} comments")

            with dist_col2:
                low_avg = sum(low_activity) / len(low_activity) if low_activity else 0
                st.metric("Bottom 1/3 Average", f"{low_avg:.1f} comments")


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
                "📊 Repository Overview",
                "📅 Temporal Analysis",
                "👥 Contributors",
                "🔥 Activity Heatmap",
                "💬 Review Analytics",
                "🔍 Interactive Analysis",
            ]
        )

        with tabs[0]:
            create_repository_overview(df)

        with tabs[1]:
            create_temporal_analysis(df)

        with tabs[2]:
            create_contributor_analysis(df)

        with tabs[3]:
            create_repository_heatmap(df)

        with tabs[4]:
            create_review_analytics(df)

        with tabs[5]:
            create_interactive_filters(df)

    else:
        st.info("📊 No data available to display")


if __name__ == "__main__":
    main()
