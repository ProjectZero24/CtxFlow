"""Tests for the Extractor interface and DefaultExtractor."""

from ctxflow.extractors import DefaultExtractor
from ctxflow.models import Node


class TestDefaultExtractor:
    def setup_method(self):
        self.extractor = DefaultExtractor()

    def test_extract_tags_basic(self):
        tags = self.extractor.extract_tags("The quick brown fox jumps over the lazy dog")
        # "the" and "over" are stop words.
        assert "quick" in tags
        assert "brown" in tags
        assert "fox" in tags
        assert "jumps" in tags
        assert "lazy" in tags
        assert "dog" in tags
        assert "the" not in tags
        assert "over" not in tags

    def test_extract_tags_short_words_excluded(self):
        tags = self.extractor.extract_tags("I am a CS AI ML")
        # Words shorter than 3 chars are excluded.
        assert len(tags) == 0

    def test_extract_tags_empty(self):
        tags = self.extractor.extract_tags("")
        assert tags == set()

    def test_extract_tags_max_tags(self):
        extractor = DefaultExtractor(max_tags=3)
        text = "alpha bravo charlie delta echo foxtrot golf"
        tags = extractor.extract_tags(text)
        assert len(tags) <= 3

    def test_extract_tags_deduplicates(self):
        tags = self.extractor.extract_tags("agent agent agent task task")
        assert "agent" in tags
        assert "task" in tags

    def test_summarize_basic(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        summary = self.extractor.summarize(text)
        assert "First sentence." in summary
        assert "Second sentence." in summary
        assert "Third sentence." in summary
        assert "Fourth sentence." not in summary

    def test_summarize_short_text(self):
        text = "Only one sentence."
        summary = self.extractor.summarize(text)
        assert summary == text

    def test_summarize_empty(self):
        assert self.extractor.summarize("") == ""

    def test_summarize_nodes(self):
        nodes = [
            Node(content="Content A", summary="Summary A"),
            Node(content="Content B", summary="Summary B"),
        ]
        result = self.extractor.summarize_nodes(nodes)
        assert "Summary A" in result
        assert "Summary B" in result

    def test_summarize_nodes_fallback_to_content(self):
        nodes = [
            Node(content="Full content here", summary=""),
        ]
        result = self.extractor.summarize_nodes(nodes)
        assert "Full content here" in result

    def test_custom_stop_words(self):
        extractor = DefaultExtractor(stop_words={"custom"})
        tags = extractor.extract_tags("custom words here")
        assert "custom" not in tags
        assert "words" in tags
        assert "here" in tags
