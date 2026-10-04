"""testdata/expected holds the records prsync writes for the shared fixtures
(checked by the Rust parity tests). The dashboard must load every one."""

import json
from pathlib import Path

from pr_analytics.models import PullRequest

EXPECTED = Path(__file__).parent.parent / "testdata" / "expected"


def test_python_reads_the_shared_json_shape() -> None:
    files = sorted(EXPECTED.glob("*/*.json"))
    assert len(files) >= 10
    for path in files:
        data = json.loads(path.read_text())["pull_request"]
        assert PullRequest.from_dict(data).to_dict() == data, path.name
