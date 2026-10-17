"""The six views: Today, an inbox of what needs a look, and a page per question it links to."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cached_property, partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pandas as pd
import streamlit as st

from .. import digest, metrics, prefs
from .. import pipelines as pl
from ..digest import Change, Move, Numbers
from ..metrics import SIZE_LABELS
from ..period import Period, between
from . import filters

if TYPE_CHECKING:
    from plotly.graph_objects import Figure

from .charts import (
    AMBER,
    HOT,
    INK,
    LIGHT,
    MID,
    TICKS,
    bars,
    card,
    cell,
    esc,
    fmt,
    grid,
    head,
    html,
    lines,
    linked,
    md,
    spark,
    table,
    table_html,
    trend,
)

VIEWS = {
    "today": "Today",
    "shipping": "Shipping",
    "review": "Review",
    "ci": "CI",
    "cost": "Cost",
    "people": "People",
}
Tone = Literal["red", "orange", "gray"]
# Waiting PRs, most in need of a reviewer first.
_URGENCY = {"No review": 0, "Changes requested": 1, "Commented": 2, "Approved, not merged": 3}
_TONES: dict[str, Tone] = {"No review": "red", "Changes requested": "orange"}
_LARGE = SIZE_LABELS[3:]
_OPENED = "#D3CFC5"  # the second, quieter bar beside an ink one


@dataclass(frozen=True)
class Context:
    """What every view draws from: the filtered PRs and CI jobs, and the period."""

    prs: pd.DataFrame
    names: Mapping[str, str]
    jobs: pd.DataFrame  # as pipelines.prepare returns them; empty without GitHub
    failures: pd.DataFrame
    prices: Mapping[str, float]
    period: Period  # its charts start at the oldest PR
    ci_period: Period  # the same, starting at the oldest CI run
    now: pd.Timestamp
    tz: str
    no_ci: str  # why `jobs` is empty
    has_ci: bool  # whether there are runs at all, before the filters
    # Repository name, and optionally a view other than this one -> that repository's page.
    repo_link: Callable[..., str | None]
    picked: tuple[str, ...]  # repository names picked in the Repository chip, if any
    data_dir: Path  # where choices are remembered, such as what has been handled

    def name(self, person: str) -> str:
        return self.names.get(person, person)

    @property
    def window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.period.window(self.now)

    @property
    def ticks(self) -> tuple[str, str]:
        return ("%a %-d", "%a %b %-d") if self.period.days == 7 else TICKS[self.period.freq]

    @property
    def per(self) -> str:
        return {"D": "per day", "W": "per week", "M": "per month"}[self.period.freq]

    @property
    def last(self) -> str:
        return f"the last {self.period.name}"

    @cached_property
    def pr(self) -> Numbers:
        return digest.numbers(partial(digest.pr_stats, self.prs), self.period, self.now, self.tz)

    @cached_property
    def people(self) -> pd.DataFrame:
        return metrics.people(self.prs, self.period, self.now, self.tz)

    @cached_property
    def sizes(self) -> pd.DataFrame:
        return metrics.by_size(metrics.merged_in(self.prs, *self.window))

    @cached_property
    def att(self) -> pd.DataFrame:
        return pl.attempts(self.jobs)

    @cached_property
    def billed(self) -> pd.DataFrame:
        return pl.billed(self.jobs, self.prices)

    @cached_property
    def ci(self) -> Numbers:
        stats = partial(digest.ci_stats, self.att, self.billed)
        return digest.numbers(stats, self.ci_period, self.now, self.tz)

    @property
    def ci_repo(self) -> str | None:
        """The repository the CI runs are from when there is just one. Workflows and jobs only
        compare within a repository, so the CI views drill into it; with several, they compare
        repositories."""
        repos = self.jobs["repository"].unique()
        return str(repos[0]) if len(repos) == 1 else None

    @cached_property
    def stretches(self) -> pd.DataFrame:
        return pl.broken(self.att, self.now)

    def broken_hours(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        """Hours main was broken in (start, end], summed over the repositories."""
        return float(pl.broken_hours(self.stretches, start, end, self.now).sum())

    @cached_property
    def broken(self) -> pd.DataFrame:
        """Hours main was broken, a row per chart bucket."""
        return self.ci_period.each(
            self.now, self.tz, lambda a, b: {"Broken": self.broken_hours(a, b)}
        )

    @cached_property
    def moves(self) -> list[Move]:
        return (
            [] if self.jobs.empty else digest.movers(self.att, self.billed, self.period, self.now)
        )


def go(view: str) -> None:
    st.session_state["view"] = view


def _link(view: str, label: str, key: str) -> None:
    st.button(f"{label} →", type="tertiary", on_click=go, args=(view,), key=key)


def _change(ratio: float) -> str:
    """A table cell for a change on the period before: red past +10%, green past -10%."""
    if math.isnan(ratio):
        return cell("–", "na")
    kind = "hot" if ratio > 0.1 else "good" if ratio < -0.1 else "n"
    return cell(f"{ratio:+.0%}".replace("-", "−"), kind)


# Below this, a percentage overstates a change: 11 to 3 is "8 fewer", not "down 73%".
_SMALL = 20


def _delta(c: Change) -> tuple[str | None, Literal["green", "red", "gray"]]:
    """The change on the period before, as text, and green when it is good news."""
    if c.now is None:
        return c.empty or None, "gray"
    if c.before is None:
        return None, "gray"
    if c.unit == "%":
        change = c.now - c.before
        text = f"{abs(change):.1f} pt" if round(change, 1) else ""
    elif not c.unit and max(c.now, c.before) < _SMALL:
        change = c.now - c.before
        text = fmt(abs(change)) if round(change, 1) else ""
    elif c.ratio is None:
        return None, "gray"
    else:
        change = c.ratio
        text = f"{abs(change):.0%}" if round(change, 2) else ""
    if not text:
        return "no change", "gray"
    arrow = "↑" if change > 0 else "↓"
    if c.lower_is_better is None:
        return f"{arrow} {text}", "gray"
    return f"{arrow} {text}", "green" if (change < 0) == c.lower_is_better else "red"


def _pr_kpis(c: Context, keys: Sequence[str]) -> list[Change]:
    """The PR numbers for `keys`. One only GitHub reports says so when every PR shown is Azure
    DevOps's, rather than a bare blank."""
    azure_only = not c.prs["platform"].eq("github").any()
    changes = [c.pr.change(k) for k in keys]
    return [
        replace(ch, empty="GitHub only") if azure_only and k in digest.GITHUB_ONLY else ch
        for k, ch in zip(keys, changes, strict=True)
    ]


