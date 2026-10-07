import pytest

from eng_health.config import ConfigError, Settings


def test_no_credentials_means_no_platforms() -> None:
    s = Settings.from_env({})
    assert s.platforms == [] and not s.mock
    assert str(s.db_path) == "data/eng_health.db"


def test_both_platforms() -> None:
    s = Settings.from_env(
        {
            "AZURE_DEVOPS_ORGANIZATION": "org",
            "AZURE_DEVOPS_PAT": "pat",
            "GITHUB_OWNER": "me",
            "GITHUB_TOKEN": "tok",
        }
    )
    assert s.platforms == ["azure_devops", "github"]
    assert (s.azure_organization, s.github_owner) == ("org", "me")


@pytest.mark.parametrize(
    "env",
    [
        {"AZURE_DEVOPS_ORGANIZATION": "org"},
        {"GITHUB_TOKEN": "tok"},
        {"IDENTITY_ALIASES": "bob"},
    ],
)
def test_invalid_config_fails_loudly(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_aliases_and_mock() -> None:
    s = Settings.from_env(
        {"IDENTITY_ALIASES": "Bob=Bob@Example.com, eve = eve@example.com", "MOCK_MODE": "true"}
    )
    assert s.aliases == {"bob": "bob@example.com", "eve": "eve@example.com"}
    assert s.mock
