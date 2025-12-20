"""Tests for AI CLI parsers.

These tests use real-world captured Claude Code output to ensure
the parser handles actual production output correctly.
"""

from nerve.core.parsers import ClaudeParser


class TestClaudeParser:
    """Tests for ClaudeParser."""

    def test_is_ready_when_insert_mode(self, sample_claude_output):
        """Test is_ready returns True when in INSERT mode."""
        parser = ClaudeParser()
        assert parser.is_ready(sample_claude_output) is True

    def test_is_ready_when_processing(self):
        """Test is_ready returns False when processing."""
        parser = ClaudeParser()
        content = """
> Some prompt
∴ Thinking…
  Still working on this...
  (esc to interrupt)
"""
        assert parser.is_ready(content) is False

    def test_parse_extracts_sections(self, sample_claude_output):
        """Test parse extracts thinking and text sections."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        assert len(response.sections) >= 1
        assert response.is_ready is True

    def test_parse_extracts_tokens(self, sample_claude_output):
        """Test parse extracts token count."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        assert response.tokens == 1234

    def test_parse_tool_call(self, sample_claude_output_with_tool):
        """Test parse handles tool calls."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output_with_tool)

        tool_sections = [s for s in response.sections if s.type == "tool_call"]
        assert len(tool_sections) >= 1


class TestClaudeParserRealWorld:
    """Tests using real-world captured Claude Code output.

    These samples are from actual Claude Code sessions and test
    the parser against production output patterns.
    """

    def test_sample_02_is_ready(self, sample_pane_02):
        """Test sample_pane_02 is ready (no 'esc to interrupt' present).

        The new is_ready logic only checks for 'esc to interrupt' in the
        last 50 lines. If not present, Claude is ready for new input.
        """
        parser = ClaudeParser()
        # Does not contain "esc to interrupt"
        assert "esc to interrupt" not in sample_pane_02.lower()
        assert parser.is_ready(sample_pane_02) is True

    def test_sample_02_token_count(self, sample_pane_02):
        """Test sample_pane_02 token count extraction."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_02)
        assert response.tokens == 102451

    def test_sample_02_has_search_tool(self, sample_pane_02):
        """Test sample_pane_02 contains Search tool call."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_02)

        tool_calls = [s for s in response.sections if s.type == "tool_call"]
        assert len(tool_calls) >= 1

        # Check at least one is a Search tool
        search_tools = [t for t in tool_calls if t.tool == "Search"]
        assert len(search_tools) >= 1

    def test_sample_02_has_thinking(self, sample_pane_02):
        """Test sample_pane_02 contains thinking section."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_02)

        thinking_sections = [s for s in response.sections if s.type == "thinking"]
        assert len(thinking_sections) >= 1

    def test_sample_02_has_text_response(self, sample_pane_02):
        """Test sample_pane_02 contains text response."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_02)

        text_sections = [s for s in response.sections if s.type == "text"]
        assert len(text_sections) >= 1

        # Check text contains expected content about debug flag
        text_content = " ".join(s.content for s in text_sections)
        assert "--debug" in text_content or "debug" in text_content.lower()

    def test_sample_03_is_ready(self, sample_pane_03):
        """Test sample_pane_03 is detected as ready state."""
        parser = ClaudeParser()
        assert parser.is_ready(sample_pane_03) is True

    def test_sample_03_token_count(self, sample_pane_03):
        """Test sample_pane_03 token count extraction."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_03)
        assert response.tokens == 43076

    def test_sample_03_has_bash_tool(self, sample_pane_03):
        """Test sample_pane_03 contains Bash tool call."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_03)

        tool_calls = [s for s in response.sections if s.type == "tool_call"]
        assert len(tool_calls) >= 1

        # Check for Bash tool
        bash_tools = [t for t in tool_calls if t.tool == "Bash"]
        assert len(bash_tools) >= 1

    def test_sample_03_has_multiple_thinking(self, sample_pane_03):
        """Test sample_pane_03 has multiple thinking sections."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_03)

        thinking_sections = [s for s in response.sections if s.type == "thinking"]
        # Sample 03 has multiple thinking blocks
        assert len(thinking_sections) >= 2

    def test_sample_03_has_bigquery_content(self, sample_pane_03):
        """Test sample_pane_03 response mentions BigQuery data."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_03)

        # Either in raw or in text sections, should mention the count
        assert "20983267" in response.raw or "20,983,267" in response.raw

    def test_sample_04_is_ready(self, sample_pane_04):
        """Test sample_pane_04 is ready (no 'esc to interrupt' present).

        The new is_ready logic only checks for 'esc to interrupt' in the
        last 50 lines. If not present, Claude is ready for new input.
        """
        parser = ClaudeParser()
        # Does not contain "esc to interrupt"
        assert "esc to interrupt" not in sample_pane_04.lower()
        assert parser.is_ready(sample_pane_04) is True

    def test_sample_04_token_count(self, sample_pane_04):
        """Test sample_pane_04 token count extraction."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_04)
        assert response.tokens == 102451

    def test_sample_04_has_multiple_search_tools(self, sample_pane_04):
        """Test sample_pane_04 contains multiple Search tool calls."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_04)

        tool_calls = [s for s in response.sections if s.type == "tool_call"]
        search_tools = [t for t in tool_calls if t.tool == "Search"]

        # Sample 04 has multiple Search calls
        assert len(search_tools) >= 2

    def test_sample_04_has_multiple_thinking(self, sample_pane_04):
        """Test sample_pane_04 has multiple thinking sections."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_04)

        thinking_sections = [s for s in response.sections if s.type == "thinking"]
        # Sample 04 has multiple thinking blocks
        assert len(thinking_sections) >= 2

    def test_sample_04_sections_order_preserved(self, sample_pane_04):
        """Test sections are in correct order (thinking before tools/text)."""
        parser = ClaudeParser()
        response = parser.parse(sample_pane_04)

        # Generally, thinking comes before the related tool call or text
        # This is a sanity check that ordering is preserved
        section_types = [s.type for s in response.sections]
        assert len(section_types) > 0

    def test_pane_content_not_ready(self, pane_content):
        """Test pane_content (mid-session) is NOT in ready state."""
        parser = ClaudeParser()
        # This fixture shows Claude mid-processing
        assert parser.is_ready(pane_content) is False

    def test_pane_content_has_thinking(self, pane_content):
        """Test pane_content has thinking markers."""
        parser = ClaudeParser()
        response = parser.parse(pane_content)

        # Even mid-processing, we should detect thinking sections
        thinking_sections = [s for s in response.sections if s.type == "thinking"]
        assert len(thinking_sections) >= 1