def _kpis(changes: Sequence[Change], views: Sequence[str] = ()) -> None:
    """One card of numbers. With `views`, clicking a number opens the view behind it."""
    with st.container(horizontal=True, gap=None, key="strip"):
        for i, c in enumerate(changes):
            delta, tone = _delta(c)
            with st.container(gap=None, key=f"cell-{i}"):
                html(
                    f'<div><div class="kpi-label">{esc(c.label)}</div><div class="kpi-row">'
                    f'<span class="kpi-value">{esc(fmt(c.now, c.unit))}</span>'
                    f'<span class="delta tone-{tone}">{esc(delta or "")}</span></div>'
                    f"{spark(c.trend, HOT if tone == 'red' else INK)}</div>"
                )
                if i < len(views):
                    view = views[i]
                    st.button(f"Open {VIEWS[view]}", key=f"go-{i}", on_click=go, args=(view,))


def _where(c: Context) -> None:
    """The repositories the view is narrowed to, with ✕ to go back to the scope."""
    if not c.picked:
        return
    names = c.picked[0] if len(c.picked) == 1 else f"{len(c.picked)} repositories"
    html(f'<div class="crumb">&nbsp;›&nbsp;&nbsp;<b>{esc(names)}</b></div>', "content")
    st.button(
        "✕",
        key="unpick",
        help="Back to all of them",
        type="tertiary",
        on_click=filters.forget,
        args=("repo",),
    )


def _header(c: Context, crumb: str, question: str, answer: str) -> None:
    with st.container(horizontal=True, gap=None, vertical_alignment="center", key="crumbs"):
        st.button("Today", type="tertiary", on_click=go, args=("today",), key="crumb")
        html(f'<div class="crumb">&nbsp;/&nbsp;&nbsp;<b>{esc(crumb)}</b></div>', "content")
        _where(c)
    st.header(question, anchor=False)
    html(f'<div class="answer">{esc(answer)}</div>')


# --- Today ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    key: str  # stable while nothing about it changes, so a handled item stays handled
    title: str
    meta: str
    tag: str
    tone: Tone
    age: str
    url: str = ""


def _day(t: pd.Timestamp, c: Context) -> str:
    local = t.tz_convert(c.tz)
    return local.strftime("%a" if c.now - t < pd.Timedelta(days=6) else "%b %-d")


