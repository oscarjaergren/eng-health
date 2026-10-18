"""The Settings drawer: connect through the gh and az CLIs (no token to paste), sync, aliases."""

from __future__ import annotations

import streamlit as st

from .. import connections, sync
from ..config import Settings
from ..models import PLATFORM_NAMES
from ..store import Store
from .charts import esc, html
from .data import relative


@st.cache_data(ttl=300, show_spinner="Asking the gh CLI…")
def _github_accounts() -> list[tuple[str, str]] | None:
    return connections.github_accounts()


@st.cache_data(ttl=300, show_spinner="Asking the az CLI…")
def _azure_organizations() -> list[str] | None:
    return connections.azure_organizations()


def request_sync(kind: str) -> None:
    st.session_state["sync_request"] = kind


def show(open_: bool = True) -> None:
    """Open or close the drawer. It stays open across reruns, such as after Connect."""
    st.session_state["settings_open"] = open_


def _source(platform: str, status: str, tone: str = "") -> None:
    """A data source's monogram, name and status."""
    mono = {"github": "GH", "azure_devops": "AZ"}[platform]
    html(
        f'<div class="source"><span class="mono">{mono}</span><div>'
        f'<b>{PLATFORM_NAMES[platform]}</b><small class="{tone}">{esc(status)}</small></div></div>'
    )


def _connected(settings: Settings, store: Store | None, platform: str, owner: str) -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        if platform in settings.connected:
            _source(platform, f"● Connected · {owner}", "tone-green")
            if st.button("Disconnect", key=f"disconnect_{platform}"):
                connections.save(settings.data_dir, platform, None)
                st.rerun()
        else:
            _source(platform, f"● Connected · {owner}, from .env", "tone-green")
    if platform == "github":
        st.caption(
            "Pull requests, reviews and comments. Actions runs, CI minutes, flaky jobs and tests."
        )
    else:
        st.caption("Pull requests, reviews and comments.")
        st.caption(
            ":orange[Azure DevOps reports no line counts and its pipelines aren't synced, so PR "
            "size, lines and CI cover GitHub only.]"
        )
    if store is not None:
        st.caption(f"Last synced {relative(store.sync_state(platform).last_sync)}")


def _signed_out(platform: str, cli: str, login: str, env: str) -> None:
    _source(platform, f"Not signed in to the {cli} CLI")
    st.caption(f"Run this in a terminal, then check again. Or set {env} in `.env`.")
    st.code(login, language="bash")
    if st.button("Check again", key=f"check_{platform}"):
        _github_accounts.clear()
        _azure_organizations.clear()
        st.rerun(scope="fragment")


def _github(settings: Settings, store: Store | None) -> None:
    if settings.github_owner:
        _connected(settings, store, "github", settings.github_owner)
        return
    accounts = _github_accounts()
    if accounts is None:
        _signed_out("github", "gh", "gh auth login", "GITHUB_OWNER and GITHUB_TOKEN")
        return
    _source("github", f"Signed in to gh as {accounts[0][0]}")
    pick = st.radio(
        "Account or organisation",
        range(len(accounts)),
        format_func=lambda i: f"{accounts[i][0]} ({accounts[i][1]})",
        key="github_pick",
    )
    if st.button("Connect GitHub", key="connect_github", type="primary"):
        owner, kind = accounts[pick]
        connections.save(settings.data_dir, "github", {"owner": owner, "type": kind})
        st.rerun()


def _azure(settings: Settings, store: Store | None) -> None:
    if settings.azure_organization:
        _connected(settings, store, "azure_devops", settings.azure_organization)
        return
    organizations = _azure_organizations()
    if organizations is None:
        _signed_out(
            "azure_devops", "az", "az login", "AZURE_DEVOPS_ORGANIZATION and AZURE_DEVOPS_PAT"
        )
        return
    if not organizations:
        _source("azure_devops", "This az account is in no organisation")
        return
    _source("azure_devops", "Signed in to az")
    pick = st.radio("Organisation", organizations, key="azure_pick")
    if st.button("Connect Azure DevOps", key="connect_azure_devops", type="primary"):
        connections.save(settings.data_dir, "azure_devops", {"organization": pick})
        st.rerun()


def _sync(settings: Settings, store: Store) -> None:
    st.markdown("**Sync**")
    st.caption(
        "Sync now, in the top bar, fetches only what changed since the last sync. Pipelines "
        "cover the last 90 days."
    )
    rows = [(p, PLATFORM_NAMES[p]) for p in settings.platforms]
    if settings.github_owner:
        rows.append(("github:pipelines", "GitHub pipelines"))
    for key, name in rows:
        state = store.sync_state(key)
        st.markdown(f"{name} :gray[· {relative(state.last_sync)}]")
        done, total = store.history(key)
        if done < total:
            st.caption(
                f"Older history: {done} of {total} repositories read back two years. Each sync "
                "continues where the last one stopped."
            )
        if state.last_error and sync.BUDGET_SPENT in state.last_error:
            st.info(state.last_error, icon=None)
        elif state.last_error:
            st.error(f"Last sync failed: {state.last_error}", icon=None)
    with st.expander("More sync options"):
        st.caption(
            "These start over and read everything again, which on a large organisation takes "
            "several syncs."
        )
        if st.button("Re-read the last two years of PRs", width="stretch"):
            request_sync("full")
            show(False)
            st.rerun()
        confirm = st.checkbox("I want to delete the local data")
        if st.button("Delete local data and resync", disabled=not confirm, width="stretch"):
            request_sync("reset")
            show(False)
            st.rerun()


@st.dialog("Settings", position="right", width="medium", on_dismiss=lambda: show(False))
def drawer(settings: Settings, store: Store | None) -> None:
    st.markdown("**Data sources**")
    st.caption(
        "Connects through your gh and az command-line logins. No token is stored: each sync "
        "asks the CLI for a fresh one."
    )
    for source in (_github, _azure):
        with st.container(border=True):
            source(settings, store)
    if store is not None:
        st.divider()
        _sync(settings, store)
    st.divider()
    st.markdown("**Identity aliases**")
    st.caption(
        "Count one person once when they use different logins on GitHub and Azure DevOps. "
        "Set them in IDENTITY_ALIASES in `.env`."
    )
    for login, to in settings.aliases.items():
        st.markdown(f"`{login}` → `{to}`")
