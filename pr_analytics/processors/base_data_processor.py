"""Base data processing utilities shared between different platforms."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.input_validator import InputValidator


class BaseDataProcessor:
    """Base class for processing pull request data from different platforms."""

    def __init__(self, logger: logging.Logger, config=None):
        """
        Initialize the base data processor.

        Args:
            logger: Logger instance for error reporting
            config: Configuration object (optional)
        """
        self.logger = logger
        self.config = config
        self.validator = InputValidator(logger)

        # Canonical IAC patterns used across all platform processors
        self.iac_keywords = [
            "terraform",
            "tf",
            "bicep",
            "arm template",
            "cloudformation",
            "cfn",
            "infrastructure",
            "infra",
            "deployment",
            "deploy",
            "pipeline",
            "yaml",
            "yml",
            "docker",
            "dockerfile",
            "kubernetes",
            "k8s",
            "helm",
            "ansible",
            "puppet",
            "chef",
            "pulumi",
            "cdk",
            "azure resource manager",
            "arm",
            "azuredeploy",
            "ci/cd",
        ]

        self.iac_file_patterns = [
            ".tf", ".bicep", ".yaml", ".yml", "dockerfile", ".json",
        ]

        self.iac_regex_patterns = [
            r"terraform",
            r"\.tf$",
            r"infrastructure",
            r"iac",
            r"cloudformation",
            r"bicep",
            r"helm",
            r"kubernetes",
            r"k8s",
        ]

        # System identity patterns (platform-agnostic)
        self.system_identity_patterns = [
            r"vstfs:",
            r"github-actions",
            r"dependabot",
            r"renovate",
            r"bot$",
            r"automation",
            r"system",
            r"service",
        ]

    def is_system_identity(self, identity_name: str) -> bool:
        """
        Check if an identity is a system/bot identity that should be filtered out.

        Args:
            identity_name: Name or identifier of the identity

        Returns:
            bool: True if system identity, False otherwise
        """
        if not identity_name or identity_name == "Unknown":
            return True

        identity_lower = identity_name.lower()

        # Check against system identity patterns
        for pattern in self.system_identity_patterns:
            if re.search(pattern, identity_lower):
                return True

        # Platform-specific checks
        return self._is_platform_system_identity(identity_name)

    def _is_platform_system_identity(self, identity_name: str) -> bool:
        """
        Platform-specific system identity check (to be overridden by subclasses).

        Args:
            identity_name: Name or identifier of the identity

        Returns:
            bool: True if platform-specific system identity, False otherwise
        """
        return False

    def is_iac_related(
        self, pr_title: str, pr_description: str = "", file_changes: List[str] = None
    ) -> bool:
        """
        Check if a PR is related to Infrastructure as Code (IAC).

        Args:
            pr_title: Title of the pull request
            pr_description: Description of the pull request
            file_changes: List of changed files (optional)

        Returns:
            bool: True if IAC-related, False otherwise
        """
        # Combine title and description for checking
        text_to_check = f"{pr_title} {pr_description}".lower()

        # Check text content against canonical keyword list
        for keyword in self.iac_keywords:
            if keyword in text_to_check:
                return True

        # Check text content against regex patterns
        for pattern in self.iac_regex_patterns:
            if re.search(pattern, text_to_check):
                return True

        # Check file changes if available
        if file_changes:
            for file_path in file_changes:
                file_lower = file_path.lower()
                for pattern in self.iac_file_patterns:
                    if pattern in file_lower:
                        return True
                for pattern in self.iac_regex_patterns:
                    if re.search(pattern, file_lower):
                        return True

        return False

    def extract_user_name(self, user_data: Any) -> str:
        """
        Extract clean user name from various user data formats.

        Args:
            user_data: User data in various formats (dict, string, etc.)

        Returns:
            str: Clean user name or 'Unknown'
        """
        if not user_data:
            return "Unknown"

        # Handle different data formats
        if isinstance(user_data, dict):
            # Try common user name fields
            name_fields = ["displayName", "name", "login", "uniqueName", "email"]
            for field in name_fields:
                if field in user_data and user_data[field]:
                    name = str(user_data[field]).strip()
                    if name and not self.is_system_identity(name):
                        return self.validator.sanitize_string(name, 100)

        elif isinstance(user_data, str):
            name = user_data.strip()
            if name and not self.is_system_identity(name):
                return self.validator.sanitize_string(name, 100)

        return "Unknown"

    def _filter_personal_approvals_internal(
        self, reviewer_info: Dict[str, Any], created_by: str
    ) -> Dict[str, Any]:
        """
        Internal method to filter out personal approvals (self-approvals) from review analytics.

        Args:
            reviewer_info: Dictionary containing reviewer information
            created_by: Name of the PR creator

        Returns:
            Dict containing filtered review information
        """
        # This is a placeholder implementation - actual filtering logic would be more complex
        filtered_info = reviewer_info.copy()
        filtered_info["personal_approvals_filtered"] = 0
        return filtered_info

    def _safe_get_nested_value(
        self, data: Any, keys: List[str], default: Any = None
    ) -> Any:
        """
        Safely get nested value from dictionary structure.

        Args:
            data: Dictionary or nested structure to search
            keys: List of keys to traverse
            default: Default value if key path not found

        Returns:
            Value at key path or default
        """
        if not data or not isinstance(data, dict):
            return default

        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default

        return current

    def _validate_pr_data(self, pr_data: Any) -> bool:
        """
        Validate pull request data structure.

        Args:
            pr_data: Pull request data to validate

        Returns:
            bool: True if valid, False otherwise
        """
        if not pr_data or not isinstance(pr_data, dict):
            return False

        # Check for required fields (basic validation)
        required_fields = ["id", "title"]
        for field in required_fields:
            if field not in pr_data:
                return False

        return True

    def _sanitize_string(self, text: str, max_length: int = 500) -> str:
        """
        Sanitize string input for safe processing.

        Args:
            text: Text to sanitize
            max_length: Maximum allowed length

        Returns:
            str: Sanitized text
        """
        if not text:
            return ""

        return self.validator.sanitize_string(text, max_length)

    def extract_date_string(self, date_data: Any) -> str:
        """
        Extract and format date string from various date formats.

        Args:
            date_data: Date data in various formats

        Returns:
            str: Formatted date string or empty string
        """
        if not date_data:
            return ""

        try:
            if isinstance(date_data, str):
                # Try to parse and reformat
                date_formats = [
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                ]

                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(date_data, fmt)
                        return parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                # If no format matches, return as-is if it looks like a date
                if re.match(r"\d{4}-\d{2}-\d{2}", date_data):
                    return date_data

            elif isinstance(date_data, datetime):
                return date_data.strftime("%Y-%m-%d %H:%M:%S")

        except Exception as e:
            self.logger.warning(f"Error parsing date: {e}")

        return ""

    def calculate_metrics(self, pr_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate common metrics for a pull request.

        Args:
            pr_data: Pull request data dictionary

        Returns:
            Dict containing calculated metrics
        """
        metrics = {
            "approval_count": 0,
            "total_comments": 0,
            "total_reviewers": 0,
            "unique_commenters": set(),
            "review_duration_hours": 0,
        }

        # Count approvals
        if "approved_by" in pr_data and pr_data["approved_by"]:
            if isinstance(pr_data["approved_by"], list):
                metrics["approval_count"] = len(pr_data["approved_by"])
            elif isinstance(pr_data["approved_by"], str):
                try:
                    import json as json_module
                    approvers = json_module.loads(pr_data["approved_by"])
                    if isinstance(approvers, list):
                        metrics["approval_count"] = len(approvers)
                except (json_module.JSONDecodeError, TypeError):
                    pass

        # Count comments and reviewers
        if "comments" in pr_data and pr_data["comments"]:
            if isinstance(pr_data["comments"], list):
                metrics["total_comments"] = len(pr_data["comments"])
                for comment in pr_data["comments"]:
                    if isinstance(comment, dict) and "author" in comment:
                        author = self.extract_user_name(comment["author"])
                        if author != "Unknown":
                            metrics["unique_commenters"].add(author)

        # Count unique reviewers
        reviewers = set()
        if "reviewers" in pr_data and pr_data["reviewers"]:
            if isinstance(pr_data["reviewers"], list):
                for reviewer in pr_data["reviewers"]:
                    reviewer_name = self.extract_user_name(reviewer)
                    if reviewer_name != "Unknown":
                        reviewers.add(reviewer_name)

        metrics["total_reviewers"] = len(reviewers)
        metrics["unique_commenters"] = len(metrics["unique_commenters"])

        # Calculate review duration
        created_date = pr_data.get("created_date", "")
        closed_date = pr_data.get("closed_date", "")

        if created_date and closed_date:
            try:
                created = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
                closed = datetime.fromisoformat(closed_date.replace("Z", "+00:00"))
                duration = closed - created
                metrics["review_duration_hours"] = round(
                    duration.total_seconds() / 3600, 2
                )
            except Exception as e:
                self.logger.debug(f"Error calculating review duration: {e}")

        return metrics

    def normalize_pr_status(self, status: str, platform: str) -> str:
        """
        Normalize PR status across different platforms.

        Args:
            status: Original status string
            platform: Platform name ('azure_devops' or 'github')

        Returns:
            str: Normalized status
        """
        if not status:
            return "unknown"

        status_lower = status.lower()

        # Common status mappings
        if platform == "azure_devops":
            status_map = {
                "completed": "merged",
                "abandoned": "closed",
                "active": "open",
            }
        elif platform == "github":
            status_map = {"merged": "merged", "closed": "closed", "open": "open"}
        else:
            status_map = {}

        return status_map.get(status_lower, status_lower)

    def filter_personal_approvals(self, pr_data: Dict[str, Any]) -> bool:
        """
        Check if PR should be filtered out due to personal approval patterns.

        Args:
            pr_data: Pull request data dictionary

        Returns:
            bool: True if should be filtered out, False otherwise
        """
        author = self.extract_user_name(pr_data.get("created_by", ""))
        approved_by = pr_data.get("approved_by", [])

        if not approved_by or not author or author == "Unknown":
            return False

        # Convert approved_by to list if it's a string
        if isinstance(approved_by, str):
            try:
                import json as json_module
                approved_by = json_module.loads(approved_by)
            except (json_module.JSONDecodeError, TypeError):
                return False

        if not isinstance(approved_by, list):
            return False

        # Check if author approved their own PR (case-insensitive)
        for approver in approved_by:
            approver_name = self.extract_user_name(approver)
            if approver_name.lower() == author.lower():
                return True

        return False

    def extract_repository_info(
        self, pr_data: Dict[str, Any], platform: str
    ) -> Dict[str, str]:
        """
        Extract repository information from PR data.

        Args:
            pr_data: Pull request data dictionary
            platform: Platform name

        Returns:
            Dict containing repository information
        """
        repo_info = {"name": "Unknown", "id": "", "full_name": ""}

        if platform == "azure_devops":
            if "repository" in pr_data:
                repo = pr_data["repository"]
                if isinstance(repo, dict):
                    repo_info["name"] = repo.get("name", "Unknown")
                    repo_info["id"] = repo.get("id", "")
                elif isinstance(repo, str):
                    repo_info["name"] = repo

            repo_info["full_name"] = repo_info["name"]

        elif platform == "github":
            if "base" in pr_data and "repo" in pr_data["base"]:
                repo = pr_data["base"]["repo"]
                repo_info["name"] = repo.get("name", "Unknown")
                repo_info["id"] = str(repo.get("id", ""))
                repo_info["full_name"] = repo.get("full_name", repo_info["name"])
            elif "repository_name" in pr_data:
                repo_info["name"] = pr_data["repository_name"]
                repo_info["full_name"] = pr_data.get(
                    "repository_full_name", repo_info["name"]
                )
                repo_info["id"] = str(pr_data.get("repository_id", ""))

        return repo_info

    def validate_and_sanitize_pr(
        self, pr_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate and sanitize pull request data.

        Args:
            pr_data: Raw pull request data

        Returns:
            Validated and sanitized PR data or None if invalid
        """
        if not isinstance(pr_data, dict):
            self.logger.warning("Invalid PR data format - not a dictionary")
            return None

        # Use input validator for comprehensive validation
        validated_pr = self.validator.validate_pr_data(pr_data)

        if not validated_pr.get("id") and not validated_pr.get("pullRequestId"):
            self.logger.warning("PR missing required ID field")
            return None

        if not validated_pr.get("title"):
            self.logger.warning("PR missing title field")
            return None

        return validated_pr

    def log_processing_stats(
        self, total_prs: int, filtered_prs: int, excluded_counts: Dict[str, int]
    ):
        """
        Log processing statistics.

        Args:
            total_prs: Total number of PRs processed
            filtered_prs: Number of PRs after filtering
            excluded_counts: Dictionary of exclusion reasons and counts
        """
        self.logger.info("Processing complete:")
        self.logger.info(f"  Total PRs processed: {total_prs}")
        self.logger.info(f"  PRs after filtering: {filtered_prs}")

        for reason, count in excluded_counts.items():
            if count > 0:
                self.logger.info(f"  Excluded ({reason}): {count}")

        if total_prs > 0:
            retention_rate = (filtered_prs / total_prs) * 100
            self.logger.info(f"  Retention rate: {retention_rate:.1f}%")
