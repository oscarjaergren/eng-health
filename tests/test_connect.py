"""Connecting through the gh and az CLIs: what they list, what is saved, what the app shows."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from eng_health import connections
from eng_health.config import Settings

from .conftest import fake_cli
from .test_app import run

GH = """case "$*" in
  "api user --jq .login") echo oscar ;;
  "api user/orgs --paginate --jq .[].login") printf 'acme\\nwidgets\\n' ;;
  *) exit 1 ;;
esac"""

AZ = """case "$*" in
  *profiles/me*) echo '{"id": "m1"}' ;;
  *memberId=m1*) echo '{"value": [{"accountName": "fabrikam"}, {"accountName": "contoso"}]}' ;;
  *) exit 1 ;;
esac"""


def test_the_clis_list_what_the_signed_in_account_can_see(tmp_path: Path) -> None:
    assert connections.github_accounts() is None  # signed out (conftest's fakes)
    fake_cli(tmp_path / "bin", "gh", GH)
    fake_cli(tmp_path / "bin", "az", AZ)
    assert connections.github_accounts() == [
        ("oscar", "user"),
        ("acme", "org"),
        ("widgets", "org"),
    ]
    assert connections.azure_organizations() == ["contoso", "fabrikam"]


def test_a_saved_connection_configures_the_platform_but_env_wins(tmp_path: Path) -> None:
    connections.save(tmp_path, "github", {"owner": "acme", "type": "org"})
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    assert (settings.platforms, settings.connected) == (["github"], ("github",))

    env = {"DATA_DIR": str(tmp_path), "GITHUB_OWNER": "other", "GITHUB_TOKEN": "t"}
    settings = Settings.from_env(env)
    assert (settings.github_owner, settings.connected) == ("other", ())

    connections.save(tmp_path, "github", None)
    assert connections.load(tmp_path) == {}


def test_connect_in_the_sidebar_saves_the_choice(tmp_path: Path) -> None:
    st.cache_data.clear()  # the panel caches what the CLIs listed
    fake_cli(tmp_path / "bin", "gh", GH)
    at = run("This week")
    at.sidebar.selectbox(key="github_pick").set_value(1).run()
    at.sidebar.button(key="connect_github").click().run()
    assert not at.exception, at.exception
    assert connections.load(tmp_path) == {"github": {"owner": "acme", "type": "org"}}
    # Now live, with a way back.
    assert at.sidebar.button(key="disconnect_github")
