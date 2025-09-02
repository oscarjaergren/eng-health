"""
PR Data Visualizer Dashboard

A Streamlit web application for visualizing Azure DevOps Pull Request data.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from collections import Counter
import os


def load_data(file_path: str) -> pd.DataFrame:
    """Load and preprocess the PR data."""
    try:
        df = pd.read_excel(file_path)
        # Convert Created Date to datetime
        df['Created Date'] = pd.to_datetime(df['Created Date'])
        # Extract datetime components for analysis
        df['Year'] = df['Created Date'].dt.year
        df['Month'] = df['Created Date'].dt.month
        df['Day'] = df['Created Date'].dt.day
        df['Weekday'] = df['Created Date'].dt.day_name()
        df['Hour'] = df['Created Date'].dt.hour
        # Create year-month column for time series
        df['Year-Month'] = df['Created Date'].dt.to_period('M')
        # Clean up reviewer data
        df['Reviewer Count'] = df['Assigned To'].apply(
            lambda x: len(eval(x)) if pd.notna(x) and x != '[]' else 0
        )
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()


def create_repository_overview(df: pd.DataFrame):
    """Create repository overview visualizations."""
    st.header("📊 Repository Overview")
    
    # Interactive controls
    col1, col2, col3 = st.columns(3)
    with col1:
        view_type = st.selectbox(
            "📈 View Type",
            ["Top Performers", "Bottom Performers", "Full Range"],
            help="Choose whether to show most active, least active, or all repositories"
        )
    
    with col2:
        num_repos = st.slider(
            "📊 Number of Repos",
            min_value=5, max_value=50, value=20, step=5,
            help="How many repositories to display"
        )
    
    with col3:
        sort_by = st.selectbox(
            "📋 Sort By",
            ["PR Count", "Avg Approvals", "Avg Comments"],
            help="Metric to sort repositories by"
        )
    
    # Calculate repository metrics
    repo_metrics = df.groupby('Repository').agg({
        'ID': 'count',
        'Approval Count': 'mean',
        'Total Comments': 'mean',
        'Total Reviewers': 'mean'
    }).round(2)
    repo_metrics.columns = ['PR Count', 'Avg Approvals', 'Avg Comments', 'Avg Reviewers']
    
    # Sort based on selection
    sort_column = sort_by.replace(' ', '_').lower()
    if sort_column == 'pr_count':
        sort_column = 'PR Count'
    elif sort_column == 'avg_approvals':
        sort_column = 'Avg Approvals'
    elif sort_column == 'avg_comments':
        sort_column = 'Avg Comments'
    
    # Apply view type filtering
    if view_type == "Top Performers":
        repo_data = repo_metrics.sort_values(sort_column, ascending=False).head(num_repos)
        title_prefix = f"🏆 Top {num_repos}"
    elif view_type == "Bottom Performers":
        repo_data = repo_metrics.sort_values(sort_column, ascending=True).head(num_repos)
        title_prefix = f"📉 Bottom {num_repos}"
    else:  # Full Range
        repo_data = repo_metrics.sort_values(sort_column, ascending=False).head(num_repos)
        title_prefix = f"📊 All {num_repos}"
    
    # Create the chart
    chart_values = repo_data[sort_column]
    fig = px.bar(
        x=chart_values.values,
        y=chart_values.index,
        orientation='h',
        title=f"{title_prefix} Repositories by {sort_by}",
        labels={'x': sort_by, 'y': 'Repository'},
        color=chart_values.values,
        color_continuous_scale='viridis' if view_type != "Bottom Performers" else 'reds'
    )
    fig.update_layout(height=max(400, num_repos * 20), showlegend=False)
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, width='stretch')
    
    # Show detailed metrics table
    st.subheader(f"📋 Detailed Metrics - {title_prefix} Repositories")
    st.dataframe(repo_data, width='stretch')
    
    # Repository stats
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Repositories", len(df['Repository'].unique()))
    
    with col2:
        st.metric("Total PRs", len(df))
    
    with col3:
        avg_prs = len(df) / len(df['Repository'].unique())
        st.metric("Avg PRs per Repo", f"{avg_prs:.1f}")
    
    with col4:
        most_active = repo_metrics['PR Count'].idxmax()
        most_active_count = int(repo_metrics.loc[most_active, 'PR Count'])
        st.metric("Most Active Repo", most_active, f"{most_active_count} PRs")


def create_temporal_analysis(df: pd.DataFrame):
    """Create temporal analysis visualizations."""
    st.header("📅 Temporal Analysis")
    
    # Time series of PR creation
    monthly_counts = df.groupby('Year-Month').size()
    
    fig = px.line(
        x=monthly_counts.index.astype(str),
        y=monthly_counts.values,
        title="PR Creation Over Time",
        labels={'x': 'Year-Month', 'y': 'Number of PRs'},
        markers=True
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Day of week analysis
        weekday_counts = df['Weekday'].value_counts()
        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekday_counts = weekday_counts.reindex(weekday_order)
        
        fig = px.bar(
            x=weekday_counts.index,
            y=weekday_counts.values,
            title="PRs by Day of Week",
            labels={'x': 'Day of Week', 'y': 'Number of PRs'},
            color=weekday_counts.values,
            color_continuous_scale='blues'
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Hour of day analysis
        hourly_counts = df['Hour'].value_counts().sort_index()
        
        fig = px.bar(
            x=hourly_counts.index,
            y=hourly_counts.values,
            title="PRs by Hour of Day",
            labels={'x': 'Hour', 'y': 'Number of PRs'},
            color=hourly_counts.values,
            color_continuous_scale='oranges'
        )
        st.plotly_chart(fig, use_container_width=True)


def create_contributor_analysis(df: pd.DataFrame):
    """Create contributor analysis visualizations."""
    st.header("👥 Contributor Analysis")
    
    # Top contributors
    contributor_counts = df['Created By'].value_counts().head(15)
    
    fig = px.bar(
        x=contributor_counts.values,
        y=contributor_counts.index,
        orientation='h',
        title="Top 15 PR Contributors",
        labels={'x': 'Number of PRs', 'y': 'Contributor'},
        color=contributor_counts.values,
        color_continuous_scale='plasma'
    )
    fig.update_layout(height=500, showlegend=False)
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, use_container_width=True)
    
    # Reviewer analysis
    col1, col2 = st.columns(2)
    
    with col1:
        # Distribution of reviewer counts
        reviewer_dist = df['Reviewer Count'].value_counts().sort_index()
        
        fig = px.bar(
            x=reviewer_dist.index,
            y=reviewer_dist.values,
            title="Distribution of Reviewer Counts",
            labels={'x': 'Number of Reviewers', 'y': 'Number of PRs'},
            color=reviewer_dist.values,
            color_continuous_scale='greens'
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Contributor stats
        st.subheader("Contributor Stats")
        total_contributors = len(df['Created By'].unique())
        avg_prs_per_contributor = len(df) / total_contributors
        median_prs = df['Created By'].value_counts().median()
        
        st.metric("Total Contributors", total_contributors)
        st.metric("Avg PRs per Contributor", f"{avg_prs_per_contributor:.1f}")
        st.metric("Median PRs per Contributor", f"{median_prs:.1f}")


def create_repository_heatmap(df: pd.DataFrame):
    """Create a repository activity heatmap."""
    st.header("🔥 Repository Activity Heatmap")
    
    # Create repository-month matrix
    repo_month_data = df.groupby(['Repository', 'Year-Month']).size().unstack(fill_value=0)
    
    # Select top repositories for better visualization
    top_repos = df['Repository'].value_counts().head(20).index
    heatmap_data = repo_month_data.loc[top_repos]
    
    fig = px.imshow(
        heatmap_data.values,
        x=heatmap_data.columns.astype(str),
        y=heatmap_data.index,
        title="Repository Activity Heatmap (Top 20 Repos)",
        labels={'x': 'Year-Month', 'y': 'Repository', 'color': 'PR Count'},
        color_continuous_scale='viridis'
    )
    fig.update_layout(height=600)
    st.plotly_chart(fig, use_container_width=True)


def create_interactive_filters(df: pd.DataFrame):
    """Show filtered data summary and detailed view."""
    st.header("🔍 Detailed Analysis")
    
    st.info("💡 Use the filters in the sidebar to refine the data shown across all tabs.")
    
    # Display filtered results summary
    st.subheader(f"Current Dataset ({len(df)} PRs)")
    
    if len(df) > 0:
        # Quick stats for the filtered data
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total PRs", len(df))
        
        with col2:
            st.metric("Repositories", len(df['Repository'].unique()))
        
        with col3:
            st.metric("Contributors", len(df['Created By'].unique()))
        
        with col4:
            avg_reviewers = df['Reviewer Count'].mean()
            st.metric("Avg Reviewers", f"{avg_reviewers:.1f}")
        
        # Show detailed data table
        st.subheader("📋 Detailed PR Data")
        
        # Select columns to display
        available_columns = df.columns.tolist()
        default_columns = ['Repository', 'Title', 'Created By', 'Created Date', 'Status', 'Reviewer Count']
        display_columns = [col for col in default_columns if col in available_columns]
        
        selected_columns = st.multiselect(
            "Select columns to display:",
            available_columns,
            default=display_columns,
            key="column_selector"
        )
        
        if selected_columns:
            st.dataframe(
                df[selected_columns],
                use_container_width=True,
                height=400
            )
        else:
            st.warning("Please select at least one column to display.")
    else:
        st.warning("No data matches the current filters. Try adjusting the filters in the sidebar.")


def create_review_analytics(df: pd.DataFrame):
    """Create comprehensive review analytics and engagement metrics."""
    st.header("💬 Review Analytics & Engagement")
    
    # Check if we have the detailed review data
    if 'Approved By' not in df.columns:
        st.warning("""
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
        """)
        
        # Show basic analytics with current data
        st.subheader("📊 Basic Review Analytics (Current Data)")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total PRs", len(df))
        with col2:
            st.metric("Total Contributors", len(df['Created By'].unique()))
        with col3:
            avg_reviewers = df['Reviewer Count'].mean() if 'Reviewer Count' in df.columns else 0
            st.metric("Avg Reviewers/PR", f"{avg_reviewers:.1f}")
        
        return
    
    # Enhanced analytics when detailed data is available
    st.success("✅ **Enhanced Review Data Available** - Showing detailed analytics!")
    
    # Extract reviewer data
    approval_counts = {}
    comment_counts = {}
    rejection_counts = {}
    
    for _, row in df.iterrows():
        # Process approvers
        if pd.notna(row.get('Approved By')):
            approvers = eval(row['Approved By']) if isinstance(row['Approved By'], str) else row['Approved By']
            for approver in approvers:
                clean_approver = approver.split(' (')[0]  # Remove "(with suggestions)" part
                approval_counts[clean_approver] = approval_counts.get(clean_approver, 0) + 1
        
        # Process commenters - use the new Comment Counts data
        if pd.notna(row.get('Comment Counts')):
            # Comment Counts is a dict of {person: count} per PR
            pr_comment_counts = eval(row['Comment Counts']) if isinstance(row['Comment Counts'], str) else row['Comment Counts']
            if isinstance(pr_comment_counts, dict):
                for commenter, count in pr_comment_counts.items():
                    comment_counts[commenter] = comment_counts.get(commenter, 0) + count
        elif pd.notna(row.get('Commenters')):
            # Fallback to old method if Comment Counts not available
            commenters = eval(row['Commenters']) if isinstance(row['Commenters'], str) else row['Commenters']
            for commenter in commenters:
                comment_counts[commenter] = comment_counts.get(commenter, 0) + 1
        
        # Process rejections
        if pd.notna(row.get('Rejected By')):
            rejectors = eval(row['Rejected By']) if isinstance(row['Rejected By'], str) else row['Rejected By']
            for rejector in rejectors:
                rejection_counts[rejector] = rejection_counts.get(rejector, 0) + 1
    
    # Top Metrics Row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_approvals = sum(approval_counts.values())
        st.metric("Total Approvals", total_approvals)
    
    with col2:
        total_comments = df['Total Comments'].sum() if 'Total Comments' in df.columns else 0
        st.metric("Total Comments", int(total_comments))
    
    with col3:
        total_threads = df['Total Threads'].sum() if 'Total Threads' in df.columns else 0
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
            help="Choose which reviewer activity to analyze"
        )
    
    with col2:
        view_perspective = st.selectbox(
            "📈 View Perspective", 
            ["Top Performers", "Bottom Performers", "Full Spectrum"],
            help="Show most active, least active, or complete view"
        )
    
    with col3:
        num_people = st.slider(
            "👥 Number of People",
            min_value=5, max_value=30, value=15, step=5,
            help="How many people to display in the analysis"
        )
    
    # Get the appropriate data based on analysis type
    if analysis_type == "Approvers":
        data_dict = approval_counts
        metric_name = "Approvals"
        icon = "👍"
        color_scale = 'greens'
    elif analysis_type == "Commenters":
        data_dict = comment_counts  
        metric_name = "Comments"
        icon = "💬"
        color_scale = 'blues'
    else:  # Rejectors
        data_dict = rejection_counts
        metric_name = "Rejections"
        icon = "👎"
        color_scale = 'reds'
    
    # Sort and filter data based on perspective
    if not data_dict:
        st.warning(f"No {analysis_type.lower()} data available. This might indicate an issue with data collection.")
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
        chart_color = 'greys'
    else:  # Full Spectrum
        display_data = sorted_data[:num_people]
        title_prefix = f"📊 All {num_people}"
        chart_color = color_scale
    
    # Create the visualization
    if display_data:
        people, counts = zip(*display_data)
        
        fig = px.bar(
            x=list(counts),
            y=[person.split('@')[0] for person in people],  # Remove email domain for cleaner display
            orientation='h',
            title=f"{title_prefix} {analysis_type} by {metric_name} {icon}",
            labels={'x': f'Number of {metric_name}', 'y': 'Person'},
            color=list(counts),
            color_continuous_scale=chart_color
        )
        fig.update_layout(
            height=max(400, num_people * 25), 
            showlegend=False,
            title_font_size=16
        )
        fig.update_yaxes(categoryorder="total ascending")
        st.plotly_chart(fig, width='stretch')
        
        # Detailed breakdown
        st.subheader(f"📋 Detailed Breakdown - {title_prefix} {analysis_type}")
        
        breakdown_df = pd.DataFrame([
            {"Person": person, f"{metric_name}": count} 
            for person, count in display_data
        ])
        st.dataframe(breakdown_df, width='stretch', hide_index=True)
        
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
        avg_comments_per_person = total_comments_made / total_people_commenting if total_people_commenting > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total People Commenting", total_people_commenting)
        with col2:
            st.metric("Total Comments Made", total_comments_made)
        with col3:
            st.metric("Avg Comments per Person", f"{avg_comments_per_person:.1f}")
        
        # Most vs Least Active Commenters
        st.markdown("### 🏆 Top vs 📉 Least Active Commenters")
        
        sorted_commenters = sorted(comment_counts.items(), key=lambda x: x[1], reverse=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**🏆 Most Active (Top 5)**")
            top_5 = sorted_commenters[:5]
            for i, (person, count) in enumerate(top_5, 1):
                clean_name = person.split('@')[0]
                st.write(f"{i}. **{clean_name}**: {count} comments")
        
        with col2:
            st.markdown("**📉 Least Active (Bottom 5)**")
            bottom_5 = sorted_commenters[-5:]
            bottom_5.reverse()  # Show lowest first
            for i, (person, count) in enumerate(bottom_5, 1):
                clean_name = person.split('@')[0]
                st.write(f"{i}. **{clean_name}**: {count} comments")
        
        # Comment distribution insights
        if len(sorted_commenters) >= 3:
            high_activity = [count for _, count in sorted_commenters[:len(sorted_commenters)//3]]
            low_activity = [count for _, count in sorted_commenters[-len(sorted_commenters)//3:]]
            
            st.markdown("### 📊 Activity Distribution")
            dist_col1, dist_col2 = st.columns(2)
            
            with dist_col1:
                high_avg = sum(high_activity) / len(high_activity) if high_activity else 0
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
        initial_sidebar_state="expanded"
    )
    
    st.title("📊 Azure DevOps PR Data Dashboard")
    st.markdown("---")
    
    # File upload or use existing file
    data_file = "pr_data.xlsx"
    
    if os.path.exists(data_file):
        st.success(f"✅ Found existing data file: {data_file}")
        df = load_data(data_file)
        
        if not df.empty:
            # Show data filtering information in sidebar
            st.sidebar.markdown("### 🔍 Data Filtering")
            st.sidebar.info("""
            **Default Exclusions Applied:**
            - ❌ IAC-related PRs (Infrastructure as Code)
            - ❌ Personal approvals (self-approvals)
            
            *This focuses analysis on meaningful peer code reviews.*
            """)
            
            st.sidebar.markdown("**💡 To include filtered items:**")
            st.sidebar.code("""