def _inbox(c: Context) -> list[tuple[str, str, str, list[Item]]]:
    """(title, view, link text, items) for each group. Open PRs go by who they wait on, idlest
    first; stale ones are left out (see `today`)."""
    waiting = metrics.waiting(c.prs, c.now)
    active = waiting[waiting["idle"] < metrics.STALE_DAYS]
    active = active.assign(urgency=active["status"].map(_URGENCY)).sort_values(
        ["urgency", "idle"], ascending=[True, False]
    )

    def prs(*statuses: str) -> list[Item]:
        return [
            Item(
                f"pr {r['url']}",
                r["title"],
                f"{r['repository']} · {c.name(r['author'])}",
                r["status"],
                _TONES.get(r["status"], "gray"),
                f"{r['idle']} d",
                r["url"],
            )
            for r in active[active["status"].isin(statuses)].to_dict("records")
        ]

    groups = [
        ("Waiting on review", "review", "All open PRs", prs("No review", "Commented")),
        ("Waiting on the author", "review", "All open PRs", prs("Changes requested")),
        ("Approved, not merged", "review", "All open PRs", prs("Approved, not merged")),
    ]
    if c.jobs.empty:
        return groups
    # First: a broken main blocks everyone working in that repository.
    failing = pl.failing(c.att).groupby("repository")["pipeline"].agg(", ".join)
    broken = c.stretches[c.stretches["end"].isna()].sort_values("start")
    groups.insert(
        0,
        (
            "Broken main",
            "ci",
            "CI detail",
            [
                Item(
                    f"broken {r['repository']} {r['start']}",
                    f"Main is broken in {r['repository']}",
                    f"{failing.get(r['repository'], 'CI')} failing on the default branch",
                    "Broken",
                    "red",
                    fmt((c.now - r["start"]).total_seconds() / 3600, " h"),
                    c.repo_link(r["repository"], "ci") or "",
                )
                for r in broken.to_dict("records")
            ],
        ),
    )
    this_week = c.period.days == 7
    new = digest.new_flaky_tests(c.failures, c.att, *c.window)
    groups.append(
        (
            "New flaky tests",
            "ci",
            "All flaky jobs",
            [
                Item(
                    f"test {r['repository']} {r['pipeline']} {r['test_id']}",
                    r["test_id"],
                    f"{r['repository']} · {r['pipeline']} · {r['flaky_runs']} flaky "
                    f"{'run' if r['flaky_runs'] == 1 else 'runs'}",
                    "New",
                    "orange",
                    _day(r["first_seen"], c),
                )
                for r in new.to_dict("records")
            ],
        )
    )
    groups.append(
        (
            "Got worse this week" if this_week else f"Got worse in {c.last}",
            "ci",
            "CI detail",
            [
                Item(
                    f"move {m.title} {m.detail}",
                    m.title,
                    m.detail,
                    m.tag,
                    "red" if abs(m.change) >= 0.4 else "orange",
                    f"{m.change:+.0%}".replace("-", "−"),
                )
                for m in c.moves
                if m.worse
            ],
        )
    )
    return groups


def _handled(data_dir: Path) -> dict[str, dict[str, str]]:
    """Items marked handled, by key: their title, and when. Remembered in dashboard.json, so they
    stay handled after a reload, for everyone sharing the data folder."""
    saved = prefs.load(data_dir).get("handled", {})
    return saved if isinstance(saved, dict) else {}


def _handle(data_dir: Path, key: str, title: str) -> None:
    now = pd.Timestamp.now(tz="UTC")
    # A year on, the PR is long closed: no need to keep remembering it.
    kept = {
        k: v
        for k, v in _handled(data_dir).items()
        if pd.Timestamp(v["at"]) > now - pd.Timedelta(days=365)
    }
    prefs.save(data_dir, handled=kept | {key: {"title": title, "at": now.isoformat()}})


def _restore(data_dir: Path, key: str) -> None:
    handled = _handled(data_dir)
    handled.pop(key, None)
    prefs.save(data_dir, handled=handled)


def _row(i: Item, view: str, key: str, data_dir: Path) -> None:
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key=key):
        html(
            f'<div class="item"><span class="dot dot-{i.tone}"></span><div style="min-width:0">'
            f'<div class="item-title">{esc(i.title)}</div>'
            f'<div class="item-meta">{esc(i.meta)}</div></div></div>'
        )
        html(
            f'<div class="item"><span class="tag">{esc(i.tag)}</span>'
            f'<span class="age">{esc(i.age)}</span></div>',
            "content",
        )
        if i.url:
            st.link_button("Open", i.url)
        else:
            st.button("Open", key=f"open {i.key}", on_click=go, args=(view,))
        st.button("✓", key=f"done {i.key}", on_click=_handle, args=(data_dir, i.key, i.title))


def _review_load(c: Context) -> pd.DataFrame:
    top = c.people.nlargest(5, "Reviews")
    return pd.DataFrame(
        {"Reviews given": top["Reviews"].to_numpy(), "PRs opened": top["Opened"].to_numpy()},
        index=[c.name(p) for p in top.index],
    )


def _load_bars(load: pd.DataFrame) -> str:
    """Two thin bars a person: reviews given, then PRs opened."""
    most = max(int(load.to_numpy().max()), 1)
    rows = "".join(
        f'<div class="load"><span class="item-meta" style="color:inherit">{esc(name)}</span>'
        f'<div><i style="width:{100 * given / most:.0f}%;background:{INK}"></i>'
        f'<i style="width:{100 * opened / most:.0f}%;background:{_OPENED}"></i></div>'
        f'<code class="r">{given} / {opened}</code></div>'
        for name, given, opened in load.itertuples()
    )
    legend = "".join(
        f'<span class="legend"><i style="background:{color}"></i>{label}</span>'
        for label, color in (("Reviews given", INK), ("PRs opened", _OPENED))
    )
    return f'<div>{rows}<div style="margin-top:10px">{legend}</div></div>'


