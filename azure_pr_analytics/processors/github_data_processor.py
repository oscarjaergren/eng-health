"""Data processing utilities for GitHub pull request data."""

import logging
from typing import Any, Dict, List, Optional

from .base_data_processor import BaseDataProcessor


class GitHubDataProcessor(BaseDataProcessor):
    """Processes raw pull request data from GitHub API."""

    def __init__(self, logger: logging.Logger, config=None):
        """Initialize the GitHub data processor."""
        super().__init__(logger, config)

    def process_pull_requests(
        self, pr_data: Optional[List[Dict[str, Any]]], platform: str = "github"
    ) -> List[Dict[str, Any]]:
        """Process raw GitHub pull request data into the desired format.

        Args:
            pr_data: List of pull request dictionaries, or None
            platform: The platform the PRs came from (default: "github")

        Returns:
            List of processed PR dictionaries
        """
        if pr_data is None:
            return []

        processed_data = []
        excluded_count = {"iac": 0, "personal_approval": 0}

        # Always exclude IAC PRs and personal approvals
        for pr in pr_data:
            try:
                # Skip IAC-related PRs
                if self.is_iac_related(pr.get("title", ""), pr.get("body", "")):
                    excluded_count["iac"] += 1
                    continue

                # Basic PR information
                processed_pr = {
                    "ID": pr.get("number"),
                    "Repository": pr.get("repository_name", "Unknown"),
                    "Work Item Type": "Code Review Request",
                    "Created Date": pr.get("created_at"),
                    "Title": pr.get("title"),
                    "Description": pr.get("body", ""),
                    "Created By": self._extract_created_by(pr),
                    "Assigned To": self._extract_github_reviewers(pr),
                    "State": self._extract_github_status(pr),
                }

                # Extract reviewer information
                reviewer_info = self._extract_github_reviewers(pr)
                processed_pr.update(reviewer_info)

                # Extract comment information
                comment_info = self._extract_github_comments(pr)
                processed_pr.update(comment_info)

                # Filter out personal approvals from review analytics
                review_info = self._filter_personal_approvals(
                    processed_pr, processed_pr["Created By"]
                )
                processed_pr.update(review_info)
                excluded_count["personal_approval"] += review_info.get(
                    "personal_approvals_filtered", 0
                )

                processed_data.append(processed_pr)

            except Exception as e:
                self.logger.warning(
                    f"Failed to process GitHub PR {pr.get('id', 'unknown')}: {e}"
                )
                continue

        self.logger.info(
            f"Successfully processed {len(processed_data)} GitHub pull requests"
        )
        self.logger.info(
            f"Excluded {excluded_count['iac']} IAC-related PRs and filtered "
            f"{excluded_count['personal_approval']} personal approvals"
        )
        return processed_data

    def _is_platform_system_identity(self, identity_name: str) -> bool:
        """GitHub specific system identity checks."""
        identity_lower = identity_name.lower()

        # GitHub specific patterns
        github_patterns = [
            "github-actions",
            "dependabot",
            "renovate",
            "codecov",
            "sonarcloud",
            "snyk-bot",
            "greenkeeper",
            "imgbot",
            "allcontributors",
            "semantic-release-bot",
        ]

        for pattern in github_patterns:
            if pattern in identity_lower:
                return True

        # Check for bot accounts (ending with [bot])
        if identity_name.endswith("[bot]"):
            return True

        return False

    def process_pull_request_data(
        self, pr_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process raw GitHub pull request data into the unified format."""
        processed_data = []
        excluded_count = {"iac": 0, "personal_approval": 0}

        for pr in pr_data:
            try:
                # Skip IAC-related PRs (core filtering)
                if self._is_iac_related(pr):
                    excluded_count["iac"] += 1
                    continue

                # Basic PR information
                processed_pr = {
                    "PR ID": pr.get("id"),
                    "Repository": pr.get("repository_name", "Unknown"),
                    "Title": pr.get("title", ""),
                    "Description": pr.get("body", ""),
                    "Created By": self._extract_created_by(pr),
                    "Created Date": pr.get("created_at"),
                    "Updated Date": pr.get("updated_at"),
                    "Closed Date": pr.get("closed_at"),
                    "Merged Date": pr.get("merged_at"),
                    "Status": self._extract_github_status(pr),
                    "Platform": "GitHub",
                }

                # Extract reviewer information
                reviewer_info = self._extract_github_reviewers(pr)
                processed_pr.update(reviewer_info)

                # Extract comment information
                comment_info = self._extract_github_comments(pr)
                processed_pr.update(comment_info)

                # Filter out personal approvals from review analytics
                review_info = self._filter_personal_approvals(
                    processed_pr, processed_pr["Created By"]
                )
                processed_pr.update(review_info)
                excluded_count["personal_approval"] += review_info.get(
                    "personal_approvals_filtered", 0
                )

                processed_data.append(processed_pr)

            except Exception as e:
                self.logger.warning(
                    f"Failed to process GitHub PR {pr.get('id', 'unknown')}: {e}"
                )
                continue

        self.logger.info(
            f"Successfully processed {len(processed_data)} GitHub pull requests"
        )
        self.logger.info(
            f"Excluded {excluded_count['iac']} IAC-related PRs and filtered "
            f"{excluded_count['personal_approval']} personal approvals"
        )
        return processed_data

    def _extract_created_by(self, pr: Dict[str, Any]) -> str:
        """Extract the creator's login from GitHub pull request data."""
        user = pr.get("user", {})
        return user.get("login", "Unknown")

    def _extract_github_status(self, pr: Dict[str, Any]) -> str:
        """Extract and convert GitHub PR status to unified format."""
        state = pr.get("state", "unknown").lower()
        merged = pr.get("merged", False)

        if state == "open":
            return "Active"
        elif state == "closed" and merged:
            return "Closed"  # Changed from 'Merged' to match test expectations
        elif state == "closed" and not merged:
            return "Abandoned"
        else:
            return "Unknown"

    def _filter_personal_approvals(
        self, review_info: Dict[str, Any], created_by: str
    ) -> Dict[str, Any]:
        """Filter out personal approvals where the creator approved their own PR.
        Always removes self-approvals as they should never be counted.

        Args:
            review_info: Dictionary containing review information
            created_by: Email of the PR creator

        Returns:
            Updated review information with personal approvals removed
        """
        if not created_by:
            return review_info

        approved_by = review_info.get("Approved By", [])
        filtered_approved_by = []
        personal_approvals_filtered = 0

        for approver in approved_by:
            # Extract just the email part if it's in format 'Name (email@example.com)'
            if "(" in approver and ")" in approver:
                # Handle 'Name (email@example.com)' format
                email_start = approver.rfind("(") + 1
                email_end = approver.rfind(")")
                approver_email = approver[email_start:email_end].strip()
            else:
                # Handle plain email format
                approver_email = approver.strip()

            if approver_email.lower() != created_by.lower():
                filtered_approved_by.append(approver)
            else:
                personal_approvals_filtered += 1

        # Update the review info with filtered approvals
        updated_review_info = review_info.copy()
        updated_review_info["Approved By"] = filtered_approved_by
        updated_review_info["Approval Count"] = len(filtered_approved_by)
        updated_review_info["personal_approvals_filtered"] = personal_approvals_filtered

        return updated_review_info

    def _extract_github_reviewers(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract reviewer information from GitHub PR reviews."""
        reviews = pr.get("reviews", [])

        # Track reviewers and their latest review state
        reviewer_states = {}
        approved_by = []
        rejected_by = []
        waiting_reviewers = []

        for review in reviews:
            reviewer = review.get("user", {})
            reviewer_login = reviewer.get("login", "Unknown")

            # Filter out system/bot reviewers
            if self.is_system_identity(reviewer_login):
                continue

            review_state = review.get("state", "COMMENTED")

            # Track the latest review state for each reviewer
            reviewer_states[reviewer_login] = review_state

        # Categorize reviewers based on their latest review state
        for reviewer_login, state in reviewer_states.items():
            converted_state = self._convert_github_review_state(state)

            if converted_state == "Approved":
                approved_by.append(reviewer_login)
            elif converted_state == "Rejected":
                rejected_by.append(reviewer_login)
            else:
                waiting_reviewers.append(reviewer_login)

        # Create assigned to list (all reviewers)
        all_reviewers = list(reviewer_states.keys())

        return {
            "Assigned To": all_reviewers,
            "Approved By": approved_by,
            "Rejected By": rejected_by,
            "Waiting Reviewers": waiting_reviewers,
            "Total Reviewers": len(all_reviewers),
            "Approval Count": len(approved_by),
            "Rejection Count": len(rejected_by),
            "Reviewer Count": len(all_reviewers),
        }

    def _convert_github_review_state(self, github_state: str) -> str:
        """Convert GitHub review state to unified format."""
        state_mapping = {
            "APPROVED": "Approved",
            "CHANGES_REQUESTED": "Rejected",
            "COMMENTED": "Commented",
            "DISMISSED": "Waiting for author",
        }

        return state_mapping.get(github_state, "Waiting for author")

    def _extract_github_comments(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract comment information from GitHub PR."""
        comments = pr.get("comments", [])
        reviews = pr.get("reviews", [])

        # Combine regular comments and review comments
        all_comments = []
        commenters = set()
        comment_counts = {}

        # Process regular comments
        for comment in comments:
            author = comment.get("user", {})
            author_login = author.get("login", "Unknown")

            # Skip system/bot commenters
            if self.is_system_identity(author_login):
                continue

            all_comments.append(comment)
            commenters.add(author_login)
            comment_counts[author_login] = comment_counts.get(author_login, 0) + 1

        # Process review comments (from reviews)
        for review in reviews:
            reviewer = review.get("user", {})
            reviewer_login = reviewer.get("login", "Unknown")

            # Skip system/bot reviewers
            if self.is_system_identity(reviewer_login):
                continue

            # Only count reviews with actual comments (not just approvals)
            if review.get("body") and review.get("body").strip():
                all_comments.append(review)
                commenters.add(reviewer_login)
                comment_counts[reviewer_login] = (
                    comment_counts.get(reviewer_login, 0) + 1
                )

        return {
            "Total Comments": len(all_comments),
            "Commenters": list(commenters),
            "Comment Count": len(commenters),
            "Comment Counts": comment_counts,
            # GitHub doesn't have the same thread concept as Azure DevOps
            "Active Threads": 0,
            "Resolved Threads": 0,
            "Total Threads": 0,
        }

    def _is_iac_related(self, pr_or_title: Dict[str, Any], body: str = "") -> bool:
        """Check if a GitHub PR is related to Infrastructure as Code.

        Args:
            pr_or_title: Either the pull request data dictionary or the PR title
            body: The PR body (only used if pr_or_title is a string)

        Returns:
            bool: True if the PR is IAC-related, False otherwise
        """
        # Get config value, defaulting to True if not set (backward compatibility)
        exclude_iac = getattr(self.config, "exclude_iac", True)

        # If IAC filtering is disabled, always return False
        if not exclude_iac:
            return False

        # Handle both PR dictionary and direct title/body parameters
        if isinstance(pr_or_title, dict):
            pr = pr_or_title
            title = pr.get("title", "").lower()
            body = pr.get("body", "").lower()
        else:
            title = str(pr_or_title).lower()
            body = str(body).lower()

        # Check for IAC-related keywords
        iac_keywords = [
            "terraform",
            "tf",
            "infrastructure",
            "deployment",
            "deploy",
            "ansible",
            "puppet",
            "chef",
            "cloudformation",
            "arm template",
            "bicep",
            "helm",
            "kubernetes",
            "k8s",
            "docker",
            "dockerfile",
            "ci/cd",
            "pipeline",
            "build",
            "release",
            "devops",
        ]

        for keyword in iac_keywords:
            if keyword in title or keyword in body:
                return True

        # Check file changes if available (only when pr_or_title is a dict)
        if isinstance(pr_or_title, dict) and "files" in pr_or_title:
            for file_info in pr_or_title["files"]:
                filename = file_info.get("filename", "").lower()
                if any(
                    ext in filename
                    for ext in [".tf", ".yml", ".yaml", "dockerfile", ".json"]
                ):
                    # Check if it's in infrastructure-related directories
                    if any(
                        dir_name in filename
                        for dir_name in [
                            "terraform",
                            "ansible",
                            "deploy",
                            "infra",
                            ".github/workflows",
                        ]
                    ):
                        return True

        return False