# In your .env file:
EXCLUDE_IAC=false
EXCLUDE_PERSONAL_APPROVALS=false
            """)
            
            # Add global filters in sidebar
            st.sidebar.subheader("📊 Filters")
            
            # Date range filter
            if 'Created Date' in df.columns:
                df['Created Date'] = pd.to_datetime(df['Created Date'])
                min_date = df['Created Date'].min().date()
                max_data_date = df['Created Date'].max().date()
                today = datetime.today().date()
                max_allowed = max(today, max_data_date)
                date_range = st.sidebar.date_input(
                    "Select Date Range",
                    value=(min_date, max_allowed),
                    min_value=min_date,
                    max_value=max_allowed,
                    key="main_date_filter"
                )
                
                if len(date_range) == 2:
                    start_date, end_date = date_range
                    df = df[(df['Created Date'].dt.date >= start_date) & 
                           (df['Created Date'].dt.date <= end_date)]
            
            # Repository filter
            if 'Repository' in df.columns:
                repos = ['All'] + sorted(df['Repository'].unique().tolist())
                selected_repo = st.sidebar.selectbox("Select Repository", repos, key="main_repo_filter")
                if selected_repo != 'All':
                    df = df[df['Repository'] == selected_repo]
            
            # Contributor filter
            if 'Created By' in df.columns:
                contributors = ['All'] + sorted(df['Created By'].unique().tolist())
                selected_contributor = st.sidebar.selectbox("Select Contributor", contributors, key="main_contributor_filter")
                if selected_contributor != 'All':
                    df = df[df['Created By'] == selected_contributor]
            
            # Show data summary (after filtering)
            total_prs = len(df)
            st.sidebar.metric("📈 Filtered PRs", total_prs)
            
            if 'Approved By' in df.columns:
                # Count PRs with approvals (excluding empty lists)
                approved_prs = sum(1 for approvals in df['Approved By'] if approvals and len(eval(str(approvals)) if isinstance(approvals, str) else approvals) > 0)
                st.sidebar.metric("👍 PRs with Approvals", approved_prs)
            
            # Create tabs for different views
            tabs = st.tabs([
                "📊 Repository Overview", 
                "📅 Temporal Analysis", 
                "👥 Contributors", 
                "🔥 Activity Heatmap",
                "� Review Analytics",
                "�🔍 Interactive Analysis"
            ])
            
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
        st.error(f"❌ Data file '{data_file}' not found. Please run the PR extraction script first.")
        
        st.markdown("""
        ### How to generate the data:
        1. Configure your `.env` file with Azure DevOps credentials
        2. Run the extraction script: `python src/main.py`
        3. Refresh this dashboard to load the generated data
        """)


if __name__ == "__main__":
    main()