def today(c: Context) -> None:
    handled = _handled(c.data_dir)
    groups = [(t, v, a, [i for i in items if i.key not in handled]) for t, v, a, items in _inbox(c)]
    waiting = metrics.waiting(c.prs, c.now)
    stale = int((waiting["idle"] >= metrics.STALE_DAYS).sum())
    count = sum(len(items) for *_, items in groups)
    with st.container(horizontal=True, gap=None, vertical_alignment="center", key="crumbs"):
        html(
            f'<div class="c-m" style="font-size:13px">{c.now.tz_convert(c.tz):%A, %b %-d}</div>',
            "content",
        )
        _where(c)
    st.title(
        f"{count} {'thing needs' if count == 1 else 'things need'} a look"
        if count
        else "Nothing needs a look",
        anchor=False,
    )
    html(
        '<div class="answer" style="color:#6E6C66">Click any number to see what\'s behind it.</div>'
    )
    tiles = [(c.pr.change("wait"), "review"), (c.pr.change("ttm"), "review")]
    tiles.append((c.pr.change("merged"), "shipping"))
    if c.has_ci:
        # Kept, blank, when the filters leave no runs, so the other numbers don't move.
        for key, view in (("failure", "ci"), ("cost", "cost")):
            label, unit, _ = digest.METRICS[key]
            blank = Change(label, None, None, unit)
            tiles.append((blank if c.jobs.empty else c.ci.change(key), view))
    _kpis([change for change, _ in tiles], [view for _, view in tiles])
    st.space("small")

    left, right = st.columns([2, 1], gap="large")
    with left:
        for g, (title, view, action, items) in enumerate(groups):
            if not items:
                continue
            with st.container(horizontal=True, vertical_alignment="center"):
                html(
                    f'<div><b style="font-size:16px">{esc(title)}</b>'
                    f'<span class="count">{len(items)}</span></div>'
                )
                _link(view, action, key=f"all {title}")
            with st.container(gap=None, key=f"group-{g}"):
                for r, item in enumerate(items[:5]):
                    _row(item, view, f"row-{g}-{r}", c.data_dir)
        if stale:
            with st.container(horizontal=True, vertical_alignment="center"):
                html(
                    f'<div class="item-meta">{stale} open {"PR" if stale == 1 else "PRs"} '
                    f"untouched for {metrics.STALE_DAYS} days or more left out: they want "
                    "closing, not reviewing.</div>"
                )
                _link("review", "See them", key="stale")
        if not count:
            html(
                '<div class="empty">Inbox clear. Nothing needs a look until something changes.'
                "</div>"
            )
    with right:
        cleared = "this week" if c.period.days == 7 else f"in {c.last}"
        html(f"<div><b>Cleared {esc(cleared)}</b></div>")
        start, _ = c.window
        recent = {k: v for k, v in handled.items() if pd.Timestamp(v["at"]) > start}
        for key, entry in recent.items():
            st.button(
                f":green[✓] {md(entry['title'])}",
                key=f"restore {key}",
                type="tertiary",
                help="Click to restore",
                on_click=_restore,
                args=(c.data_dir, key),
            )
        better = [m for m in c.moves if not m.worse][:5]
        for m in better:
            html(
                f'<div class="cleared"><span class="tone-green">✓</span>'
                f"<span>{esc(m.title)}: {esc(m.detail)}</span></div>"
            )
        if not recent and not better:
            html('<div class="item-meta">Nothing yet.</div>')
        load = _review_load(c)
        if load["Reviews given"].sum():
            st.divider()
            with st.container(horizontal=True, vertical_alignment="center"):
                html("<div><b>Review load</b></div>")
                _link("review", "Review", key="load review")
            html(f'<div class="item-meta">Reviews given vs. PRs opened, {esc(c.last)}</div>')
            html(_load_bars(load))


# --- The questions -----------------------------------------------------------------------


def _has_prs(c: Context) -> bool:
    if c.prs.empty:
        st.info("No pull requests match these filters.")
    return not c.prs.empty


def _has_ci(c: Context) -> bool:
    if c.jobs.empty:
        st.info(c.no_ci)
    return not c.jobs.empty


def shipping(c: Context) -> None:
    if not _has_prs(c):
        return
    now, before = c.pr.now, c.pr.before
    opened, merged, still_open = now["opened"] or 0, now["merged"] or 0, now["open"] or 0
    queue = "growing" if opened > merged else "shrinking" if opened < merged else "steady"
    _header(
        c,
        "Shipping",
        "Are we shipping?",
        f"{merged:.0f} PRs merged in {c.last} against {opened:.0f} opened, so the open queue is "
        f"{queue}: {still_open:.0f} are open now, and {before['open'] or 0:.0f} were "
        f"{c.period.name} ago.",
    )
    _kpis(_pr_kpis(c, ("merged", "opened", "open", "size")))
    t = c.pr.trend
    unit = {"D": "day", "W": "week", "M": "month"}[c.period.freq]
    charts = [
        (
            "Opened vs merged",
            c.per,
            bars(
                t[["opened", "merged"]].set_axis(["Opened", "Merged"], axis=1),
                [LIGHT, INK],
                ticks=c.ticks,
            ),
        ),
        (
            "Open PRs",
            f"at the end of each {unit}",
            lines(t[["open"]].set_axis(["Open"], axis=1), ticks=c.ticks),
        ),
    ]
    if not c.sizes.empty:
        charts += [
            (
                "PR size",
                "merged PRs by lines changed",
                bars(c.sizes[["PRs"]].reindex(SIZE_LABELS, fill_value=0)),
            ),
            (
                "Time to merge by size",
                "median",
                bars(
                    c.sizes[["Median to merge (h)"]].set_axis(["Median to merge"], axis=1),
                    highlight=_LARGE,
                    unit=" h",
                ),
            ),
        ]
    grid(charts)

    slow = c.pr.now["ttm_p75"] or float("inf")  # slower than three in four PRs: worth a look
    rows = []
    for repo, r in metrics.repositories(c.prs, c.period, c.now, c.tz).iterrows():
        hot = r["Median to merge (h)"] > slow
        rows.append(
            [
                linked(str(repo), c.repo_link(str(repo))),
                cell(r["Merged"], "n"),
                cell(r["Opened"], "n"),
                cell(r["Open now"], "n"),
                cell(fmt(r["Median to merge (h)"], " h"), "hot" if hot else "n"),
                trend(r["Trend"], HOT if hot else MID),
            ]
        )
    table(
        "By repository",
        c.last,
        ["Repository", "Merged", "Opened", "Open now", "Median to merge", "Trend"],
        "minmax(0,1.6fr) 80px 80px 80px 120px 96px",
        rows,
        right={1, 2, 3, 4, 5},
    )


