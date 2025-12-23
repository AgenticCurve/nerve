"""Tests for name validation."""

import pytest

from nerve.core.validation import is_valid_name, validate_name


class TestValidateName:
    """Tests for validate_name function."""

    def test_valid_simple_name(self):
        """Simple lowercase name should be valid."""
        validate_name("myproject", "server")  # Should not raise

    def test_valid_name_with_numbers(self):
        """Name with numbers should be valid."""
        validate_name("project123", "server")

    def test_valid_name_with_dashes(self):
        """Name with dashes should be valid."""
        validate_name("my-project", "node")
        validate_name("my-cool-project-1", "node")

    def test_valid_single_char(self):
        """Single character name should be valid."""
        validate_name("a", "server")
        validate_name("1", "server")

    def test_invalid_uppercase(self):
        """Uppercase should be rejected."""
        with pytest.raises(ValueError, match="lowercase"):
            validate_name("MyProject", "server")

    def test_invalid_spaces(self):
        """Spaces should be rejected."""
        with pytest.raises(ValueError, match="lowercase"):
            validate_name("my project", "server")

    def test_invalid_underscore(self):
        """Underscores should be rejected."""
        with pytest.raises(ValueError, match="lowercase"):
            validate_name("my_project", "server")

    def test_invalid_starts_with_dash(self):
        """Cannot start with dash."""
        with pytest.raises(ValueError, match="cannot start or end with dash"):
            validate_name("-project", "server")

    def test_invalid_ends_with_dash(self):
        """Cannot end with dash."""
        with pytest.raises(ValueError, match="cannot start or end with dash"):
            validate_name("project-", "server")

    def test_invalid_empty(self):
        """Empty name should be rejected."""
        with pytest.raises(ValueError, match="required"):
            validate_name("", "server")

    def test_invalid_too_long(self):
        """Name over 32 chars should be rejected."""
        with pytest.raises(ValueError, match="32 characters"):
            validate_name("a" * 33, "server")

    def test_valid_max_length(self):
        """Exactly 32 chars should be valid."""
        validate_name("a" * 32, "server")

    def test_error_message_includes_entity(self):
        """Error message should include the entity type."""
        with pytest.raises(ValueError, match="Server"):
            validate_name("", "server")
        with pytest.raises(ValueError, match="Node"):
            validate_name("", "node")


class TestIsValidName:
    """Tests for is_valid_name function."""

    def test_valid_returns_true(self):
        """Valid names should return True."""
        assert is_valid_name("myproject") is True
        assert is_valid_name("my-project") is True
        assert is_valid_name("a") is True

    def test_invalid_returns_false(self):
        """Invalid names should return False."""
        assert is_valid_name("") is False
        assert is_valid_name("MyProject") is False
        assert is_valid_name("-project") is False
        assert is_valid_name("a" * 33) is False
