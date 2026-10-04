from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ... import metrics
from ..charts import ACCENT, SECOND, heatmap, show


def render(df: pd.DataFrame, people: dict[str, str]) -> None:
    def name(p: str) -> str:
        return people.get(p, p)

    exclude_own = not st.toggle(
        "Count comments on your own PRs",
        value=False,
        help="Authors replying on their own PRs is not reviewing, so it is left out by default.",
    )
    activity = metrics.reviewer_activity(df, exclude_own_comments=exclude_own)
    if activity.empty:
        st.info("No review activity in the current selection.")
        return
    shown = activity.rename(index=name)

    top = shown.head(20)[["PRs reviewed", "PRs authored"]].iloc[::-1]
    long = top.reset_index().melt("person", var_name="series", value_name="PRs")
    fig = px.bar(
        long,
        x="PRs",
        y="person",
        color="series",
        orientation="h",
        barmode="group",
        title="Reviews given and PRs authored (top 20 reviewers)",
        color_discrete_sequence=[ACCENT, SECOND],
        labels={"person": ""},
    )
    fig.update_layout(height=max(320, 40 * len(top)))
    show(fig)

    st.dataframe(
        shown,
        width="stretch",
        column_config={
            "PRs reviewed": st.column_config.NumberColumn(
                help="PRs by someone else that this person commented on, voted on or reviewed"
            ),
            "Median response (h)": st.column_config.NumberColumn(
                format="%.1f", help="Median time from a PR opening to this person's first response"
            ),
        },
    )

    quiet = metrics.non_reviewers(activity)
    if not quiet.empty:
        st.subheader("Authoring but not reviewing")
        st.caption("People who opened PRs in this selection but have not reviewed anyone else's.")
        st.dataframe(quiet.rename(index=name), width="stretch")

    st.subheader("Where people comment")
    rows = metrics.comment_rows(df, exclude_own)
    if rows.empty:
        st.info("No comments in the current selection.")
        return
    grid = rows.pivot_table(
        index="person", columns="repository", values="comments", aggfunc="sum", fill_value=0
    )
    grid = grid.loc[grid.sum(axis=1).nlargest(25).index, grid.sum().nlargest(25).index]
    heatmap(grid.rename(index=name), "Comments by person and repository", "", "", "Comments")

    commenters = (
        rows.groupby("person")["comments"].sum().sort_values(ascending=False).index.tolist()
    )
    person = st.selectbox("Show the PRs this person commented on", commenters, format_func=name)
    mine = (
        rows[rows["person"] == person]
        .merge(df[["key", "state", "created_at", "url"]], on="key")
        .assign(author=lambda d: d["author"].map(name))
        .sort_values("comments", ascending=False)
    )
    st.dataframe(
        mine[["title", "repository", "author", "comments", "state", "created_at", "url"]],
        width="stretch",
        hide_index=True,
        column_config={
            "title": "Title",
            "repository": "Repository",
            "author": "Author",
            "comments": "Comments",
            "state": "State",
            "created_at": st.column_config.DatetimeColumn("Created", format="YYYY-MM-DD"),
            "url": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )
