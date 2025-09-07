"""Data processing utilities for Azure DevOps pull request data."""

import logging
from typing import Dict, List, Any
from .base_data_processor import BaseDataProcessor
from ..core.safe_data_parser import safe_parse_list, safe_parse_dict


class DataProcessor(BaseDataProcessor):
    """Processes raw pull request data from Azure DevOps API."""

    def __init__(self, logger: logging.Logger, config=None):
        """Initialize the Azure DevOps data processor."""
        super().__init__(logger, config)

    def _is_platform_system_identity(self, identity_name: str) -> bool:
        """Azure DevOps specific system identity checks."""
        identity_lower = identity_name.lower()

        # Azure DevOps specific patterns
        azure_patterns = [
            "vstfs:///framework/identitydomain/",
            "vstfs:///classification/teamproject/",
            "\\example-team",
            "\\devops",
            "\\engineering",
            "\\graph data science",
            "\\salesforce owners",
            "\\site reliability engineering",
        ]

        for pattern in azure_patterns:
            if pattern in identity_lower:
                return True

        # Check for domain identities without @ symbol (likely groups/teams)
        if "\\" in identity_name and "@" not in identity_name:
            return True

        return False

    def process_pull_requests(
        self, pr_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process raw pull request data into the desired format with detailed review information."""
        filtered_pr_data = []
        excluded_count = {"iac": 0, "personal_approval": 0}

        for pr in pr_data:
            try:
                # Skip IAC-related PRs (core filtering)
                if self._is_iac_related(pr):
                    excluded_count["iac"] += 1
                    continue

                # Basic PR information
                processed_pr = {
                    "ID": pr.get("pullRequestId"),
                    "Repository": pr.get("repository_name", "Unknown"),
                    "Work Item Type": "Code Review Request",
                    "Created Date": pr.get("creationDate"),
                    "Title": pr.get("title"),
                    "Description": pr.get("description", ""),
                    "Created By": self._extract_created_by(pr),
                    "Assigned To": self._extract_reviewers(pr),
                    "State": pr.get("status", "Closed"),
                }

                # Extract detailed review information
                review_info = self._extract_review_details(pr)
                processed_pr.update(review_info)

                # Extract comment information
                comment_info = self._extract_comment_details(pr)
                processed_pr.update(comment_info)

                # Filter out personal approvals from review analytics (core filtering)
                review_info = self._filter_personal_approvals(
                    review_info, processed_pr["Created By"]
                )
                processed_pr.update(review_info)
                excluded_count["personal_approval"] += review_info.get(
                    "personal_approvals_filtered", 0
                )

                filtered_pr_data.append(processed_pr)

            except Exception as e:
                self.logger.warning(
                    f"Failed to process PR {pr.get('pullRequestId', 'unknown')}: {e}"
                )
                continue

        self.logger.info(
            f"Successfully processed {len(filtered_pr_data)} pull requests"
        )
        self.logger.info(
            f"Excluded {excluded_count['iac']} IAC-related PRs and filtered {excluded_count['personal_approval']} personal approvals"
        )
        return filtered_pr_data

    def _extract_created_by(self, pr: Dict[str, Any]) -> str:
        """Extract the creator's unique name from pull request data."""
        created_by = pr.get("createdBy", {})
        return created_by.get("uniqueName", "Unknown")

    def _extract_reviewers(self, pr: Dict[str, Any]) -> List[str]:
        """Extract and format assigned reviewers."""
        reviewers = pr.get("reviewers", [])
        reviewers_info = []

        for reviewer in reviewers:
            display_name = reviewer.get("displayName", "Unknown")
            unique_name = reviewer.get("uniqueName", "Unknown")
            reviewers_info.append(f"{display_name} - {unique_name}")

        return reviewers_info

    def _extract_review_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract detailed review information including votes and approvals, filtering out system/team reviewers."""
        reviewers = pr.get("reviewers", [])

        # Count reviewer votes
        approved_by = []
        rejected_by = []
        waiting_reviewers = []
        optional_reviewers = []

        for reviewer in reviewers:
            reviewer_name = reviewer.get("uniqueName", "Unknown")

            # Filter out system/team reviewers using our centralized method
            if self._is_system_identity(reviewer_name):
                continue

            vote = reviewer.get("vote", 0)
            is_required = reviewer.get("isRequired", True)
            # Azure DevOps vote values: 10=approved, -10=rejected, -5=waiting for author, 5=approved with suggestions, 0=no vote
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
            if not self._is_system_identity(r.get("uniqueName", "Unknown"))
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

    def _extract_comment_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract comment and discussion thread information."""
        threads = pr.get("threads", [])

        # Handle case where thread details weren't fetched for performance
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
        comment_counts = {}  # Track comments per person
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

            # Extract commenters and count their comments, filtering out system identities
            for comment in comments:
                author = comment.get("author", {})
                author_name = author.get("uniqueName", "Unknown")

                # Skip system/team identities
                if self._is_system_identity(author_name):
                    continue

                if author_name != "Unknown":
                    # Count total comments (excluding system identities)
                    total_comments += 1

                    # Track unique commenters
                    if author_name not in commenters:
                        commenters.append(author_name)

                    # Count comments per person
                    if author_name in comment_counts:
                        comment_counts[author_name] += 1
                    else:
                        comment_counts[author_name] = 1

        return {
            "Total Comments": total_comments,
            "Commenters": commenters,
            "Active Threads": active_threads,
            "Resolved Threads": resolved_threads,
            "Total Threads": len(threads),
            "Comment Count": len(commenters),
            "Comment Counts": comment_counts,
        }

    def _is_iac_related(self, pr: Dict[str, Any]) -> bool:
        """Check if a PR is related to Infrastructure as Code."""
        # IAC-related keywords to check in title and description
        iac_keywords = [
            "terraform",
            "tf",
            "bicep",
            "arm template",
            "cloudformation",
            "cfn",
            "infrastructure",
            "infra",
            "deployment",
            "pipeline",
            "yaml",
            "yml",
            "docker",
            "dockerfile",
            "kubernetes",
            "k8s",
            "helm",
            "ansible",
            "pulumi",
            "cdk",
            "azure resource manager",
            "arm",
            "azuredeploy",
        ]

        title = pr.get("title", "").lower()
        description = pr.get("description", "").lower()
        repo_name = pr.get("repository_name", "").lower()

        # Check if any IAC keywords are present
        for keyword in iac_keywords:
            if keyword in title or keyword in description or keyword in repo_name:
                return True

        # Check for specific IAC file patterns in the title/description
        iac_patterns = [".tf", ".bicep", ".yaml", ".yml", "dockerfile", ".json"]
        for pattern in iac_patterns:
            if pattern in title or pattern in description:
                return True

        return False

    def _filter_personal_approvals(
        self, review_info: Dict[str, Any], created_by: str
    ) -> Dict[str, Any]:
        """Filter out personal approvals where the creator approved their own PR."""
        approved_by = review_info.get("Approved By", [])
        personal_approvals_count = 0

        # Filter out approvals from the PR creator
        filtered_approved_by = []
        for approver in approved_by:
            # Extract the username (before any additional info like "(with suggestions)")
            approver_username = (
                approver.split(" (")[0] if " (" in approver else approver
            )
            if approver_username != created_by:
                filtered_approved_by.append(approver)
            else:
                personal_approvals_count += 1

        # Update the review info with filtered data
        updated_review_info = review_info.copy()
        updated_review_info["Approved By"] = filtered_approved_by
        updated_review_info["Approval Count"] = len(filtered_approved_by)
        updated_review_info["personal_approvals_filtered"] = personal_approvals_count

        return updated_review_info
