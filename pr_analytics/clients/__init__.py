"""Platform API clients."""

from ..config import Settings
from .azure_devops import AzureDevOpsClient
from .base import ApiError, AuthError, PlatformClient
from .github import GitHubClient


def make_clients(settings: Settings) -> list[PlatformClient]:
    clients: list[PlatformClient] = []
    if settings.azure:
        clients.append(AzureDevOpsClient(settings.azure))
    if settings.github:
        clients.append(GitHubClient(settings.github))
    return clients


__all__ = [
    "ApiError",
    "AuthError",
    "AzureDevOpsClient",
    "GitHubClient",
    "PlatformClient",
    "make_clients",
]
