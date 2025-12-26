"""
Tests for safe data parsing utilities.
"""

from pr_analytics.core.safe_data_parser import (
    safe_count_items,
    safe_parse_dict,
    safe_parse_list,
    safe_parse_with_fallback,
)


class TestSafeParseList:
    """Test safe_parse_list function."""

    def test_parse_empty_string(self):
        """Test parsing empty string returns empty list."""
        assert safe_parse_list("") == []
        assert safe_parse_list("[]") == []
        assert safe_parse_list("None") == []

    def test_parse_none(self):
        """Test parsing None returns empty list."""
        assert safe_parse_list(None) == []

    def test_parse_existing_list(self):
        """Test parsing existing list returns same list."""
        test_list = ["a", "b", "c"]
        assert safe_parse_list(test_list) == test_list

    def test_parse_string_representation(self):
        """Test parsing string representation of list."""
        assert safe_parse_list("['a', 'b', 'c']") == ["a", "b", "c"]
        assert safe_parse_list('["x", "y", "z"]') == ["x", "y", "z"]
        assert safe_parse_list("[1, 2, 3]") == [1, 2, 3]

    def test_parse_json_format(self):
        """Test parsing JSON format list."""
        assert safe_parse_list('["item1", "item2"]') == ["item1", "item2"]
        assert safe_parse_list("[1, 2, 3, 4]") == [1, 2, 3, 4]

    def test_parse_comma_separated(self):
        """Test parsing comma-separated values."""
        assert safe_parse_list("a, b, c") == ["a", "b", "c"]
        # Quoted items with commas are treated as having special chars, returns empty
        assert safe_parse_list("item1, item2, item3") == ["item1", "item2", "item3"]

    def test_parse_invalid_format(self):
        """Test parsing invalid format returns empty list."""
        assert safe_parse_list("not a list") == []
        assert safe_parse_list("{a: b}") == []
        assert safe_parse_list("(1, 2, 3)") == []

    def test_parse_non_string_non_list(self):
        """Test parsing non-string, non-list returns empty list."""
        assert safe_parse_list(123) == []
        assert safe_parse_list({"key": "value"}) == []
        assert safe_parse_list(True) == []


class TestSafeParseDict:
    """Test safe_parse_dict function."""

    def test_parse_empty_string(self):
        """Test parsing empty string returns empty dict."""
        assert safe_parse_dict("") == {}
        assert safe_parse_dict("{}") == {}
        assert safe_parse_dict("None") == {}

    def test_parse_none(self):
        """Test parsing None returns empty dict."""
        assert safe_parse_dict(None) == {}

    def test_parse_existing_dict(self):
        """Test parsing existing dict returns same dict."""
        test_dict = {"a": 1, "b": 2}
        assert safe_parse_dict(test_dict) == test_dict

    def test_parse_string_representation(self):
        """Test parsing string representation of dict."""
        assert safe_parse_dict("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}
        assert safe_parse_dict('{"x": "y"}') == {"x": "y"}

    def test_parse_json_format(self):
        """Test parsing JSON format dict."""
        assert safe_parse_dict('{"key": "value"}') == {"key": "value"}
        assert safe_parse_dict('{"num": 123, "bool": true}') == {
            "num": 123,
            "bool": True,
        }

    def test_parse_invalid_format(self):
        """Test parsing invalid format returns empty dict."""
        assert safe_parse_dict("not a dict") == {}
        assert safe_parse_dict("[1, 2, 3]") == {}
        assert safe_parse_dict("invalid json") == {}

    def test_parse_non_string_non_dict(self):
        """Test parsing non-string, non-dict returns empty dict."""
        assert safe_parse_dict(123) == {}
        assert safe_parse_dict(["a", "b"]) == {}
        assert safe_parse_dict(True) == {}


class TestSafeCountItems:
    """Test safe_count_items function."""

    def test_count_empty(self):
        """Test counting empty list."""
        assert safe_count_items("") == 0
        assert safe_count_items("[]") == 0
        assert safe_count_items(None) == 0

    def test_count_list(self):
        """Test counting items in list."""
        assert safe_count_items(["a", "b", "c"]) == 3
        assert safe_count_items([1, 2, 3, 4, 5]) == 5

    def test_count_string_representation(self):
        """Test counting items in string representation."""
        assert safe_count_items("['a', 'b', 'c']") == 3
        assert safe_count_items("[1, 2, 3, 4]") == 4

    def test_count_comma_separated(self):
        """Test counting comma-separated values."""
        assert safe_count_items("a, b, c, d") == 4
        assert safe_count_items("item1, item2") == 2


class TestSafeParseWithFallback:
    """Test safe_parse_with_fallback function."""

    def test_parse_empty_returns_fallback(self):
        """Test parsing empty values returns fallback."""
        assert safe_parse_with_fallback("", "default") == "default"
        assert safe_parse_with_fallback("None", "default") == "default"
        assert safe_parse_with_fallback("null", 0) == 0
        assert safe_parse_with_fallback(None, []) == []

    def test_parse_valid_string(self):
        """Test parsing valid string representations."""
        assert safe_parse_with_fallback("123", 0) == 123
        assert safe_parse_with_fallback("'text'", "default") == "text"
        assert safe_parse_with_fallback("[1, 2, 3]", []) == [1, 2, 3]
        assert safe_parse_with_fallback('{"key": "value"}', {}) == {"key": "value"}

    def test_parse_json_format(self):
        """Test parsing JSON format."""
        assert safe_parse_with_fallback('{"a": 1}', {}) == {"a": 1}
        assert safe_parse_with_fallback("[1, 2, 3]", []) == [1, 2, 3]
        assert safe_parse_with_fallback("true", False) is True

    def test_parse_non_string_returns_value(self):
        """Test parsing non-string returns the value itself."""
        assert safe_parse_with_fallback(123, 0) == 123
        assert safe_parse_with_fallback([1, 2], []) == [1, 2]
        assert safe_parse_with_fallback({"a": 1}, {}) == {"a": 1}

    def test_parse_invalid_returns_fallback(self):
        """Test parsing invalid format returns fallback."""
        assert safe_parse_with_fallback("invalid", "default") == "default"
        assert safe_parse_with_fallback("{not json}", {}) == {}
        assert safe_parse_with_fallback("[broken", []) == []

    def test_fallback_none_default(self):
        """Test fallback with None as default."""
        assert safe_parse_with_fallback("", None) is None
        assert safe_parse_with_fallback("invalid", None) is None
