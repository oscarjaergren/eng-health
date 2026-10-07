from __future__ import annotations

import pandas as pd
import streamlit as st

from ... import metrics


def render(df: pd.DataFrame, people: dict[str, str]) -> None:
    out = metrics.export_table(df, people)
    st.download_button(
        "Download CSV",
        out.to_csv(index=False).encode(),
        file_name="pull_requests.csv",
        mime="text/csv",
    )
    st.dataframe(
        out,
        width="stretch",
        hide_index=True,
        column_config={
            "Link": st.column_config.LinkColumn(display_text="Open"),
            "Hours to merge": st.column_config.NumberColumn(format="%.1f"),
            "Hours to first review": st.column_config.NumberColumn(format="%.1f"),
        },
    )
