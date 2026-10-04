//! Azure DevOps pull request -> `PullRequest`. `testdata/azure` and the expected
//! records beside it pin the behaviour.

use std::collections::{BTreeMap, BTreeSet};

use crate::model::{Platform, PullRequest, Repo, State, Timestamp};
use crate::rules::{identity, is_bot, is_infrastructure, parse_time};
use crate::source::{People, Responses};

use super::types::{IdentityRef, PullRequestInfo, Thread};

pub(super) fn state(status: &str) -> State {
    match status {
        "completed" => State::Merged,
        "abandoned" => State::Abandoned,
        _ => State::Open,
    }
}

fn person(r: &IdentityRef, people: &mut People) -> String {
    let ident = identity(r.unique_name.as_deref());
    if let (false, Some(name)) = (
        ident.is_empty(),
        r.display_name.as_ref().filter(|n| !n.is_empty()),
    ) {
        people.entry(ident.clone()).or_insert_with(|| name.clone());
    }
    ident
}

/// Vote updates are system threads; the voter is looked up in the thread's
/// identity table, falling back to the system comment's author.
fn voter(thread: &Thread, people: &mut People) -> String {
    let ref_id = thread.property("CodeReviewVotedByIdentity");
    let found = thread
        .identities
        .get(&ref_id)
        .filter(|v| v.as_object().is_some_and(|o| !o.is_empty()));
    if let Some(found) = found {
        let r: IdentityRef = serde_json::from_value(found.clone()).unwrap_or_default();
        return person(&r, people);
    }
    thread
        .comments
        .first()
        .map_or_else(String::new, |c| person(&c.author, people))
}

/// `threads` is `None` when fetching them failed, which marks the PR incomplete.
#[must_use]
pub fn convert(
    pr: &PullRequestInfo,
    threads: Option<&[Thread]>,
    repo: &Repo,
    people: &mut People,
) -> PullRequest {
    let author = person(&pr.created_by, people);

    let mut approvers = BTreeSet::new();
    let mut rejecters = BTreeSet::new();
    let mut reviewers = Vec::new();
    for r in &pr.reviewers {
        let who = person(&r.identity, people);
        if is_bot(&who, r.identity.is_container) || who == author {
            continue;
        }
        reviewers.push(who.clone());
        if r.vote >= 5 {
            approvers.insert(who);
        } else if r.vote == -10 {
            rejecters.insert(who);
        }
    }

    let mut comment_counts = BTreeMap::new();
    let mut responses = Responses::default();
    for thread in threads.unwrap_or_default() {
        if thread.property("CodeReviewThreadType") == "VoteUpdate" {
            // Current votes reset when new commits are pushed; the vote history
            // in these threads keeps approvals that were reset.
            let who = voter(thread, people);
            if !who.is_empty() && who != author && !is_bot(&who, false) {
                let vote: i64 = thread.property("CodeReviewVoteResult").parse().unwrap_or(0);
                if vote >= 5 {
                    approvers.insert(who.clone());
                } else if vote == -10 {
                    rejecters.insert(who.clone());
                }
                responses.note(&who, parse_time(thread.published_date.as_deref()));
            }
            continue;
        }
        for c in &thread.comments {
            // System comments ("X updated the PR", "X voted") are not review comments.
            if c.comment_type != "text" || c.is_deleted {
                continue;
            }
            let who = person(&c.author, people);
            if is_bot(&who, false) {
                continue;
            }
            *comment_counts.entry(who.clone()).or_insert(0) += 1;
            if who != author {
                responses.note(&who, parse_time(c.published_date.as_deref()));
            }
        }
    }

    let web_url = repo
        .raw
        .get("webUrl")
        .and_then(|v| v.as_str())
        .unwrap_or_default();
    PullRequest {
        platform: Platform::AzureDevops,
        repo_id: repo.id.clone(),
        repository: repo.name.clone(),
        number: pr.pull_request_id,
        title: pr.title.clone(),
        author,
        state: state(&pr.status),
        is_draft: pr.is_draft,
        created_at: parse_time(pr.creation_date.as_deref())
            .unwrap_or_else(|| Timestamp::new(chrono::Utc::now())),
        closed_at: parse_time(pr.closed_date.as_deref()),
        url: if web_url.is_empty() {
            String::new()
        } else {
            format!("{web_url}/pullrequest/{}", pr.pull_request_id)
        },
        is_infrastructure: is_infrastructure(&pr.title),
        updated_at: None,
        reviewers,
        approvers: approvers.into_iter().collect(),
        rejecters: rejecters.into_iter().collect(),
        comment_counts,
        first_responses: responses.times,
        details_complete: threads.is_some(),
    }
}
