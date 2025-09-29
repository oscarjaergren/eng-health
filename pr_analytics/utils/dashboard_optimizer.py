"""Dashboard optimization utilities for handling large datasets efficiently."""

import hashlib
import logging
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st


class DataFrameOptimizer:
    """
    Optimizes pandas DataFrames for better performance with large datasets.

    Features:
    - Memory usage optimization
    - Efficient data type conversion
    - Chunked processing for large datasets
    - Caching of expensive operations
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the DataFrame optimizer."""
        self.logger = logger or logging.getLogger(__name__)
        self.cache_dir = Path(".cache/dataframes")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def optimize_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Optimize DataFrame data types to reduce memory usage.

        Args:
            df: Input DataFrame

        Returns:
            Optimized DataFrame with reduced memory usage
        """
        if df.empty:
            return df

        original_memory = df.memory_usage(deep=True).sum()
        optimized_df = df.copy()

        for col in optimized_df.columns:
            col_type = optimized_df[col].dtype

            # Optimize numeric columns
            if pd.api.types.is_numeric_dtype(col_type):
                if pd.api.types.is_integer_dtype(col_type):
                    # Downcast integers
                    optimized_df[col] = pd.to_numeric(
                        optimized_df[col], downcast="integer"
                    )
                else:
                    # Downcast floats
                    optimized_df[col] = pd.to_numeric(
                        optimized_df[col], downcast="float"
                    )

            # Convert object columns to category if beneficial
            elif col_type == "object":
                unique_count = optimized_df[col].nunique()
                total_count = len(optimized_df[col])

                # Convert to category if less than 50% unique values
                if unique_count / total_count < 0.5:
                    optimized_df[col] = optimized_df[col].astype("category")

        optimized_memory = optimized_df.memory_usage(deep=True).sum()
        memory_reduction = (original_memory - optimized_memory) / original_memory * 100

        self.logger.info(
            f"Memory usage reduced by {memory_reduction:.1f}% "
            f"({original_memory / 1024**2:.1f}MB -> {optimized_memory / 1024**2:.1f}MB)"
        )

        return optimized_df

    def create_data_hash(self, df: pd.DataFrame) -> str:
        """Create a hash of the DataFrame for caching purposes."""
        # Create hash based on shape, columns, and sample of data
        hash_data = {
            "shape": df.shape,
            "columns": list(df.columns),
            "dtypes": str(df.dtypes.to_dict()),
            "sample": str(df.head().to_dict()) if not df.empty else "",
        }

        hash_string = str(hash_data)
        return hashlib.md5(hash_string.encode()).hexdigest()[:16]

    @lru_cache(maxsize=32)
    def get_cached_aggregation(self, data_hash: str, operation: str) -> Optional[Any]:
        """Get cached aggregation result if available."""
        cache_file = self.cache_dir / f"{data_hash}_{operation}.pkl"

        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                self.logger.warning(f"Error loading cache {cache_file}: {e}")
                cache_file.unlink()  # Remove corrupted cache

        return None

    def cache_aggregation(self, data_hash: str, operation: str, result: Any) -> None:
        """Cache aggregation result for future use."""
        cache_file = self.cache_dir / f"{data_hash}_{operation}.pkl"

        try:
            with open(cache_file, "wb") as f:
                pickle.dump(result, f)
        except Exception as e:
            self.logger.warning(f"Error caching result {cache_file}: {e}")


class StreamlitOptimizer:
    """
    Optimizes Streamlit dashboard performance for large datasets.

    Features:
    - Efficient data filtering and pagination
    - Lazy loading of visualizations
    - Memory-efficient chart rendering
    - Progress tracking for long operations
    """

    def __init__(self, df_optimizer: DataFrameOptimizer):
        """Initialize the Streamlit optimizer."""
        self.df_optimizer = df_optimizer
        self.logger = logging.getLogger(__name__)

    def paginate_dataframe(
        self, df: pd.DataFrame, page_size: int = 1000
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Implement pagination for large DataFrames.

        Args:
            df: Input DataFrame
            page_size: Number of rows per page

        Returns:
            Tuple of (paginated DataFrame, pagination info)
        """
        if df.empty:
            return df, {"total_pages": 0, "current_page": 1, "total_rows": 0}

        total_rows = len(df)
        total_pages = (total_rows + page_size - 1) // page_size

        # Create pagination controls
        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            current_page = st.number_input(
                f"Page (1-{total_pages})",
                min_value=1,
                max_value=total_pages,
                value=1,
                key="page_selector",
            )

        # Calculate slice indices
        start_idx = (current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total_rows)

        paginated_df = df.iloc[start_idx:end_idx]

        pagination_info = {
            "total_pages": total_pages,
            "current_page": current_page,
            "total_rows": total_rows,
            "showing_rows": f"{start_idx + 1}-{end_idx}",
            "page_size": page_size,
        }

        # Display pagination info
        st.info(
            f"Showing rows {pagination_info['showing_rows']} of {total_rows} "
            f"(Page {current_page} of {total_pages})"
        )

        return paginated_df, pagination_info

    def create_efficient_filter(
        self, df: pd.DataFrame, column: str, filter_type: str = "multiselect"
    ) -> pd.DataFrame:
        """
        Create memory-efficient filters for large datasets.

        Args:
            df: Input DataFrame
            column: Column to filter on
            filter_type: Type of filter ('multiselect', 'selectbox', 'slider')

        Returns:
            Filtered DataFrame
        """
        if df.empty or column not in df.columns:
            return df

        unique_values = df[column].unique()

        # Limit options for very large datasets
        if len(unique_values) > 1000:
            st.warning(
                f"Column '{column}' has {len(unique_values)} unique values. "
                "Showing top 100 most frequent values for performance."
            )

            # Get top 100 most frequent values
            value_counts = df[column].value_counts().head(100)
            unique_values = value_counts.index.tolist()

        if filter_type == "multiselect":
            selected_values = st.multiselect(
                f"Filter by {column}",
                options=unique_values,
                default=unique_values[
                    : min(10, len(unique_values))
                ],  # Default to first 10
                key=f"filter_{column}",
            )

            if selected_values:
                return df[df[column].isin(selected_values)]

        elif filter_type == "selectbox":
            selected_value = st.selectbox(
                f"Filter by {column}",
                options=["All"] + list(unique_values),
                key=f"filter_{column}",
            )

            if selected_value != "All":
                return df[df[column] == selected_value]

        elif filter_type == "slider" and pd.api.types.is_numeric_dtype(df[column]):
            min_val, max_val = float(df[column].min()), float(df[column].max())

            selected_range = st.slider(
                f"Filter by {column}",
                min_value=min_val,
                max_value=max_val,
                value=(min_val, max_val),
                key=f"filter_{column}",
            )

            return df[
                (df[column] >= selected_range[0]) & (df[column] <= selected_range[1])
            ]

        return df

    def create_lazy_chart(
        self, df: pd.DataFrame, chart_func: callable, chart_title: str, **kwargs
    ) -> None:
        """
        Create charts with lazy loading for better performance.

        Args:
            df: Input DataFrame
            chart_func: Function to create the chart
            chart_title: Title for the chart
            **kwargs: Additional arguments for chart function
        """
        # Only render chart if data is not too large or if user explicitly
        # requests it
        if len(df) > 10000:
            if st.button(
                f"Load {chart_title} (Large Dataset)", key=f"load_{chart_title}"
            ):
                with st.spinner(f"Generating {chart_title}..."):
                    chart_func(df, **kwargs)
            else:
                st.info(
                    f"📊 {chart_title} - Click to load (Dataset has {len(df):,} rows)"
                )
        else:
            chart_func(df, **kwargs)

    def optimize_plotly_chart(self, fig, max_points: int = 5000):
        """
        Optimize Plotly charts for better performance with large datasets.

        Args:
            fig: Plotly figure object
            max_points: Maximum number of data points to display

        Returns:
            Optimized figure
        """
        # Sample data if too many points
        for trace in fig.data:
            if hasattr(trace, "x") and trace.x is not None:
                if len(trace.x) > max_points:
                    # Sample data points
                    indices = np.linspace(0, len(trace.x) - 1, max_points, dtype=int)

                    if hasattr(trace, "y") and trace.y is not None:
                        trace.x = [trace.x[i] for i in indices]
                        trace.y = [trace.y[i] for i in indices]

                    # Add annotation about sampling
                    fig.add_annotation(
                        text=f"Showing {max_points:,} sampled points from {len(trace.x):,} total",
                        xref="paper",
                        yref="paper",
                        x=0.02,
                        y=0.98,
                        showarrow=False,
                        font=dict(size=10, color="gray"),
                    )

        # Optimize layout for performance
        fig.update_layout(
            showlegend=True,
            hovermode="closest",
            # Disable some interactive features for better performance
            dragmode="pan",
        )

        return fig

    def create_summary_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Create summary metrics optimized for large datasets.

        Args:
            df: Input DataFrame

        Returns:
            Dictionary of summary metrics
        """
        if df.empty:
            return {}

        # Use data hash for caching
        data_hash = self.df_optimizer.create_data_hash(df)

        # Try to get cached metrics
        cached_metrics = self.df_optimizer.get_cached_aggregation(
            data_hash, "summary_metrics"
        )
        if cached_metrics:
            return cached_metrics

        # Calculate metrics
        metrics = {
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "memory_usage_mb": df.memory_usage(deep=True).sum() / 1024**2,
            "date_range": None,
            "numeric_columns": [],
            "categorical_columns": [],
        }

        # Date range if datetime columns exist
        datetime_cols = df.select_dtypes(include=["datetime64"]).columns
        if len(datetime_cols) > 0:
            first_date = df[datetime_cols[0]].min()
            last_date = df[datetime_cols[0]].max()
            metrics[
                "date_range"
            ] = f"{first_date.strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')}"

        # Column type analysis
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                metrics["numeric_columns"].append(
                    {
                        "name": col,
                        "min": float(df[col].min()),
                        "max": float(df[col].max()),
                        "mean": float(df[col].mean()),
                    }
                )
            elif (
                pd.api.types.is_categorical_dtype(df[col]) or df[col].dtype == "object"
            ):
                metrics["categorical_columns"].append(
                    {
                        "name": col,
                        "unique_values": int(df[col].nunique()),
                        "most_common": (
                            str(df[col].mode().iloc[0])
                            if not df[col].mode().empty
                            else "N/A"
                        ),
                    }
                )

        # Cache the metrics
        self.df_optimizer.cache_aggregation(data_hash, "summary_metrics", metrics)

        return metrics

    def display_performance_info(self, df: pd.DataFrame) -> None:
        """Display performance information and optimization tips."""
        metrics = self.create_summary_metrics(df)

        if not metrics:
            return

        # Performance info in expandable section
        with st.expander("📈 Performance Information", expanded=False):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Total Rows", f"{metrics['total_rows']:,}")
                st.metric(
                    "Memory Usage",
                    f"{metrics['memory_usage_mb']:.1f} MB",
                )

            with col2:
                st.metric("Total Columns", metrics["total_columns"])
                if metrics["date_range"]:
                    st.metric("Date Range", metrics["date_range"])

            with col3:
                st.metric("Numeric Columns", len(metrics["numeric_columns"]))
                st.metric("Categorical Columns", len(metrics["categorical_columns"]))

            # Performance tips
            if metrics["total_rows"] > 10000:
                st.info(
                    "💡 **Performance Tips:**\n"
                    "- Use filters to reduce dataset size\n"
                    "- Charts may be lazy-loaded for large datasets\n"
                    "- Consider using pagination for detailed views"
                )

            if metrics["memory_usage_mb"] > 100:
                st.warning(
                    "⚠️ **Memory Usage Warning:**\n"
                    f"Dataset is using {metrics['memory_usage_mb']:.1f} MB of memory. "
                    "Consider filtering data or using sampling for better performance."
                )


def create_progress_tracker(total_items: int, description: str = "Processing"):
    """
    Create a progress tracker for long-running operations.

    Args:
        total_items: Total number of items to process
        description: Description of the operation

    Returns:
        Progress bar object
    """
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(completed_items: int):
        progress = completed_items / total_items
        progress_bar.progress(progress)
        status_text.text(
            f"{description}: {completed_items}/{total_items} ({progress:.1%})"
        )

    return update_progress