def review(c: Context) -> None:
    if not _has_prs(c):
        return
    now = c.pr.now
    answer = (
        f"The first review arrives in {fmt(now['wait'], ' h')} at the median, and merging "
        f"takes {fmt(now['ttm'], ' h')}."
        if now["wait"] is not None and now["ttm"] is not None
        else f"Too few reviews and merges in {c.last} for a median."
    )
    depth = c.sizes.loc[c.sizes.index.isin(_LARGE), "Comments per 100 lines"]
    if len(depth) and (depth < 1).all():
        answer += " PRs over 400 lines get under one comment per 100 lines: skimmed, not read."
    load = _review_load(c)
    total = c.people["Reviews"].sum()
    if total >= 10 and len(load) >= 2:
        share = load["Reviews given"].iloc[:2].sum() / total
        answer += f" {load.index[0]} and {load.index[1]} gave {share:.0%} of all reviews."
    _header(c, "Review", "Is review the bottleneck?", answer)
    _kpis(_pr_kpis(c, ("wait", "ttm", "depth", "unreviewed")))

    t = c.pr.trend
    charts = [
        (
            "Wait for first review",
            c.per,
            lines(
                t[["wait_p75", "wait"]].set_axis(["p75", "Median"], axis=1),
                [LIGHT, INK],
                dashed=["p75"],
                unit=" h",
                ticks=c.ticks,
            ),
        ),
        (
            "Time to merge",
            c.per,
            lines(
                t[["ttm_p75", "ttm"]].set_axis(["p75", "Median"], axis=1),
                [LIGHT, HOT],
                dashed=["p75"],
                unit=" h",
                ticks=c.ticks,
            ),
        ),
    ]
    if not c.sizes.empty:
        depth_chart = bars(c.sizes[["Comments per 100 lines"]], highlight=_LARGE)
        charts.append(("Review depth by size", "comments per 100 changed lines", depth_chart))
    if load["Reviews given"].sum():
        charts.append(
            ("Review load", "reviews given vs PRs opened, top 5", bars(load, [INK, LIGHT]))
        )
    grid(charts)

    rows = [
        [
            cell(r["title"]),
            linked(r["repository"], c.repo_link(r["repository"]), "m"),
            cell(c.name(r["author"]), "m"),
            cell(r["status"], "hot-tag" if r["status"] == "No review" else "tag"),
            cell(f"{r['age']} d", "hot" if r["status"] == "No review" else "n"),
            cell(f"{r['idle']} d", "na" if r["idle"] >= metrics.STALE_DAYS else "n"),
            cell(r["url"], "link"),
        ]
        for r in metrics.waiting(c.prs, c.now).to_dict("records")
    ]
    table(
        "Open PRs waiting",
        "open 2 days or more, oldest first. Idle: since anything last happened on it.",
        ["Pull request", "Repository", "Author", "State", "Open", "Idle", ""],
        "minmax(0,2fr) 140px 140px 160px 64px 64px 48px",
        rows,
        right={4, 5},
    )
    merged = metrics.merged_in(c.prs, *c.window)
    unreviewed = merged[~metrics.reviewed(merged)].sort_values("closed_at", ascending=False)
    if len(unreviewed):
        table(
            "Merged without review",
            f"{c.last}: no approval, and no one but the author commented",
            ["Pull request", "Repository", "Author", "Merged", ""],
            "minmax(0,2fr) 140px 140px 80px 48px",
            [
                [
                    cell(r["title"]),
                    linked(r["repository"], c.repo_link(r["repository"]), "m"),
                    cell(c.name(r["author"]), "m"),
                    cell(_day(r["closed_at"], c), "n"),
                    cell(r["url"], "link"),
                ]
                for r in unreviewed.to_dict("records")
            ],
            right={3},
        )


