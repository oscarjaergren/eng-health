"""Data processing utilities for Azure DevOps pull request data."""

import logging
from typing import Any, Dict, List, Optional

from .base_data_processor import BaseDataProcessor


class AzureDevOpsDataProcessor(BaseDataProcessor):
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
        self, pr_data: Optional[List[Dict[str, Any]]], platform: str = "azure_devops"
    ) -> List[Dict[str, Any]]:
        """Process raw pull request data into the desired format with detailed review information.

        Args:
            pr_data: List of pull request dictionaries, or None
            platform: The platform the PRs came from (default: "azure_devops")

        Returns:
            List of processed PR dictionaries
        """
        if pr_data is None:
            return []

        filtered_pr_data = []
        excluded_count = {"iac": 0, "personal_approval": 0}

        # Get config values, defaulting to True if not set (backward compatibility)
        exclude_iac = getattr(self.config, "exclude_iac", True)

        for pr in pr_data:
            try:
                # Skip IAC-related PRs if configured to do so
                if exclude_iac and self._is_iac_related(pr):
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

                # Filter out personal approvals
                filtered_review_info = self._filter_personal_approvals(
                    processed_pr, processed_pr["Created By"]
                )
                processed_pr.update(filtered_review_info)
                excluded_count["personal_approval"] += filtered_review_info.get(
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
            f"Excluded {excluded_count['iac']} IAC-related PRs and filtered "
            f"{excluded_count['personal_approval']} personal approvals"
        )
        return filtered_pr_data

    def _extract_created_by(self, pr: Dict[str, Any]) -> str:
        """Extract the creator's display name from pull request data."""
        created_by = pr.get("createdBy", {})
        return created_by.get("displayName", "Unknown")

    def _extract_reviewers(self, pr: Dict[str, Any]) -> List[str]:
        """Extract and format assigned reviewers."""
        reviewers = pr.get("reviewers", [])
        reviewers_info = []

        for reviewer in reviewers:
            display_name = reviewer.get("displayName", "Unknown")
            unique_name = reviewer.get("uniqueName", "Unknown")
            reviewers_info.append(f"{display_name} - {unique_name}")

        return reviewers_info

    def _extract_historical_approvers(self, pr: Dict[str, Any]) -> List[str]:
        """Extract all users who ever approved the PR from thread history.
        
        Azure DevOps records vote changes in system threads. This method parses
        those threads to find anyone who approved at any point, even if their
        vote was later reset by new commits.
        """
        threads = pr.get("threads", [])
        historical_approvers = set()
        created_by = pr.get("createdBy", {}).get("uniqueName", "").lower()
        
        if not isinstance(threads, list):
            return []
        
        for thread in threads:
            # System-generated vote threads have specific properties
            properties = thread.get("properties", {})
            
            # Check for vote threads via CodeReviewVotedByIdentity property
            voted_by_prop = properties.get("CodeReviewVotedByIdentity", {})
            vote_prop = properties.get("CodeReviewVoteResult", {})
            
            if voted_by_prop and vote_prop:
                voter_id = voted_by_prop.get("$value", "")
                vote_result = vote_prop.get("$value", "")
                
                # Positive votes (10 = approved, 5 = approved with suggestions)
                if vote_result in ["10", "5"]:
                    if voter_id and not self.is_system_identity(voter_id):
                        if voter_id.lower() != created_by:
                            historical_approvers.add(voter_id)
            
            # Also check thread comments for vote-related system messages
            for comment in thread.get("comments", []):
                comment_type = comment.get("commentType", "")
                
                if comment_type == "system":
                    author = comment.get("author", {})
                    author_name = author.get("uniqueName", "")
                    content = comment.get("content", "").lower()
                    
                    # System messages like "X approved" or "X voted approve"
                    if any(phrase in content for phrase in ["approved", "voted 10", "voted 5"]):
                        if author_name and not self.is_system_identity(author_name):
                            if author_name.lower() != created_by:
                                historical_approvers.add(author_name)
        
        return list(historical_approvers)

    def _extract_review_details(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract detailed review information including votes and approvals, filtering out system/team reviewers."""
        reviewers = pr.get("reviewers", [])
        created_by = pr.get("createdBy", {}).get("uniqueName", "")

        # Count current reviewer votes
        approved_by = []
        rejected_by = []
        waiting_reviewers = []
        optional_reviewers = []

        for reviewer in reviewers:
            reviewer_name = reviewer.get("uniqueName", "Unknown")

            # Filter out system/team reviewers using our centralized method
            if self.is_system_identity(reviewer_name):
                continue

            vote = reviewer.get("vote", 0)
            is_required = reviewer.get("isRequired", False)

            # Azure DevOps vote values: 10=approved, 5=approved with suggestions,
            # -5=waiting for author, -10=rejected, 0=no vote
            if vote == 10:
                approved_by.append(reviewer_name)
            elif vote == 5:
                approved_by.append(f"{reviewer_name} (with suggestions)")
            elif vote == -10:
                rejected_by.append(reviewer_name)
            elif vote == -5:
                waiting_reviewers.append(reviewer_name)
            elif is_required:
                waiting_reviewers.append(reviewer_name)
            else:
                optional_reviewers.append(reviewer_name)

        # Extract historical approvers from threads
        historical_approvers = self._extract_historical_approvers(pr)
        
        # Merge: "Ever Approved" = current approvers + historical approvers (deduplicated)
        ever_approved_set = set(approved_by) | set(historical_approvers)
        ever_approved = list(ever_approved_set)

        # Filter system identities from all reviewers for counting
        filtered_reviewers = [
            r
            for r in reviewers
            if not self.is_system_identity(r.get("uniqueName", "Unknown"))
        ]

        review_info = {
            "Approved By": approved_by,
            "Ever Approved": ever_approved,
            "Rejected By": rejected_by,
            "Waiting Reviewers": waiting_reviewers,
            "Optional Reviewers": optional_reviewers,
            "Total Reviewers": len(filtered_reviewers),
            "Approval Count": len(approved_by),
            "Ever Approved Count": len(ever_approved),
            "Rejection Count": len(rejected_by),
        }

        # Always filter out personal approvals
        if created_by:
            review_info = self._filter_personal_approvals(review_info, created_by)

        return review_info

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

            # Extract commenters and count their comments, filtering out system
            # identities
            for comment in comments:
                author = comment.get("author", {})
                author_name = author.get("uniqueName", "Unknown")

                # Skip system/team identities
                if self.is_system_identity(author_name):
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
        """Check if a PR is related to Infrastructure as Code using canonical keywords."""
        title = pr.get("title", "")
        description = pr.get("description", "")
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
        self, review_info: Dict[str, Any], created_by: str
    ) -> Dict[str, Any]:
        """Filter out personal approvals where the creator approved their own PR.

        Args:
            review_info: Dictionary containing review information
            created_by: Username of the PR creator

        Returns:
            Updated review info with personal approvals filtered out if enabled
        """
        # Get config value, defaulting to True if not set (backward compatibility)
        exclude_personal_approvals = getattr(
            self.config, "exclude_personal_approvals", True
        )

        # If personal approval filtering is disabled, return the original data
        if not exclude_personal_approvals:
            return review_info

        approved_by = review_info.get("Approved By", [])
        ever_approved = review_info.get("Ever Approved", [])
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

        # Also filter "Ever Approved" list (case-insensitive)
        filtered_ever_approved = []
        for approver in ever_approved:
            approver_username = (
                approver.split(" (")[0] if " (" in approver else approver
            )

            if approver_username.lower() != created_by.lower():
                filtered_ever_approved.append(approver)

        # Update the review info with filtered data
        updated_review_info = review_info.copy()
        updated_review_info["Approved By"] = filtered_approved_by
        updated_review_info["Approval Count"] = len(filtered_approved_by)
        updated_review_info["Ever Approved"] = filtered_ever_approved
        updated_review_info["Ever Approved Count"] = len(filtered_ever_approved)
        updated_review_info["personal_approvals_filtered"] = personal_approvals_count

        return updated_review_info
