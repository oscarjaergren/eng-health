"""The sidebar's Connect panel: pick accounts through the gh and az CLIs, with no token to paste."""

from __future__ import annotations

import streamlit as st

from .. import connections
from ..config import Settings


@st.cache_data(ttl=300, show_spinner="Asking the gh CLI…")
def _github_accounts() -> list[tuple[str, str]] | None:
    return connections.github_accounts()


@st.cache_data(ttl=300, show_spinner="Asking the az CLI…")
def _azure_organizations() -> list[str] | None:
    return connections.azure_organizations()


def _disconnect(settings: Settings, platform: str, name: str, cli: str, owner: str) -> None:
    st.caption(f"{name}: **{owner}**, through the {cli} CLI.")
    if st.button(f"Disconnect {name}", key=f"disconnect_{platform}"):
        connections.save(settings.data_dir, platform, None)
        st.rerun()


def _github(settings: Settings) -> None:
    owner = settings.github_owner
    if owner and "github" not in settings.connected:
        st.caption(f"GitHub: **{owner}**, from `.env`.")
        return
    if owner:
        _disconnect(settings, "github", "GitHub", "gh", owner)
        return
    accounts = _github_accounts()
    if accounts is None:
        st.caption(
            "GitHub: sign in with `gh auth login` in a terminal, then reload. "
            "Or set GITHUB_OWNER and GITHUB_TOKEN in `.env`."
        )
        return
    pick = st.selectbox(
        "GitHub account or organisation",
        range(len(accounts)),
        format_func=lambda i: f"{accounts[i][0]} ({accounts[i][1]})",
        key="github_pick",
    )
    if st.button("Connect GitHub", key="connect_github", type="primary"):
        owner, kind = accounts[pick]
        connections.save(settings.data_dir, "github", {"owner": owner, "type": kind})
        st.rerun()


def _azure(settings: Settings) -> None:
    organization = settings.azure_organization
    if organization and "azure_devops" not in settings.connected:
        st.caption(f"Azure DevOps: **{organization}**, from `.env`.")
        return
    if organization:
        _disconnect(settings, "azure_devops", "Azure DevOps", "az", organization)
        return
    organizations = _azure_organizations()
    if organizations is None:
        st.caption(
            "Azure DevOps: sign in with `az login` in a terminal, then reload. Or set "
            "AZURE_DEVOPS_ORGANIZATION and AZURE_DEVOPS_PAT in `.env`."
        )
        return
    if not organizations:
        st.caption("Azure DevOps: this az account is not a member of any organisation.")
        return
    pick = st.selectbox("Azure DevOps organisation", organizations, key="azure_pick")
    if st.button("Connect Azure DevOps", key="connect_azure_devops", type="primary"):
        connections.save(settings.data_dir, "azure_devops", {"organization": pick})
        st.rerun()


def render(settings: Settings) -> None:
    with st.sidebar.expander("Connect", expanded=not settings.platforms):
        st.caption("Uses your gh and az logins; no token is stored.")
        _github(settings)
        _azure(settings)