def _flaky_rows(c: Context) -> list[list[str]]:
    """Flaky jobs, each workflow's flaky tests under its jobs. New: first flaky in the period."""
    start, end = c.window
    att = c.att[between(c.att["started"], start, end)]
    jobs = pl.flaky_jobs(c.jobs[between(c.jobs["started_at"], start, end)])
    first = pl.flaky_jobs(c.jobs).set_index(["repository", "pipeline", "name"])["first_seen"]
    tests = pl.flaky_tests(c.failures, att) if len(c.failures) else pd.DataFrame()
    first_test = (
        pl.flaky_tests(c.failures, c.att).set_index(["repository", "pipeline", "test_id"])
        if len(tests)
        else pd.DataFrame()
    )

    def status(since: pd.Timestamp) -> str:
        new = since > start
        return cell("New" if new else "Open", "hot-tag" if new else "tag")

    rows = []
    workflows = pd.concat([jobs[["repository", "pipeline"]], tests.get(["repository", "pipeline"])])
    for repo, pipeline in workflows.drop_duplicates().itertuples(index=False):
        mine = jobs[(jobs["repository"] == repo) & (jobs["pipeline"] == pipeline)]
        for j in mine.to_dict("records"):
            since = first[(repo, pipeline, j["name"])]
            rows.append(
                [
                    cell(j["name"]),
                    cell(pipeline, "m"),
                    linked(repo, c.repo_link(repo), "m"),
                    cell(j["flaky_runs"], "hot" if j["flaky_runs"] >= 5 else "n"),
                    cell(f"{since.tz_convert(c.tz):%b %-d}", "n"),
                    status(since),
                ]
            )
        if tests.empty:
            continue
        for t in tests[(tests["repository"] == repo) & (tests["pipeline"] == pipeline)].to_dict(
            "records"
        ):
            since = first_test.loc[(repo, pipeline, t["test_id"]), "first_seen"]
            rows.append(
                [
                    cell(t["test_id"], "sub" if len(mine) else "t"),
                    cell("" if len(mine) else pipeline, "m"),
                    cell("" if len(mine) else repo, "m"),
                    cell(t["flaky_runs"], "n"),
                    cell(f"{since.tz_convert(c.tz):%b %-d}", "n"),
                    status(since),
                ]
            )
    return rows


def _broken_change(c: Context) -> Change:
    return Change(
        "Time main was broken",
        c.broken_hours(*c.window),
        c.broken_hours(*c.period.window(c.now, back=1)),
        " h",
        True,
        tuple(c.broken["Broken"]),
    )


def _ci_charts(c: Context) -> list[tuple[str, str, Figure]]:
    """The charts that add up across repositories."""
    t = c.ci.trend
    outcomes = t[["passed", "passed_on_rerun", "failed"]].set_axis(
        ["Passed", "Passed on a rerun", "Failed"], axis=1
    )
    return [
        (
            "Time main was broken",
            f"default branch, {c.per}",
            bars(c.broken, [HOT], unit=" h", ticks=c.ticks),
        ),
        (
            "Runs by outcome",
            f"all workflows, {c.per}",
            bars(outcomes, [INK, AMBER, HOT], stack=True, ticks=c.ticks),
        ),
        (
            "Time lost to reruns",
            f"runner time, {c.per}",
            bars(t[["rerun_hours"]].set_axis(["Lost"], axis=1), unit=" h", ticks=c.ticks),
        ),
    ]


def ci(c: Context) -> None:
    if not _has_ci(c):
        return
    if c.ci_repo is None:
        _ci_repositories(c)
    else:
        _ci_repository(c, c.ci_repo)
    table(
        "Flaky jobs",
        "A job failed, then passed on a re-run. Tests below it failed, then passed on the same "
        "commit.",
        ["Job / test", "Workflow", "Repository", "Flaky runs", "First seen", "Status"],
        "minmax(0,2.4fr) 100px 130px 84px 84px 100px",
        _flaky_rows(c),
        right={3, 4},
        count=int(c.ci.now["flaky"] or 0),  # jobs, as the number above says, not their tests too
    )
    if c.failures.empty:
        st.caption(
            "No test results found, so flaky tests can't be shown. eng-health reads JUnit or TRX "
            "files from artifacts whose name contains test, junit, trx or result. For example, "
            "after `dotnet test --logger trx`: `uses: actions/upload-artifact@v4` with `name: "
            "test-results`, `path: '**/*.trx'` and `if: always()`."
        )


