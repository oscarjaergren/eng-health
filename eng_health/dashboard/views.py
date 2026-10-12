"""The six views: Today, an inbox of what needs a look, and a page per question it links to."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property, partial
from typing import Literal

import pandas as pd
import streamlit as st

from .. import digest, metrics
from .. import pipelines as pl
from ..digest import Change, Move, Numbers
from ..metrics import SIZE_LABELS
from ..period import Period, between
from . import filters
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
    period: Period
    now: pd.Timestamp
    tz: str
    no_ci: str  # why `jobs` is empty
    has_ci: bool  # whether there are runs at all, before the filters
    repo_link: Callable[[str], str | None]  # repository name -> its page
    picked: tuple[str, ...]  # repository names picked in the Repository chip, if any

    def name(self, person: str) -> str:
        return self.names.get(person, person)

    @property
    def window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.period.window(self.now)

    @property
    def ticks(self) -> str:
        return "%a %-d" if self.period.days == 7 else TICKS[self.period.freq]

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
        return digest.numbers(stats, self.period, self.now, self.tz)

    @cached_property
    def moves(self) -> list[Move]:
        return (
            [] if self.jobs.empty else digest.movers(self.att, self.billed, self.period, self.now)
        )


def go(view: str) -> None:
    st.session_state["view"] = view


def _link(view: str, label: str, key: str) -> None:
    st.button(f"{label} →", type="tertiary", on_click=go, args=(view,), key=key)


def _value(v: float | None, unit: str) -> str:
    if v is None:
        return "–"
    if unit == "$":
        return f"${v:,.2f}"
    if unit == "%":
        return f"{v:.1f}%"
    return f"{v:,.1f}{unit}" if v % 1 else f"{v:,.0f}{unit}"


def _hours(v: float) -> str:
    return "–" if pd.isna(v) else f"{v:.1f} h"


def _change(ratio: float) -> str:
    """A table cell for a change on the period before: red past +10%, green past -10%."""
    if math.isnan(ratio):
        return cell("–", "na")
    kind = "hot" if ratio > 0.1 else "good" if ratio < -0.1 else "n"
    return cell(f"{ratio:+.0%}".replace("-", "−"), kind)


def _delta(c: Change) -> tuple[str | None, Literal["green", "red", "gray"]]:
    """The change on the period before, as text, and green when it is good news."""
    if c.now is None or c.before is None:
        return None, "gray"
    if c.unit == "%":
        change = c.now - c.before
        text = f"{abs(change):.1f} pt" if round(change, 1) else ""
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


def _kpis(changes: Sequence[Change], views: Sequence[str] = ()) -> None:
    """One card of numbers. With `views`, clicking a number opens the view behind it."""
    with st.container(horizontal=True, gap=None, key="strip"):
        for i, c in enumerate(changes):
            delta, tone = _delta(c)
            with st.container(gap=None, key=f"cell-{i}"):
                html(
                    f'<div><div class="kpi-label">{esc(c.label)}</div><div class="kpi-row">'
                    f'<span class="kpi-value">{esc(_value(c.now, c.unit))}</span>'
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
    """(title, view, link text, items) for each group."""
    waiting = metrics.waiting(c.prs, c.now)
    waiting = waiting.assign(urgency=waiting["status"].map(_URGENCY)).sort_values(
        ["urgency", "age"], ascending=[True, False]
    )
    groups = [
        (
            "Waiting on review",
            "review",
            "All open PRs",
            [
                Item(
                    f"pr {r['url']}",
                    r["title"],
                    f"{r['repository']} · {c.name(r['author'])}",
                    r["status"],
                    _TONES.get(r["status"], "gray"),
                    f"{r['age']} d",
                    r["url"],
                )
                for r in waiting.to_dict("records")
            ],
        )
    ]
    if c.jobs.empty:
        return groups
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
                    f"{r['repository']} · {r['pipeline']} · {r['flaky_runs']} flaky runs",
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
                    f"{m.change:+.0%}",
                )
                for m in c.moves
                if m.worse
            ],
        )
    )
    return groups


def _handle(key: str, title: str) -> None:
    st.session_state["handled"][key] = title


def _restore(key: str) -> None:
    st.session_state["handled"].pop(key, None)


def _row(i: Item, view: str, key: str) -> None:
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
        st.button("✓", key=f"done {i.key}", on_click=_handle, args=(i.key, i.title))


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
    handled: dict[str, str] = st.session_state.setdefault("handled", {})
    groups = [(t, v, a, [i for i in items if i.key not in handled]) for t, v, a, items in _inbox(c)]
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
                    _row(item, view, f"row-{g}-{r}")
        if not count:
            html(
                '<div class="empty">Inbox clear. Nothing needs a look until something changes.'
                "</div>"
            )
    with right:
        cleared = "this week" if c.period.days == 7 else f"in {c.last}"
        html(f"<div><b>Cleared {esc(cleared)}</b></div>")
        for key, title in handled.items():
            st.button(
                f":green[✓] {md(title)}",
                key=f"restore {key}",
                type="tertiary",
                help="Click to restore",
                on_click=_restore,
                args=(key,),
            )
        better = [m for m in c.moves if not m.worse][:5]
        for m in better:
            html(
                f'<div class="cleared"><span class="tone-green">✓</span>'
                f"<span>{esc(m.title)}: {esc(m.detail)}</span></div>"
            )
        if not handled and not better:
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
    _kpis([c.pr.change(k) for k in ("merged", "opened", "open", "size")])
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
        ("Open PRs", f"at the end of each {unit}", lines(t[["open"]], ticks=c.ticks)),
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
                "median hours",
                bars(c.sizes[["Median to merge (h)"]], highlight=_LARGE, suffix="h"),
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
                cell(_hours(r["Median to merge (h)"]), "hot" if hot else "n"),
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
        f"The first review arrives in {_value(now['wait'], ' h')} at the median, and merging "
        f"takes {_value(now['ttm'], ' h')}."
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
    _kpis([c.pr.change(k) for k in ("wait", "ttm", "depth", "unreviewed")])

    t = c.pr.trend
    charts = [
        (
            "Wait for first review",
            f"hours, {c.per}",
            lines(
                t[["wait_p75", "wait"]].set_axis(["p75", "Median"], axis=1),
                [LIGHT, INK],
                dashed=["p75"],
                suffix="h",
                ticks=c.ticks,
            ),
        ),
        (
            "Time to merge",
            f"hours, {c.per}",
            lines(
                t[["ttm_p75", "ttm"]].set_axis(["p75", "Median"], axis=1),
                [LIGHT, HOT],
                dashed=["p75"],
                suffix="h",
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
            cell(r["url"], "link"),
        ]
        for r in metrics.waiting(c.prs, c.now).to_dict("records")
    ]
    table(
        "Open PRs waiting",
        "open 2 days or more, oldest first",
        ["Pull request", "Repository", "Author", "State", "Age", ""],
        "minmax(0,2fr) 140px 140px 160px 64px 48px",
        rows,
        right={4},
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


def ci(c: Context) -> None:
    if not _has_ci(c):
        return
    start, end = c.window
    slow = pl.durations(c.att[between(c.att["started"], start, end)])
    before = pl.durations(c.att[between(c.att["started"], *c.period.window(c.now, back=1))])
    failure = c.ci.change("failure")

    answer = (
        f"Default-branch runs failed {failure.now:.1f}% of the time in {c.last}."
        if failure.now is not None
        else f"No runs finished on the default branch in {c.last}."
    )
    kpis = [failure]
    charts = [
        (
            "Failure rate by workflow",
            "default branch, % of runs",
            lines(pl.failure_rate(c.att, c.period, c.now, c.tz), suffix="%", ticks=c.ticks),
        )
    ]
    if not slow.empty:
        top = str(slow.index[0])
        median = float(slow["Median (min)"].iloc[0])
        times = pl.run_times(c.att, top, c.period, c.now, c.tz)
        was = before["Median (min)"].get(top)
        kpis.append(
            Change(f"{top} median run", median, was, " min", True, tuple(times["Median"].dropna()))
        )
        answer += f" {top} is the slowest workflow, at {median:.1f} min median."
        charts.append(
            (
                f"{top} run time",
                "minutes",
                lines(
                    times[["p90", "Median"]],
                    [LIGHT, HOT],
                    dashed=["p90"],
                    suffix="m",
                    ticks=c.ticks,
                ),
            )
        )
    kpis += [c.ci.change("rerun_hours"), c.ci.change("flaky")]
    _header(c, "CI", "Is CI slowing us down?", answer)
    _kpis(kpis)

    t = c.ci.trend
    outcomes = t[["passed", "passed_on_rerun", "failed"]].set_axis(
        ["Passed", "Passed on a rerun", "Failed"], axis=1
    )
    charts += [
        (
            "Runs by outcome",
            f"all workflows, {c.per}",
            bars(outcomes, [INK, AMBER, HOT], stack=True, ticks=c.ticks),
        ),
        (
            "Time lost to reruns",
            f"runner hours, {c.per}",
            bars(t[["rerun_hours"]], suffix="h", ticks=c.ticks),
        ),
    ]
    grid(charts)

    rows = []
    slowest = pl.slowest_jobs(c.jobs, c.period, c.now, c.tz).head(10).reset_index()
    for r in slowest.to_dict("records"):
        worse = r["Change"] > 0.1
        rows.append(
            [
                cell(r["name"]),
                cell(r["pipeline"], "m"),
                cell(f"{r['Median (min)']:.1f}", "n"),
                cell(f"{r['90th pct (min)']:.1f}", "n"),
                _change(r["Change"]),
                trend(r["Trend"], HOT if worse else MID),
            ]
        )
    table(
        "Slowest jobs",
        f"minutes, successful runs, {c.last}",
        ["Job", "Workflow", "Median", "p90", "Change", "Trend"],
        "minmax(0,2fr) 120px 80px 80px 80px 96px",
        rows,
        right={2, 3, 4, 5},
    )
    table(
        "Flaky jobs",
        "A job failed, then passed on a re-run. Tests below it failed, then passed on the same "
        "commit.",
        ["Job / test", "Workflow", "Repository", "Flaky runs", "First seen", "Status"],
        "minmax(0,2.4fr) 100px 130px 84px 84px 100px",
        _flaky_rows(c),
        right={3, 4},
    )
    if c.failures.empty:
        st.caption(
            "No test results found, so flaky tests can't be shown. eng-health reads JUnit or TRX "
            "files from artifacts whose name contains test, junit, trx or result. For example, "
            "after `dotnet test --logger trx`: `uses: actions/upload-artifact@v4` with `name: "
            "test-results`, `path: '**/*.trx'` and `if: always()`."
        )


def cost(c: Context) -> None:
    if not _has_ci(c):
        return
    spent = c.ci.change("cost")
    minutes, reruns = c.ci.now["minutes"] or 0, c.ci.now["rerun_cost"]
    change = (
        f" ({spent.ratio:+.0%} on the {c.period.name} before)" if spent.ratio is not None else ""
    )
    _header(
        c,
        "Cost",
        "What's it costing?",
        f"{_value(spent.now, '$')} in {c.last}{change}, across {minutes:,.0f} CI minutes. "
        f"Reruns cost {_value(reruns, '$')} of it. Estimated at list price, before any minutes "
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
    repos = pl.cost_by_repository(c.billed, c.period, c.now, c.tz)
    costs = repos[["Est. cost ($)"]].sort_values("Est. cost ($)", ascending=False)
    grid(
        [
            (
                "Minutes by workflow",
                c.per,
                bars(
                    pl.minutes_by_pipeline(c.billed, c.period, c.now, c.tz),
                    stack=True,
                    ticks=c.ticks,
                ),
            ),
            (
                "Cost by repository",
                f"US dollars, {c.last}",
                bars(costs, highlight=list(costs.index[:1])),
            ),
        ]
    )
    rows = [
        [
            linked(str(repo), c.repo_link(str(repo))),
            cell(f"{r['Minutes']:,.0f}", "n"),
            cell(_value(r["Est. cost ($)"], "$"), "n"),
            cell(f"{r['Share']:.0%}", "n"),
            _change(r["Change"]),
            trend(r["Trend"], HOT if r["Change"] > 0.1 else MID),
        ]
        for repo, r in repos.iterrows()
    ]
    table(
        "By repository",
        c.last,
        ["Repository", "Minutes", "Est. cost", "Share of minutes", "Change", "Trend"],
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
        if p[column].sum():
            top = str(p[column].idxmax())
            answer += f" {c.name(top)} {did} the most ({p.loc[top, column]})."
    _header(c, "People", "Who's doing what?", answer)
    _kpis([c.pr.change(k) for k in ("authors", "per_person", "added", "deleted")])
    top8 = p.nlargest(8, "Merged").rename(index=c.name)
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
                    cell(_hours(r["Median to merge (h)"]), "hot" if hot else "n"),
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
