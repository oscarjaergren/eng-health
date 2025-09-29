"""Input validation and sanitization utilities for PR analytics."""

import html
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


class InputValidator:
    """Utility class for validating and sanitizing input data."""

    def __init__(self, logger: logging.Logger):
        """
        Initialize the input validator.

        Args:
            logger: Logger instance for error reporting
        """
        self.logger = logger

        # Common patterns for validation
        self.email_pattern = re.compile(
            r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        )
        self.url_pattern = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
        self.safe_string_pattern = re.compile(r"^[a-zA-Z0-9\s\-_.@()]+$")

        # Dangerous patterns to filter out
        self.dangerous_patterns = [
            re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
            re.compile(r"javascript:", re.IGNORECASE),
            re.compile(r"on\w+\s*=", re.IGNORECASE),
            re.compile(r"eval\s*\(", re.IGNORECASE),
            re.compile(r"exec\s*\(", re.IGNORECASE),
        ]

    def sanitize_string(self, value: Any, max_length: int = 1000) -> str:
        """
        Sanitize a string value by removing dangerous content and limiting length.

        Args:
            value: Input value to sanitize
            max_length: Maximum allowed length

        Returns:
            Sanitized string
        """
        if value is None:
            return ""

        # Convert to string and strip whitespace
        sanitized = str(value).strip()

        # Limit length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
            self.logger.warning(f"String truncated to {max_length} characters")

        # HTML escape to prevent XSS
        sanitized = html.escape(sanitized)

        # Remove dangerous patterns
        for pattern in self.dangerous_patterns:
            if pattern.search(sanitized):
                self.logger.warning(
                    f"Dangerous pattern detected and removed: {pattern.pattern}"
                )
                sanitized = pattern.sub("", sanitized)

        return sanitized

    def validate_email(self, email: str) -> bool:
        """
        Validate email address format.

        Args:
            email: Email address to validate

        Returns:
            True if valid email format, False otherwise
        """
        if not email or not isinstance(email, str):
            return False

        return bool(self.email_pattern.match(email.strip()))

    def validate_url(self, url: str) -> bool:
        """
        Validate URL format.

        Args:
            url: URL to validate

        Returns:
            True if valid URL format, False otherwise
        """
        if not url or not isinstance(url, str):
            return False

        return bool(self.url_pattern.match(url.strip()))

    def validate_pr_data(self, pr_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize pull request data.

        Args:
            pr_data: Raw PR data dictionary

        Returns:
            Validated and sanitized PR data
        """
        if not isinstance(pr_data, dict):
            self.logger.error("PR data must be a dictionary")
            return {}

        validated = {}

        # Validate required fields
        required_fields = ["id", "title"]
        for field in required_fields:
            if field not in pr_data:
                self.logger.warning(f"Missing required field: {field}")
                validated[field] = ""
            else:
                validated[field] = self.sanitize_string(pr_data[field])

        # Validate optional string fields
        string_fields = [
            "description",
            "status",
            "createdBy",
            "repository",
            "sourceBranch",
            "targetBranch",
            "mergeStatus",
        ]
        for field in string_fields:
            if field in pr_data:
                validated[field] = self.sanitize_string(pr_data[field])

        # Validate numeric fields
        numeric_fields = ["pullRequestId", "codeReviewId"]
        for field in numeric_fields:
            if field in pr_data:
                validated[field] = self._validate_numeric(pr_data[field], field)

        # Validate date fields
        date_fields = ["creationDate", "closedDate"]
        for field in date_fields:
            if field in pr_data:
                validated[field] = self._validate_date(pr_data[field], field)

        # Validate lists (reviewers, comments, etc.)
        list_fields = ["reviewers", "comments", "workItems"]
        for field in list_fields:
            if field in pr_data:
                validated[field] = self._validate_list(pr_data[field], field)

        return validated

    def validate_config_data(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate configuration data.

        Args:
            config_data: Configuration dictionary

        Returns:
            Validated configuration data
        """
        if not isinstance(config_data, dict):
            self.logger.error("Config data must be a dictionary")
            return {}

        validated = {}

        # Validate organization/owner names
        if "organization" in config_data:
            org = self.sanitize_string(config_data["organization"], 100)
            if self.safe_string_pattern.match(org):
                validated["organization"] = org
            else:
                self.logger.error("Invalid organization name format")
                validated["organization"] = ""

        if "github_owner" in config_data:
            owner = self.sanitize_string(config_data["github_owner"], 100)
            if self.safe_string_pattern.match(owner):
                validated["github_owner"] = owner
            else:
                self.logger.error("Invalid GitHub owner name format")
                validated["github_owner"] = ""

        # Validate project names
        if "project" in config_data:
            project = self.sanitize_string(config_data["project"], 100)
            if self.safe_string_pattern.match(project):
                validated["project"] = project
            else:
                self.logger.error("Invalid project name format")
                validated["project"] = ""

        # Validate URLs
        url_fields = ["base_url", "repositories_url"]
        for field in url_fields:
            if field in config_data:
                url = config_data[field]
                if self.validate_url(url):
                    validated[field] = url
                else:
                    self.logger.error(f"Invalid URL format for {field}: {url}")
                    validated[field] = ""

        # Validate tokens (should be non-empty strings)
        token_fields = ["token", "github_token"]
        for field in token_fields:
            if field in config_data:
                token = config_data[field]
                if isinstance(token, str) and len(token.strip()) > 0:
                    validated[field] = token.strip()
                else:
                    self.logger.error(f"Invalid token format for {field}")
                    validated[field] = ""

        return validated

    def _validate_numeric(self, value: Any, field_name: str) -> Optional[int]:
        """
        Validate numeric field.

        Args:
            value: Value to validate
            field_name: Name of the field for logging

        Returns:
            Validated numeric value or None
        """
        if value is None:
            return None

        try:
            if isinstance(value, (int, float)):
                return int(value)
            elif isinstance(value, str):
                return int(value.strip())
            else:
                self.logger.warning(
                    f"Invalid numeric type for {field_name}: {type(value)}"
                )
                return None
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert {field_name} to numeric: {value}")
            return None

    def _validate_date(self, value: Any, field_name: str) -> Optional[str]:
        """
        Validate date field.

        Args:
            value: Value to validate
            field_name: Name of the field for logging

        Returns:
            Validated date string or None
        """
        if value is None:
            return None

        if isinstance(value, str):
            # Try to parse common date formats
            date_formats = [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]

            for fmt in date_formats:
                try:
                    datetime.strptime(value, fmt)
                    return value  # Valid date string
                except ValueError:
                    continue

            self.logger.warning(f"Invalid date format for {field_name}: {value}")
            return None

        elif isinstance(value, datetime):
            return value.isoformat()

        else:
            self.logger.warning(f"Invalid date type for {field_name}: {type(value)}")
            return None

    def _validate_list(self, value: Any, field_name: str) -> List[Any]:
        """
        Validate list field.

        Args:
            value: Value to validate
            field_name: Name of the field for logging

        Returns:
            Validated list
        """
        if value is None:
            return []

        if isinstance(value, list):
            # Sanitize each item in the list
            sanitized_list = []
            for item in value:
                if isinstance(item, dict):
                    # For dictionary items, sanitize string values
                    sanitized_item = {}
                    for k, v in item.items():
                        if isinstance(v, str):
                            sanitized_item[k] = self.sanitize_string(v)
                        else:
                            sanitized_item[k] = v
                    sanitized_list.append(sanitized_item)
                elif isinstance(item, str):
                    sanitized_list.append(self.sanitize_string(item))
                else:
                    sanitized_list.append(item)
            return sanitized_list

        else:
            self.logger.warning(f"Expected list for {field_name}, got {type(value)}")
            return []

    def validate_file_path(self, file_path: str) -> bool:
        """
        Validate file path for security.

        Args:
            file_path: File path to validate

        Returns:
            True if path is safe, False otherwise
        """
        if not file_path or not isinstance(file_path, str):
            return False

        # Check for path traversal attempts
        dangerous_patterns = ["../", "..\\", "/etc/", "/proc/", "C:\\Windows\\"]
        for pattern in dangerous_patterns:
            if pattern in file_path:
                self.logger.warning(f"Dangerous path pattern detected: {pattern}")
                return False

        # Only allow certain file extensions
        allowed_extensions = [".xlsx", ".csv", ".json", ".txt", ".log"]
        if not any(file_path.lower().endswith(ext) for ext in allowed_extensions):
            self.logger.warning(f"File extension not allowed: {file_path}")
            return False

        return True