def _ci_repositories(c: Context) -> None:
    """Several repositories: one row each, since their workflows don't compare."""
    failure = c.ci.change("failure")
    broken_now = c.stretches[c.stretches["end"].isna()]
    n = c.jobs["repository"].nunique()
    answer = (
        f"{len(broken_now)} of {n} repositories {'has' if len(broken_now) == 1 else 'have'} a "
        "broken main right now."
        if len(broken_now)
        else "Main is green in every repository."
    )
    if failure.now is not None:
        answer += f" Default-branch runs failed {failure.now:.1f}% of the time in {c.last}."
    _header(c, "CI", "Is CI slowing us down?", answer)
    _kpis(
        [
            failure,
            Change("Broken main now", float(len(broken_now)), None),
            _broken_change(c),
            c.ci.change("rerun_hours"),
            c.ci.change("flaky"),
        ]
    )
    grid(_ci_charts(c))

    rows = []
    for repo, r in pl.repositories(c.att, c.jobs, c.stretches, c.ci_period, c.now, c.tz).iterrows():
        since = r["Broken since"]
        broken = pd.notna(since)
        rows.append(
            [
                linked(str(repo), c.repo_link(str(repo))),
                cell(f"{r['Runs']:,.0f}", "n"),
                cell(fmt(r["Failure rate"], "%"), "n"),
                cell(fmt(r["Broken (h)"], " h"), "hot") if r["Broken (h)"] else cell("–", "na"),
                cell(f"since {since.tz_convert(c.tz):%b %-d}", "hot-tag")
                if broken
                else cell("–", "na"),
                cell(fmt(r["Lost to reruns (h)"], " h"), "n")
                if r["Lost to reruns (h)"]
                else cell("–", "na"),
                cell(f"{r['Flaky jobs']:.0f}", "n"),
                trend(r["Trend"], HOT if broken else MID),
            ]
        )
    table(
        "By repository",
        f"{c.last}, broken first. Open one for its workflows and jobs.",
        [
            "Repository",
            "Runs",
            "Failure rate",
            "Broken",
            "Main now",
            "Lost to reruns",
            "Flaky",
            "Broken trend",
        ],
        "minmax(0,1.6fr) 70px 100px 90px 110px 120px 70px 110px",
        rows,
        right={1, 2, 3, 5, 6, 7},
    )


def _ci_repository(c: Context, repo: str) -> None:
    """One repository: its workflows and jobs side by side."""
    start, end = c.window
    slow = pl.durations(c.att[between(c.att["started"], start, end)])
    before = pl.durations(c.att[between(c.att["started"], *c.period.window(c.now, back=1))])
    failure = c.ci.change("failure")
    broken = _broken_change(c)
    since = c.stretches.loc[c.stretches["end"].isna(), "start"]

    answer = (
        f"In {repo}, main was broken for {fmt(broken.now, ' h')} in {c.last}"
        if broken.now
        else f"In {repo}, main wasn't broken in {c.last}"
    )
    answer += (
        f", and has been since {since.iloc[0].tz_convert(c.tz):%b %-d}." if len(since) else "."
    )
    if failure.now is not None:
        answer += f" Default-branch runs failed {failure.now:.1f}% of the time."
    kpis = [failure, broken]
    charts = [
        (
            "Failure rate by workflow",
            "default branch, % of runs",
            lines(pl.failure_rate(c.att, c.ci_period, c.now, c.tz), unit="%", ticks=c.ticks),
        )
    ]
    if not slow.empty:
        top = str(slow.index[0])
        median = float(slow["Median (min)"].iloc[0])
        times = pl.run_times(c.att, top, c.ci_period, c.now, c.tz)
        was = before["Median (min)"].get(top)
        kpis.append(
            Change(f"{top} median run", median, was, " min", True, tuple(times["Median"].dropna()))
        )
        answer += f" {top} is the slowest workflow, at {fmt(median, ' min')} median."
        charts.append(
            (
                f"{top} run time",
                c.per,
                lines(
                    times[["p90", "Median"]],
                    [LIGHT, HOT],
                    dashed=["p90"],
                    unit=" min",
                    ticks=c.ticks,
                ),
            )
        )
    kpis += [c.ci.change("rerun_hours"), c.ci.change("flaky")]
    _header(c, "CI", "Is CI slowing us down?", answer)
    _kpis(kpis)
    grid(charts + _ci_charts(c))

    rows = []
    slowest = pl.slowest_jobs(c.jobs, c.ci_period, c.now, c.tz).head(10).reset_index()
    for r in slowest.to_dict("records"):
        worse = r["Change"] > 0.1
        rows.append(
            [
                cell(r["name"]),
                cell(r["pipeline"], "m"),
                cell(fmt(r["Median (min)"], " min"), "n"),
                cell(fmt(r["90th pct (min)"], " min"), "n"),
                _change(r["Change"]),
                trend(r["Trend"], HOT if worse else MID),
            ]
        )
    table(
        "Slowest jobs",
        f"successful runs, {c.last}",
        ["Job", "Workflow", "Median", "p90", "Change", "Trend"],
        "minmax(0,2fr) 120px 80px 80px 80px 96px",
        rows,
        right={2, 3, 4, 5},
    )


