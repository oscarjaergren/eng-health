"""Write testdata/expected/ from the Python processing code.

The Rust sync engine must produce identical output from the same inputs. Run
`python -m tests.export_goldens` after changing processing rules on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

from pr_analytics.models import Repo
from pr_analytics.processing import from_azure, from_github

ROOT = Path(__file__).parent.parent / "testdata"
CONVERTERS = {
    "azure": ("azure_devops", from_azure, "*.json"),
    "github": ("github", from_github, "*.rest.json"),
}


def canonical(obj: object) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def goldens() -> dict[Path, str]:
    out = {}
    for folder, (platform, convert, pattern) in CONVERTERS.items():
        for src in sorted((ROOT / folder).glob(pattern)):
            case = json.loads(src.read_text())
            r = case["repo"]
            people: dict[str, str] = {}
            pr = convert(case["pr"], Repo(platform, r["id"], r["name"], r["raw"]), people)
            name = src.name.removesuffix(".json").removesuffix(".rest")
            out[ROOT / "expected" / folder / f"{name}.json"] = canonical(
                {"pull_request": pr.to_dict(), "people": people}
            )
    return out


if __name__ == "__main__":
    for path, text in goldens().items():
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT.parent)}")
