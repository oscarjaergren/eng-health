//! GraphQL pull request -> `PullRequest`. Ports `from_github` in
//! `pr_analytics/processing.py`; `testdata/github/*.graphql.json` pins parity.

use std::collections::{BTreeMap, BTreeSet};

use crate::model::{Platform, PullRequest, Repo, State, Timestamp};
use crate::rules::{identity, is_bot, is_infrastructure, parse_time};
use crate::source::People;

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

/// First response per person, remembering first-seen order like a Python dict.
#[derive(Default)]
struct Responses {
    order: Vec<String>,
    times: BTreeMap<String, Timestamp>,
}

impl Responses {
    fn note(&mut self, who: &str, when: Option<Timestamp>) {
        let Some(when) = when else { return };
        match self.times.get(who) {
            Some(t) if *t <= when => {}
            Some(_) => {
                self.times.insert(who.to_owned(), when);
            }
            None => {
                self.order.push(who.to_owned());
                self.times.insert(who.to_owned(), when);
            }
        }
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
        updated_at: parse_time(Some(&node.updated_at)),
        reviewers,
        approvers: approvers.into_iter().collect(),
        rejecters: rejecters.into_iter().collect(),
        comment_counts,
        first_responses: responses.times,
        details_complete: complete,
    }
}