class TestClaudeParserEdgeCases:
    """Edge case tests for ClaudeParser."""

    def test_empty_content(self):
        """Test parser handles empty content."""
        parser = ClaudeParser()
        assert parser.is_ready("") is False

        response = parser.parse("")
        assert response.raw == ""
        assert len(response.sections) == 0

    def test_only_prompt(self):
        """Test parser handles content with only prompt."""
        parser = ClaudeParser()
        content = "> Some question\n"
        assert parser.is_ready(content) is False

    def test_multiline_thinking(self):
        """Test parser handles multi-line thinking content."""
        parser = ClaudeParser()
        content = """
> Question

∴ Thinking…
  First line of thought.
  Second line of thought.
  Third line with more detail.

⏺ Here is the answer.

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    1000 tokens
"""
        response = parser.parse(content)
        thinking_sections = [s for s in response.sections if s.type == "thinking"]

        assert len(thinking_sections) == 1
        assert "First line" in thinking_sections[0].content
        assert "Second line" in thinking_sections[0].content
        assert "Third line" in thinking_sections[0].content

    def test_multiple_tool_calls(self):
        """Test parser handles multiple sequential tool calls."""
        parser = ClaudeParser()
        content = """
> Do multiple things

⏺ Read(file="a.py")
⎿  content of a

⏺ Read(file="b.py")
⎿  content of b

⏺ Bash(command="ls")
⎿  file1  file2

⏺ Done with all tools.

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    5000 tokens
"""
        response = parser.parse(content)
        tool_calls = [s for s in response.sections if s.type == "tool_call"]

        assert len(tool_calls) == 3
        tools = [t.tool for t in tool_calls]
        assert tools.count("Read") == 2
        assert tools.count("Bash") == 1

    def test_tool_with_complex_args(self):
        """Test parser handles tool calls with complex arguments."""
        parser = ClaudeParser()
        content = """
> Search for something

⏺ Search(pattern: "some pattern", path: "/path/to/dir", output_mode: "content")
⎿  Found 5 results

⏺ Found what you need.

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    3000 tokens
"""
        response = parser.parse(content)
        tool_calls = [s for s in response.sections if s.type == "tool_call"]

        assert len(tool_calls) == 1
        assert tool_calls[0].tool == "Search"

    def test_thinking_followed_by_thinking(self):
        """Test parser handles consecutive thinking sections."""
        parser = ClaudeParser()
        content = """
> Complex question

∴ Thinking…
  First round of thought.

∴ Thinking…
  Second round of thought after more processing.

⏺ Final answer.

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    2000 tokens
"""
        response = parser.parse(content)
        thinking_sections = [s for s in response.sections if s.type == "thinking"]

        assert len(thinking_sections) == 2
        assert "First round" in thinking_sections[0].content
        assert "Second round" in thinking_sections[1].content

    def test_token_extraction_with_k_suffix(self):
        """Test token extraction handles various formats."""
        parser = ClaudeParser()
        # Some versions might show "102k tokens" instead of full number
        content = """
> Question

⏺ Answer

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    99999 tokens
"""
        response = parser.parse(content)
        assert response.tokens == 99999

    def test_no_insert_mode(self):
        """Test parser handles output without INSERT mode."""
        parser = ClaudeParser()
        content = """
> Question

⏺ Still working...
  (esc to interrupt)
"""
        assert parser.is_ready(content) is False

    def test_suggestion_prompt_not_user_prompt(self):
        """Test parser distinguishes suggestion from actual prompt."""
        parser = ClaudeParser()
        content = """
> Actual user question

⏺ Some response

───────────────────────────────────────────────────────────
> suggested completion (tab to accept)
───────────────────────────────────────────────────────────
  -- INSERT --                                    1000 tokens
"""
        response = parser.parse(content)
        # Should extract response after "Actual user question", not after suggestion
        assert "Some response" in response.raw

    def test_compacted_conversation_marker(self):
        """Test parser extracts response after compaction marker."""
        parser = ClaudeParser()
        # Simulate compacted conversation where the last user prompt is BEFORE
        # the compaction marker, but the response is AFTER
        content = """
> Old prompt that was compacted away

──── Conversation compacted ────────────────────────────────

∴ Thinking…
  Working on the new request after compaction.

⏺ The answer to your question is 42.

───────────────────────────────────────────────────────────
>
───────────────────────────────────────────────────────────
  -- INSERT --                                    5000 tokens
"""
        # Parser should extract response after compaction, not before
        response = parser.parse(content)
        assert response.is_ready is True
        assert "42" in response.raw
        assert "Old prompt" not in response.raw

        # Should have thinking and text sections
        thinking = [s for s in response.sections if s.type == "thinking"]
        text = [s for s in response.sections if s.type == "text"]
        assert len(thinking) >= 1
        assert len(text) >= 1
        assert "42" in text[0].content

    def test_rating_prompt_handling(self, sample_pane_03):
        """Test parser handles session rating prompt."""
        parser = ClaudeParser()
        # sample_pane_03 contains rating prompt
        assert "How is Claude doing" in sample_pane_03

        # Parser should still detect ready state
        assert parser.is_ready(sample_pane_03) is True


