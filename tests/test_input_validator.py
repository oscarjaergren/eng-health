"""
Tests for input validation and sanitization utilities.
"""

import logging

import pytest

from pr_analytics.core.input_validator import InputValidator


@pytest.fixture
def validator():
    """Create InputValidator instance for testing."""
    logger = logging.getLogger("test")
    return InputValidator(logger)


class TestInputValidatorSanitization:
    """Test string sanitization methods."""

    def test_sanitize_none(self, validator):
        """Test sanitizing None returns empty string."""
        assert validator.sanitize_string(None) == ""

    def test_sanitize_normal_string(self, validator):
        """Test sanitizing normal string."""
        assert validator.sanitize_string("Hello World") == "Hello World"
        assert validator.sanitize_string("  spaces  ") == "spaces"

    def test_sanitize_html_escaping(self, validator):
        """Test HTML escaping in sanitization."""
        assert validator.sanitize_string("<script>alert('xss')</script>") == (
            "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
        )
        assert validator.sanitize_string("A & B") == "A &amp; B"
        assert (
            validator.sanitize_string("<div>test</div>")
            == "&lt;div&gt;test&lt;/div&gt;"
        )

    def test_sanitize_length_limit(self, validator):
        """Test length limiting in sanitization."""
        long_string = "a" * 2000
        result = validator.sanitize_string(long_string, max_length=100)
        assert len(result) == 100

    def test_sanitize_dangerous_patterns(self, validator):
        """Test removal of dangerous patterns."""
        dangerous = "onclick=alert('xss')"
        result = validator.sanitize_string(dangerous)
        assert "onclick" not in result.lower() or "=" not in result

    def test_sanitize_numeric_value(self, validator):
        """Test sanitizing numeric values."""
        assert validator.sanitize_string(123) == "123"
        assert validator.sanitize_string(45.67) == "45.67"


class TestInputValidatorEmailValidation:
    """Test email validation."""

    def test_validate_valid_emails(self, validator):
        """Test validation of valid email addresses."""
        assert validator.validate_email("user@example.com") is True
        assert validator.validate_email("test.user@company.co.uk") is True
        assert validator.validate_email("name+tag@domain.com") is True

    def test_validate_invalid_emails(self, validator):
        """Test validation of invalid email addresses."""
        assert validator.validate_email("") is False
        assert validator.validate_email(None) is False
        assert validator.validate_email("not-an-email") is False
        assert validator.validate_email("@example.com") is False
        assert validator.validate_email("user@") is False
        assert validator.validate_email("user@domain") is False

    def test_validate_email_with_spaces(self, validator):
        """Test email validation handles whitespace."""
        assert validator.validate_email("  user@example.com  ") is True


class TestInputValidatorURLValidation:
    """Test URL validation."""

    def test_validate_valid_urls(self, validator):
        """Test validation of valid URLs."""
        assert validator.validate_url("http://example.com") is True
        assert validator.validate_url("https://www.example.com/path") is True
        assert validator.validate_url("https://api.github.com/repos") is True

    def test_validate_invalid_urls(self, validator):
        """Test validation of invalid URLs."""
        assert validator.validate_url("") is False
        assert validator.validate_url(None) is False
        assert validator.validate_url("not-a-url") is False
        assert validator.validate_url("ftp://example.com") is False
        assert validator.validate_url("//example.com") is False

    def test_validate_url_with_spaces(self, validator):
        """Test URL validation handles whitespace."""
        assert validator.validate_url("  https://example.com  ") is True


class TestInputValidatorPRData:
    """Test PR data validation."""

    def test_validate_valid_pr_data(self, validator):
        """Test validation of valid PR data."""
        pr_data = {
            "id": "123",
            "title": "Fix bug in authentication",
            "description": "This PR fixes a critical bug",
            "status": "completed",
        }
        result = validator.validate_pr_data(pr_data)
        assert "id" in result
        assert "title" in result
        assert result["title"] == "Fix bug in authentication"

    def test_validate_missing_required_fields(self, validator):
        """Test validation with missing required fields."""
        pr_data = {"description": "Missing id and title"}
        result = validator.validate_pr_data(pr_data)
        assert "id" in result
        assert "title" in result
        assert result["id"] == ""
        assert result["title"] == ""

    def test_validate_non_dict_pr_data(self, validator):
        """Test validation of non-dict PR data."""
        result = validator.validate_pr_data("not a dict")
        assert result == {}

        result = validator.validate_pr_data(None)
        assert result == {}

    def test_validate_pr_data_sanitizes_strings(self, validator):
        """Test PR data validation sanitizes string fields."""
        pr_data = {
            "id": "123",
            "title": "<script>alert('xss')</script>",
            "description": "Normal description",
        }
        result = validator.validate_pr_data(pr_data)
        assert "<script>" not in result["title"]
        assert "&lt;script&gt;" in result["title"]


