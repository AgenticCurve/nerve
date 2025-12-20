"""Tests for ToolIDMapper."""

import pytest

from nerve.core.transforms.tool_id_mapper import ToolIDMapper


class TestToolIDMapper:
    """Tests for bidirectional tool ID mapping."""

    def test_to_anthropic_id_creates_mapping(self):
        """to_anthropic_id should create a new mapping."""
        mapper = ToolIDMapper()

        anthropic_id = mapper.to_anthropic_id("call_abc123")

        assert anthropic_id.startswith("toolu_")
        # Should be able to map back
        assert mapper.to_openai_id(anthropic_id) == "call_abc123"

    def test_to_anthropic_id_reuses_mapping(self):
        """Same OpenAI ID should always return the same Anthropic ID."""
        mapper = ToolIDMapper()

        id1 = mapper.to_anthropic_id("call_abc")
        id2 = mapper.to_anthropic_id("call_abc")

        assert id1 == id2

    def test_multiple_ids_are_unique(self):
        """Different OpenAI IDs should get unique Anthropic IDs."""
        mapper = ToolIDMapper()

        id1 = mapper.to_anthropic_id("call_1")
        id2 = mapper.to_anthropic_id("call_2")
        id3 = mapper.to_anthropic_id("call_3")

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3

    def test_to_openai_id_requires_prior_mapping(self):
        """to_openai_id should raise KeyError for unknown IDs."""
        mapper = ToolIDMapper()

        with pytest.raises(KeyError, match="Unknown Anthropic tool ID"):
            mapper.to_openai_id("toolu_unknown")

    def test_to_openai_id_returns_correct_id(self):
        """to_openai_id should return the original OpenAI ID."""
        mapper = ToolIDMapper()

        # Create a mapping
        anthropic_id = mapper.to_anthropic_id("call_xyz")

        # Should get back the original
        openai_id = mapper.to_openai_id(anthropic_id)

        assert openai_id == "call_xyz"

    def test_register_mapping(self):
        """register_mapping should create explicit bidirectional mapping."""
        mapper = ToolIDMapper()

        mapper.register_mapping("call_my_id", "toolu_my_id")

        assert mapper.to_anthropic_id("call_my_id") == "toolu_my_id"
        assert mapper.to_openai_id("toolu_my_id") == "call_my_id"

    def test_has_anthropic_id(self):
        """has_anthropic_id should check for mapping existence."""
        mapper = ToolIDMapper()

        assert mapper.has_anthropic_id("toolu_xyz") is False

        mapper.register_mapping("call_abc", "toolu_xyz")

        assert mapper.has_anthropic_id("toolu_xyz") is True
        assert mapper.has_anthropic_id("toolu_other") is False

    def test_has_openai_id(self):
        """has_openai_id should check for mapping existence."""
        mapper = ToolIDMapper()

        assert mapper.has_openai_id("call_abc") is False

        mapper.register_mapping("call_abc", "toolu_xyz")

        assert mapper.has_openai_id("call_abc") is True
        assert mapper.has_openai_id("call_other") is False

    def test_anthropic_id_format(self):
        """Anthropic IDs should follow the toolu_<timestamp>_<counter> format."""
        mapper = ToolIDMapper()

        id1 = mapper.to_anthropic_id("call_1")

        parts = id1.split("_")
        assert parts[0] == "toolu"
        # Second part should be a timestamp (large number)
        assert int(parts[1]) > 1000000000000  # After year 2001
        # Third part should be the counter
        assert parts[2] == "1"

    def test_counter_increments(self):
        """Counter should increment for each new mapping."""
        mapper = ToolIDMapper()

        id1 = mapper.to_anthropic_id("call_1")
        id2 = mapper.to_anthropic_id("call_2")

        counter1 = int(id1.split("_")[2])
        counter2 = int(id2.split("_")[2])

        assert counter2 == counter1 + 1

    def test_request_scoped_usage(self):
        """Each mapper instance should be independent (request-scoped)."""
        mapper1 = ToolIDMapper()
        mapper2 = ToolIDMapper()

        # Create mapping in mapper1
        anthropic_id = mapper1.to_anthropic_id("call_from_mapper1")

        # mapper1 can reverse lookup its own ID
        assert mapper1.to_openai_id(anthropic_id) == "call_from_mapper1"
        assert mapper1.has_openai_id("call_from_mapper1")

        # mapper2 should NOT have this mapping - proves independence
        # Even if the anthropic_id happens to be the same (same timestamp),
        # mapper2 shouldn't have a mapping for it
        assert not mapper2.has_anthropic_id(anthropic_id)

        # Key test: mapper2 cannot reverse-lookup mapper1's ID
        with pytest.raises(KeyError):
            mapper2.to_openai_id(anthropic_id)

    def test_error_message_is_helpful(self):
        """Error message should help debug mapping issues."""
        mapper = ToolIDMapper()

        try:
            mapper.to_openai_id("toolu_missing")
            pytest.fail("Expected KeyError")
        except KeyError as e:
            error_msg = str(e)
            assert "toolu_missing" in error_msg
            assert "never mapped" in error_msg.lower() or "tool_use" in error_msg.lower()