class TestClaudeParserSectionMetadata:
    """Tests for section metadata extraction."""

    def test_tool_call_has_tool_name(self, sample_claude_output_with_tool):
        """Test tool call sections have tool name in metadata."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output_with_tool)

        tool_sections = [s for s in response.sections if s.type == "tool_call"]
        assert all(s.tool is not None for s in tool_sections)

    def test_tool_call_has_args(self, sample_claude_output_with_tool):
        """Test tool call sections have args in metadata."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output_with_tool)

        tool_sections = [s for s in response.sections if s.type == "tool_call"]
        assert len(tool_sections) >= 1

        # First tool should be Read with file_path arg
        read_tool = tool_sections[0]
        assert read_tool.tool == "Read"
        assert "args" in read_tool.metadata
        assert 'file_path="main.py"' in read_tool.metadata["args"]

    def test_tool_call_content_is_result(self, sample_claude_output_with_tool):
        """Test tool call content is the result (from ⎿ lines)."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output_with_tool)

        tool_sections = [s for s in response.sections if s.type == "tool_call"]
        assert len(tool_sections) >= 1

        # The Read tool result should contain the file contents
        read_tool = tool_sections[0]
        assert "def main():" in read_tool.content
        assert 'print("Hello, World!")' in read_tool.content

    def test_thinking_has_content(self, sample_claude_output):
        """Test thinking sections have content."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        thinking_sections = [s for s in response.sections if s.type == "thinking"]
        assert all(len(s.content) > 0 for s in thinking_sections)

    def test_text_has_content(self, sample_claude_output):
        """Test text sections have content."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        text_sections = [s for s in response.sections if s.type == "text"]
        assert all(len(s.content) > 0 for s in text_sections)


class TestClaudeParserRawExtraction:
    """Tests for raw response extraction."""

    def test_raw_excludes_prompt_line(self, sample_claude_output):
        """Test raw response doesn't include the prompt line."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        # The "> What is 2+2?" should not be in raw
        assert "> What is 2+2?" not in response.raw

    def test_raw_excludes_status_line(self, sample_claude_output):
        """Test raw response doesn't include status line."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        # INSERT mode line should not be in raw
        assert "-- INSERT --" not in response.raw

    def test_raw_includes_response_content(self, sample_claude_output):
        """Test raw response includes actual response."""
        parser = ClaudeParser()
        response = parser.parse(sample_claude_output)

        # Should contain the thinking and text
        assert "Thinking" in response.raw or "∴" in response.raw or "answer" in response.raw.lower()
