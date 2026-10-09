//! GraphQL pull request -> `PullRequest`. `testdata/github` and the expected
//! records beside it pin the behaviour, which matches what REST reported.

use std::collections::{BTreeMap, BTreeSet};

use crate::model::{Platform, PullRequest, Repo, State, Timestamp};
use crate::rules::{identity, is_bot, is_infrastructure, is_noise, parse_time};
use crate::source::{People, Responses};

use super::types::{Actor, PrNode, PrState};

/// Login as REST reports it. GraphQL drops the `[bot]` suffix that REST and
/// our bot rules rely on, and gives no author at all for deleted accounts,
/// which REST reports as `ghost`.
fn login(actor: Option<&Actor>) -> String {
    match actor {
        None => "ghost".to_owned(),
        Some(a) if a.typename == "Bot" => format!("{}[bot]", a.login),
        Some(a) => a.login.clone(),
    }
}

fn person(raw: &str, people: &mut People) -> String {
    let ident = identity(Some(raw));
    if !ident.is_empty() {
        people
            .entry(ident.clone())
            .or_insert_with(|| raw.to_owned());
    }
    ident
}

/// Lines added, deleted and files changed, without noise files. A PR with more files than one
/// query carries falls back to GitHub's totals, noise included.
// ponytail: >100 files uses unfiltered totals; page `files` if huge PRs matter.
fn size(node: &PrNode) -> (Option<i64>, Option<i64>, Option<i64>) {
    match &node.files {
        Some(files) if !files.truncated() => {
            let kept = files.nodes.iter().filter(|f| !is_noise(&f.path));
            let (mut added, mut deleted, mut count) = (0, 0, 0);
            for f in kept {
                added += f.additions;
                deleted += f.deletions;
                count += 1;
            }
            (Some(added), Some(deleted), Some(count))
        }
        _ => (node.additions, node.deletions, node.changed_files),
    }
}

#[must_use]
pub fn convert(node: &PrNode, repo: &Repo, complete: bool, people: &mut People) -> PullRequest {
    let author = person(&login(node.author.as_ref()), people);

    let mut approvers = BTreeSet::new();
    let mut rejecters = BTreeSet::new();
    let mut responses = Responses::default();
    for review in &node.reviews.nodes {
        let who = person(&login(review.author.as_ref()), people);
        if is_bot(&who, false) || who == author {
            continue;
        }
        let state = review.state.to_uppercase();
        match state.as_str() {
            "APPROVED" => {
                approvers.insert(who.clone());
            }
            "CHANGES_REQUESTED" => {
                rejecters.insert(who.clone());
            }
            _ => {}
        }
        if state != "PENDING" {
            responses.note(&who, parse_time(review.submitted_at.as_deref()));
        }
    }

    // Inline review comments first, then conversation comments, as REST lists them.
    let thread_comments = node
        .review_threads
        .nodes
        .iter()
        .flat_map(|t| &t.comments.nodes);
    let mut comment_counts = BTreeMap::new();
    for comment in thread_comments.chain(&node.comments.nodes) {
        let who = person(&login(comment.author.as_ref()), people);
        if is_bot(&who, false) {
            continue;
        }
        *comment_counts.entry(who.clone()).or_insert(0) += 1;
        if who != author {
            responses.note(&who, parse_time(Some(&comment.created_at)));
        }
    }

    let mut reviewers: Vec<String> = node
        .review_requests
        .nodes
        .iter()
        .filter_map(|r| r.requested_reviewer.as_ref()?.login.as_deref())
        .map(|l| person(l, people))
        .collect();
    for who in &responses.order {
        if !reviewers.contains(who) {
            reviewers.push(who.clone());
        }
    }
    reviewers.retain(|r| *r != author && !is_bot(r, false));

    let state = match node.state {
        PrState::Merged => State::Merged,
        PrState::Closed if node.merged_at.is_some() => State::Merged,
        PrState::Closed => State::Abandoned,
        PrState::Open => State::Open,
    };
    let (additions, deletions, changed_files) = size(node);

    PullRequest {
        platform: Platform::Github,
        repo_id: repo.id.clone(),
        repository: repo.name.clone(),
        number: node.number,
        title: node.title.clone(),
        author,
        state,
        is_draft: node.is_draft,
        created_at: parse_time(Some(&node.created_at))
            .unwrap_or_else(|| Timestamp::new(chrono::Utc::now())),
        closed_at: parse_time(node.merged_at.as_deref().or(node.closed_at.as_deref())),
        url: node.url.clone(),
        is_infrastructure: is_infrastructure(&node.title),
        additions,
        deletions,
        changed_files,
        updated_at: parse_time(Some(&node.updated_at)),
        reviewers,
        approvers: approvers.into_iter().collect(),
        rejecters: rejecters.into_iter().collect(),
        comment_counts,
        first_responses: responses.times,
        details_complete: complete,
    }
}