class TestInputValidatorConfigData:
    """Test configuration data validation."""

    def test_validate_valid_config(self, validator):
        """Test validation of valid configuration."""
        config = {
            "organization": "my-org",
            "project": "my-project",
            "github_owner": "github-user",
        }
        result = validator.validate_config_data(config)
        assert result["organization"] == "my-org"
        assert result["project"] == "my-project"

    def test_validate_config_with_urls(self, validator):
        """Test validation of config with URLs."""
        config = {
            "base_url": "https://dev.azure.com/org",
            "repositories_url": "https://api.github.com/repos",
        }
        result = validator.validate_config_data(config)
        assert result["base_url"] == "https://dev.azure.com/org"
        assert result["repositories_url"] == "https://api.github.com/repos"

    def test_validate_config_invalid_urls(self, validator):
        """Test validation rejects invalid URLs."""
        config = {"base_url": "not-a-url"}
        result = validator.validate_config_data(config)
        assert result["base_url"] == ""

    def test_validate_config_with_tokens(self, validator):
        """Test validation of config with tokens."""
        config = {
            "token": "my-secret-token",
            "github_token": "ghp_1234567890",
        }
        result = validator.validate_config_data(config)
        assert result["token"] == "my-secret-token"
        assert result["github_token"] == "ghp_1234567890"

    def test_validate_config_non_dict(self, validator):
        """Test validation of non-dict config."""
        result = validator.validate_config_data("not a dict")
        assert result == {}


class TestInputValidatorFilePathValidation:
    """Test file path validation."""

    def test_validate_valid_file_paths(self, validator):
        """Test validation of valid file paths."""
        assert validator.validate_file_path("output/results.csv") is True
        assert validator.validate_file_path("data.json") is True
        assert validator.validate_file_path("logs/app.log") is True

    def test_validate_invalid_extensions(self, validator):
        """Test validation rejects invalid extensions."""
        assert validator.validate_file_path("script.exe") is False
        assert validator.validate_file_path("data.bin") is False
        assert validator.validate_file_path("file.py") is False

    def test_validate_path_traversal_attempts(self, validator):
        """Test validation rejects path traversal."""
        assert validator.validate_file_path("../../../etc/passwd") is False
        assert validator.validate_file_path("..\\..\\Windows\\System32") is False
        assert validator.validate_file_path("/etc/shadow.txt") is False
        assert validator.validate_file_path("C:\\Windows\\system.log") is False

    def test_validate_empty_path(self, validator):
        """Test validation of empty path."""
        assert validator.validate_file_path("") is False
        assert validator.validate_file_path(None) is False


class TestInputValidatorPrivateMethods:
    """Test private validation methods."""

    def test_validate_numeric(self, validator):
        """Test numeric validation."""
        assert validator._validate_numeric(123, "test") == 123
        assert validator._validate_numeric("456", "test") == 456
        assert validator._validate_numeric(78.9, "test") == 78
        assert validator._validate_numeric(None, "test") is None
        assert validator._validate_numeric("not a number", "test") is None

    def test_validate_date(self, validator):
        """Test date validation."""
        assert (
            validator._validate_date("2024-01-01T10:00:00Z", "test")
            == "2024-01-01T10:00:00Z"
        )
        assert validator._validate_date("2024-01-01", "test") == "2024-01-01"
        assert validator._validate_date(None, "test") is None
        assert validator._validate_date("invalid-date", "test") is None

    def test_validate_list(self, validator):
        """Test list validation."""
        assert validator._validate_list([1, 2, 3], "test") == [1, 2, 3]
        assert validator._validate_list(["a", "b"], "test") == ["a", "b"]
        assert validator._validate_list(None, "test") == []
        assert validator._validate_list("not a list", "test") == []

    def test_validate_list_with_dicts(self, validator):
        """Test list validation with dictionary items."""
        test_list = [{"name": "test", "value": 123}]
        result = validator._validate_list(test_list, "test")
        assert len(result) == 1
        assert "name" in result[0]
