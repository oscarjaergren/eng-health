"""The shared expected outputs must match what the Python processing produces."""

import json

from pr_analytics.models import PullRequest

from .export_goldens import goldens


def test_goldens_are_up_to_date() -> None:
    stale = [
        str(p.name) for p, text in goldens().items() if not p.exists() or p.read_text() != text
    ]
    assert not stale, f"Run `python -m tests.export_goldens`; stale: {stale}"


def test_python_reads_the_shared_json_shape() -> None:
    """The Rust engine writes exactly the golden JSON; the dashboard must load it."""
    for text in goldens().values():
        data = json.loads(text)["pull_request"]
        assert PullRequest.from_dict(data).to_dict() == data
