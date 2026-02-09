"""Unified data processor for handling both Azure DevOps and GitHub PR data."""

import logging
from typing import Any, Dict, List

from .azure_devops_data_processor import AzureDevOpsDataProcessor
from .base_data_processor import BaseDataProcessor
from .github_data_processor import GitHubDataProcessor


class UnifiedDataProcessor(BaseDataProcessor):
    """Processes raw pull request data from Azure DevOps and GitHub APIs."""

    def __init__(self, logger: logging.Logger, config=None):
        """Initialize the unified data processor."""
        super().__init__(logger, config)

    def _is_platform_system_identity(self, identity_name: str) -> bool:
        """Platform-specific system identity checks for both Azure DevOps and GitHub."""
        identity_lower = identity_name.lower()

        # Azure DevOps specific patterns
        azure_patterns = [
            "vstfs:///framework/identitydomain/",
            "vstfs:///classification/teamproject/",
            "\\example-team",
            "\\devops",
            "\\engineering",
        ]

        for pattern in azure_patterns:
            if pattern in identity_lower:
                return True

        # GitHub specific patterns
        github_patterns = ["[bot]", "github-actions", "dependabot"]

        for pattern in github_patterns:
            if pattern in identity_lower:
                return True

        # Check for domain identities without @ symbol (likely groups/teams)
        if "\\" in identity_name and "@" not in identity_name:
            return True

        return False

    def _identify_platform(self, pr: Dict[str, Any]) -> str:
        """Identify the platform of a PR based on its structure."""
        if "pullRequestId" in pr or "createdBy" in pr:
            return "azure_devops"
        elif "number" in pr and "user" in pr:
            return "github"
        else:
            return "unknown"

    def process_pull_requests(
        self, pr_data: List[Dict[str, Any]], platform: str
    ) -> List[Dict[str, Any]]:
        """Process raw pull request data into unified format with detailed review information."""
        filtered_pr_data = []
        excluded_count = {"iac": 0, "personal_approval": 0}

        # If platform is mixed, we need to process each PR based on its type
        if platform == "mixed":
            azure_prs = []
            github_prs = []

            # Sort PRs by platform
            for pr in pr_data:
                pr_platform = self._identify_platform(pr)
                if pr_platform == "azure_devops":
                    azure_prs.append(pr)
                elif pr_platform == "github":
                    github_prs.append(pr)

            # Process Azure DevOps PRs
            if azure_prs:
                azure_processor = AzureDevOpsDataProcessor(self.logger, self.config)
                filtered_pr_data.extend(
                    azure_processor.process_pull_requests(azure_prs, "azure_devops")
                )

            # Process GitHub PRs
            if github_prs:
                github_processor = GitHubDataProcessor(self.logger, self.config)
                filtered_pr_data.extend(
                    github_processor.process_pull_requests(github_prs, "github")
                )

            return filtered_pr_data

        # For single platform processing
        for pr in pr_data:
            try:
                # Skip IAC-related PRs (core filtering)
                if self._is_iac_related(pr, platform):
                    excluded_count["iac"] += 1
                    continue

                # Process based on platform
                if platform == "azure_devops":
                    processed_pr = self._process_azure_devops_pr(pr)
                elif platform == "github":
                    processed_pr = self._process_github_pr(pr)
                else:
                    self.logger.warning(f"Unknown platform: {platform}")
                    continue

                # Filter out personal approvals from review analytics (core
                # filtering)
                review_info = self._filter_personal_approvals(
                    processed_pr, processed_pr["Created By"]
                )
                processed_pr.update(review_info)
                excluded_count["personal_approval"] += review_info.get(
                    "personal_approvals_filtered", 0
                )

                # Add platform information
                processed_pr["Platform"] = platform.replace("_", " ").title()

                filtered_pr_data.append(processed_pr)

            except Exception as e:
                pr_id = pr.get("pullRequestId") or pr.get("number", "unknown")
                self.logger.warning(f"Failed to process PR {pr_id}: {e}")
                continue

        self.logger.info(
            f"Successfully processed {len(filtered_pr_data)} pull requests from {platform}"
        )
        self.logger.info(
            f"Excluded {excluded_count['iac']} IAC-related PRs and filtered "
            f"{excluded_count['personal_approval']} personal approvals"
        )
        return filtered_pr_data

    def _process_azure_devops_pr(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Process Azure DevOps PR data."""
        # Basic PR information
        processed_pr = {
            "ID": pr.get("pullRequestId"),
            "Repository": pr.get("repository_name", "Unknown"),
            "Work Item Type": "Code Review Request",
            "Created Date": pr.get("creationDate"),
            "Title": pr.get("title"),
            "Description": pr.get("description", ""),
            "Created By": self._extract_azure_created_by(pr),
            "Assigned To": self._extract_azure_reviewers(pr),
            "State": pr.get("status", "Closed"),
        }

        # Extract detailed review information
        review_info = self._extract_azure_review_details(pr)
        processed_pr.update(review_info)

        # Extract comment information
        comment_info = self._extract_azure_comment_details(pr)
        processed_pr.update(comment_info)

        return processed_pr

    def _process_github_pr(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Process GitHub PR data."""
        # Basic PR information
        processed_pr = {
            "ID": pr.get("number"),
            "Repository": pr.get("repository_name", "Unknown"),
            "Work Item Type": "Code Review Request",
            "Created Date": pr.get("created_at"),
            "Title": pr.get("title"),
            "Description": pr.get("body", ""),
            "Created By": self._extract_github_created_by(pr),
            "Assigned To": self._extract_github_reviewers(pr),
            "State": (
                "Closed" if pr.get("state") == "closed" else pr.get("state", "Open")
            ),
        }

        # Extract detailed review information
        review_info = self._extract_github_review_details(pr)
        processed_pr.update(review_info)

        # Extract comment information
        comment_info = self._extract_github_comment_details(pr)
        processed_pr.update(comment_info)

        return processed_pr

    def _extract_azure_created_by(self, pr: Dict[str, Any]) -> str:
        """Extract the creator's unique name from Azure DevOps PR data."""
        created_by = pr.get("createdBy", {})
        return created_by.get("uniqueName", "Unknown")

    def _extract_github_created_by(self, pr: Dict[str, Any]) -> str:
        """Extract the creator's login from GitHub PR data."""
        user = pr.get("user", {})
        return user.get("login", "Unknown")

    def _extract_azure_reviewers(self, pr: Dict[str, Any]) -> List[str]:
        """Extract and format assigned reviewers from Azure DevOps."""
        reviewers = pr.get("reviewers", [])
        reviewers_info = []

        for reviewer in reviewers:
            display_name = reviewer.get("displayName", "Unknown")
            unique_name = reviewer.get("uniqueName", "Unknown")
            reviewers_info.append(f"{display_name} - {unique_name}")

        return reviewers_info

    def _extract_github_reviewers(self, pr: Dict[str, Any]) -> List[str]:
        """Extract and format assigned reviewers from GitHub."""
        # GitHub doesn't have explicit "assigned reviewers" in the same way
        # We'll extract from requested_reviewers and reviews
        reviewers_info = []

        # Get requested reviewers
        requested_reviewers = pr.get("requested_reviewers", [])
        for reviewer in requested_reviewers:
            login = reviewer.get("login", "Unknown")
            reviewers_info.append(f"{login} (requested)")

        # Get actual reviewers from reviews
        reviews = pr.get("reviews", [])
        reviewed_by = set()
        for review in reviews:
            user = review.get("user", {})
            login = user.get("login", "Unknown")
            if login != "Unknown" and not self.is_system_identity(login):
                reviewed_by.add(login)

        for reviewer in reviewed_by:
            if reviewer not in [r.split(" (")[0] for r in reviewers_info]:
                reviewers_info.append(reviewer)

        return reviewers_info

    def _extract_azure_review_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract detailed review information from Azure DevOps PR."""
        reviewers = pr.get("reviewers", [])

        # Count reviewer votes
        approved_by = []
        rejected_by = []
        waiting_reviewers = []
        optional_reviewers = []

        for reviewer in reviewers:
            reviewer_name = reviewer.get("uniqueName", "Unknown")

            # Filter out system/team reviewers
            if self.is_system_identity(reviewer_name):
                continue

            vote = reviewer.get("vote", 0)
            is_required = reviewer.get("isRequired", True)

            # Azure DevOps vote values: 10=approved, -10=rejected, -5=waiting
            # for author, 5=approved with suggestions, 0=no vote
            if vote == 10:  # Approved
                approved_by.append(reviewer_name)
            elif vote == -10:  # Rejected
                rejected_by.append(reviewer_name)
            elif vote == 5:  # Approved with suggestions
                approved_by.append(f"{reviewer_name} (with suggestions)")
            elif vote == -5:  # Waiting for author
                waiting_reviewers.append(reviewer_name)
            elif vote == 0 and is_required:  # No vote but required
                waiting_reviewers.append(reviewer_name)
            elif not is_required:  # Optional reviewer
                optional_reviewers.append(reviewer_name)

        # Filter system identities from all reviewers for counting
        filtered_reviewers = [
            r
            for r in reviewers
            if not self.is_system_identity(r.get("uniqueName", "Unknown"))
        ]

        return {
            "Approved By": approved_by,
            "Rejected By": rejected_by,
            "Waiting Reviewers": waiting_reviewers,
            "Optional Reviewers": optional_reviewers,
            "Total Reviewers": len(filtered_reviewers),
            "Approval Count": len(approved_by),
            "Rejection Count": len(rejected_by),
        }

    def _extract_github_review_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract detailed review information from GitHub PR."""
        reviews = pr.get("reviews", [])

        # Count reviewer votes
        approved_by = []
        changes_requested_by = []
        commented_by = []

        # Track latest review state per reviewer
        reviewer_states = {}

        for review in reviews:
            user = review.get("user", {})
            reviewer_name = user.get("login", "Unknown")

            # Filter out system/team reviewers
            if self.is_system_identity(reviewer_name):
                continue

            state = review.get("state", "").upper()
            submitted_at = review.get("submitted_at")

            # Keep track of the latest review state for each reviewer
            if (
                reviewer_name not in reviewer_states
                or submitted_at > reviewer_states[reviewer_name]["submitted_at"]
            ):
                reviewer_states[reviewer_name] = {
                    "state": state,
                    "submitted_at": submitted_at,
                }

        # Process final states
        for reviewer_name, review_data in reviewer_states.items():
            state = review_data["state"]

            if state == "APPROVED":
                approved_by.append(reviewer_name)
            elif state == "CHANGES_REQUESTED":
                changes_requested_by.append(reviewer_name)
            elif state == "COMMENTED":
                commented_by.append(reviewer_name)

        return {
            "Approved By": approved_by,
            # GitHub "changes requested" maps to "rejected"
            "Rejected By": changes_requested_by,
            "Waiting Reviewers": commented_by,  # Commenters are waiting for response
            "Optional Reviewers": [],  # GitHub doesn't have explicit optional reviewers
            "Total Reviewers": len(reviewer_states),
            "Approval Count": len(approved_by),
            "Rejection Count": len(changes_requested_by),
        }

    def _extract_azure_comment_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract comment and discussion thread information from Azure DevOps."""
        threads = pr.get("threads", [])

        # Handle case where thread details weren't fetched
        if not isinstance(threads, list):
            return {
                "Total Comments": 0,
                "Commenters": [],
                "Active Threads": 0,
                "Resolved Threads": 0,
                "Total Threads": 0,
                "Comment Count": 0,
                "Comment Counts": {},
            }

        total_comments = 0
        commenters = []
        comment_counts = {}
        active_threads = 0
        resolved_threads = 0

        for thread in threads:
            thread_status = thread.get("status", "unknown")
            if thread_status == "active":
                active_threads += 1
            elif thread_status == "closed" or thread_status == "fixed":
                resolved_threads += 1

            # Count comments in this thread
            comments = thread.get("comments", [])

            for comment in comments:
                author = comment.get("author", {})
                author_name = author.get("uniqueName", "Unknown")

                # Skip system/team identities
                if self.is_system_identity(author_name):
                    continue

                if author_name != "Unknown":
                    total_comments += 1

                    if author_name not in commenters:
                        commenters.append(author_name)

                    comment_counts[author_name] = comment_counts.get(author_name, 0) + 1

        return {
            "Total Comments": total_comments,
            "Commenters": commenters,
            "Active Threads": active_threads,
            "Resolved Threads": resolved_threads,
            "Total Threads": len(threads),
            "Comment Count": len(commenters),
            "Comment Counts": comment_counts,
        }

    def _extract_github_comment_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract comment information from GitHub PR."""
        review_comments = pr.get("review_comments", [])
        issue_comments = pr.get("issue_comments", [])

        total_comments = 0
        commenters = []
        comment_counts = {}

        # Process review comments (code comments)
        for comment in review_comments:
            user = comment.get("user", {})
            author_name = user.get("login", "Unknown")

            # Skip system/team identities
            if self.is_system_identity(author_name):
                continue

            if author_name != "Unknown":
                total_comments += 1

                if author_name not in commenters:
                    commenters.append(author_name)

                comment_counts[author_name] = comment_counts.get(author_name, 0) + 1

        # Process issue comments (general comments)
        for comment in issue_comments:
            user = comment.get("user", {})
            author_name = user.get("login", "Unknown")

            # Skip system/team identities
            if self.is_system_identity(author_name):
                continue

            if author_name != "Unknown":
                total_comments += 1

                if author_name not in commenters:
                    commenters.append(author_name)

                comment_counts[author_name] = comment_counts.get(author_name, 0) + 1

        # GitHub doesn't have explicit thread status, so we'll estimate
        # Active threads = review comments (assuming they're ongoing discussions)
        # Resolved threads = 0 (we can't determine this easily from GitHub API)
        active_threads = len(review_comments)
        resolved_threads = 0
        total_threads = active_threads + resolved_threads

        return {
            "Total Comments": total_comments,
            "Commenters": commenters,
            "Active Threads": active_threads,
            "Resolved Threads": resolved_threads,
            "Total Threads": total_threads,
            "Comment Count": len(commenters),
            "Comment Counts": comment_counts,
        }

    def _is_iac_related(self, pr: Dict[str, Any], platform: str) -> bool:
        """Check if a PR is related to Infrastructure as Code using canonical keywords."""
        title = pr.get("title", "")
        description = (pr.get("description") or pr.get("body", ""))
        repo_name = pr.get("repository_name", "")

        text_to_check = f"{title} {description} {repo_name}".lower()

        for keyword in self.iac_keywords:
            if keyword in text_to_check:
                return True

        for pattern in self.iac_file_patterns:
            if pattern in text_to_check:
                return True

        return False

    def _filter_personal_approvals(
        self, processed_pr: Dict[str, Any], created_by: str
    ) -> Dict[str, Any]:
        """Filter out personal approvals where the creator approved their own PR."""
        approved_by = processed_pr.get("Approved By", [])
        personal_approvals_count = 0

        # Filter out approvals from the PR creator (case-insensitive)
        filtered_approved_by = []
        for approver in approved_by:
            approver_username = (
                approver.split(" (")[0] if " (" in approver else approver
            )
            if approver_username.lower() != created_by.lower():
                filtered_approved_by.append(approver)
            else:
                personal_approvals_count += 1

        # Update the processed PR with filtered data
        processed_pr["Approved By"] = filtered_approved_by
        processed_pr["Approval Count"] = len(filtered_approved_by)
        processed_pr["personal_approvals_filtered"] = personal_approvals_count

        return processed_pr