def cost(c: Context) -> None:
    if not _has_ci(c):
        return
    spent = c.ci.change("cost")
    minutes, reruns = c.ci.now["minutes"] or 0, c.ci.now["rerun_cost"]
    change = (
        f" ({abs(spent.ratio):.0%} {'more' if spent.ratio > 0 else 'less'} than the "
        f"{c.period.name} before)"
        if spent.ratio
        else ""
    )
    repo = c.ci_repo
    _header(
        c,
        "Cost",
        "What's it costing?",
        f"{f'{repo}: ' if repo else ''}"
        f"{fmt(spent.now, '$')} in {c.last}{change}, across {minutes:,.0f} CI minutes. "
        f"Reruns cost {fmt(reruns, '$')} of it. Estimated at list price, before any minutes "
        "your plan includes.",
    )
    yearly = (spent.now or 0) / c.period.days * 365
    _kpis(
        [
            c.ci.change("minutes"),
            spent,
            c.ci.change("rerun_cost"),
            Change("Yearly, at this pace", yearly, None, "$", None),
        ]
    )
    # One repository: its workflows. Several: the repositories, whose workflows don't compare.
    by, label = ("pipeline", "workflow") if repo else ("repository", "repository")
    spend = pl.cost_by(c.billed, by, c.ci_period, c.now, c.tz)
    costs = spend[["Est. cost ($)"]].sort_values("Est. cost ($)", ascending=False)
    minutes_chart = (
        (
            "Minutes by workflow",
            c.per,
            bars(
                pl.minutes_by_pipeline(c.billed, c.ci_period, c.now, c.tz),
                stack=True,
                ticks=c.ticks,
            ),
        )
        if repo
        else (
            "CI minutes",
            c.per,
            bars(c.ci.trend[["minutes"]].set_axis(["Minutes"], axis=1), ticks=c.ticks),
        )
    )
    grid(
        [
            minutes_chart,
            (
                f"Cost by {label}",
                f"US dollars, {c.last}",
                bars(
                    costs.set_axis(["Est. cost"], axis=1),
                    highlight=list(costs.index[:1]),
                    unit="$",
                ),
            ),
        ]
    )
    rows = [
        [
            cell(str(name)) if repo else linked(str(name), c.repo_link(str(name))),
            cell(f"{r['Minutes']:,.0f}", "n"),
            cell(fmt(r["Est. cost ($)"], "$"), "n"),
            cell(f"{r['Share']:.0%}", "n"),
            _change(r["Change"]),
            trend(r["Trend"], HOT if r["Change"] > 0.1 else MID),
        ]
        for name, r in spend.iterrows()
    ]
    table(
        f"By {label}",
        c.last,
        [label.capitalize(), "Minutes", "Est. cost", "Share of minutes", "Change", "Trend"],
        "minmax(0,1.6fr) 100px 100px 120px 90px 96px",
        rows,
        right={1, 2, 3, 4, 5},
    )


_SORTS = {
    "Merged": "Merged",
    "Opened": "Opened",
    "Reviews": "Reviews",
    "Lines": "Lines added",
    "Time to merge": "Median to merge (h)",
}


def _signed(n: float) -> str:
    return f"{n:+,.0f}".replace("-", "−")


def people(c: Context) -> None:
    if not _has_prs(c):
        return
    p = c.people
    answer = f"{c.pr.now['authors'] or 0:.0f} people opened or merged PRs in {c.last}."
    for column, did in (("Merged", "merged"), ("Reviews", "reviewed")):
        most = p[column].max()
        leaders = p.index[p[column] == most]
        # Only one person can have done the most: on a tie, nobody is named.
        if most and len(leaders) == 1:
            answer += f" {c.name(str(leaders[0]))} {did} the most ({most})."
    _header(c, "People", "Who's doing what?", answer)
    _kpis(_pr_kpis(c, ("authors", "per_person", "added", "deleted")))
    # Reviewers who opened nothing would only be an empty slot in a chart of PRs.
    top8 = p[p["Merged"] + p["Opened"] > 0].nlargest(8, "Merged").rename(index=c.name)
    lines_written = top8[["Lines added", "Lines deleted"]].dropna(how="all")
    charts = [("PRs merged", f"top 8, {c.last}", bars(top8[["Merged", "Opened"]], [INK, LIGHT]))]
    if not lines_written.empty:
        charts.append(("Lines added vs deleted", "same people", bars(lines_written, [INK, HOT])))
    grid(charts)

    slow = c.pr.now["ttm_p75"] or float("inf")
    with card("Everyone"):
        with st.container(horizontal=True, vertical_alignment="center"):
            html(head("Everyone", count=len(p), note="Lines are GitHub only."))
            by = st.segmented_control(
                "Sort by",
                list(_SORTS),
                default="Merged",
                required=True,
                key="people_sort",
                label_visibility="collapsed",
            )
        ordered = p.sort_values(_SORTS[by], ascending=False, na_position="last")
        rows = []
        for person, r in ordered.iterrows():
            lines_cells = (
                [cell("not reported", "na")] * 2 + [cell("–", "na")]
                if pd.isna(r["Lines added"])
                else [
                    cell(_signed(r["Lines added"]), "good"),
                    cell(_signed(-r["Lines deleted"]), "n"),
                    cell(_signed(r["Net"]), "good" if r["Net"] < 0 else "n"),
                ]
            )
            hot = r["Median to merge (h)"] > slow
            rows.append(
                [
                    cell(c.name(str(person))),
                    cell(r["Opened"], "n"),
                    cell(r["Merged"], "n"),
                    cell(r["Reviews"], "n"),
                    *lines_cells,
                    cell(fmt(r["Median to merge (h)"], " h"), "hot" if hot else "n"),
                    trend(r["Trend"]),
                ]
            )
        columns = ["Person", "Opened", "Merged", "Reviews", "Lines added", "Lines deleted"]
        html(
            table_html(
                [*columns, "Net", "Median to merge", "Trend"],
                "minmax(150px,1.4fr) 70px 70px 70px 96px 104px 80px 120px 96px",
                rows,
                right=set(range(1, 9)),
            )
        )


RENDER = {
    "today": today,
    "shipping": shipping,
    "review": review,
    "ci": ci,
    "cost": cost,
    "people": people,
}
