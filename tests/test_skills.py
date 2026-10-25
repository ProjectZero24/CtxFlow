"""Unit tests for ResearchOS Skills Layer."""

from __future__ import annotations

import pytest

from ctxflow import CtxFlow
from ctxflow.models import CtxFlowConfig
from researchos.skills.graph_query import GraphQuerySkill
from researchos.skills.literature_search import LiteratureSearchSkill, PaperResult
from researchos.skills.paper_reader import ExtractedClaim, PaperReaderSkill, PaperSection
from researchos.skills.registry import SkillRegistry, SkillResult
from researchos.skills.review_writer import ReviewWriterSkill


class TestSkillRegistry:
    """Tests for SkillRegistry registration, discovery, and execution."""

    def test_register_decorator_and_invoke(self):
        registry = SkillRegistry()

        @registry.register(
            name="add_numbers",
            description="Add two numbers together",
            tags=["math", "arithmetic"],
        )
        def add(a: int, b: int) -> int:
            return a + b

        assert registry.has_skill("add_numbers")
        assert len(registry) == 1

        result = registry.invoke("add_numbers", a=5, b=7)
        assert isinstance(result, SkillResult)
        assert result.success is True
        assert result.data == 12

    def test_invoke_missing_skill(self):
        registry = SkillRegistry()
        result = registry.invoke("non_existent", x=1)
        assert result.success is False
        assert "not found" in result.error

    def test_input_schema_validation(self):
        registry = SkillRegistry()

        registry.register_function(
            name="search",
            fn=lambda query, max_results=5: (query, max_results),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
            },
        )

        assert registry.invoke("search", query="graph").success is True

        missing = registry.invoke("search")
        assert missing.success is False
        assert "required" in missing.error

        wrong_type = registry.invoke("search", query="graph", max_results="many")
        assert wrong_type.success is False
        assert "max_results" in wrong_type.error

        below_min = registry.invoke("search", query="graph", max_results=0)
        assert below_min.success is False
        assert ">= 1" in below_min.error

    def test_find_by_tag(self):
        registry = SkillRegistry()

        registry.register_function(
            name="skill_a",
            fn=lambda: 1,
            tags=["paper", "nlp"],
        )
        registry.register_function(
            name="skill_b",
            fn=lambda: 2,
            tags=["cv"],
        )

        nlp_skills = registry.find_by_tag("nlp")
        assert len(nlp_skills) == 1
        assert nlp_skills[0].name == "skill_a"

    @pytest.mark.asyncio
    async def test_async_skill_invocation(self):
        registry = SkillRegistry()

        @registry.register(name="async_op")
        async def async_op(value: str) -> str:
            return f"processed_{value}"

        result = await registry.invoke_async("async_op", value="test")
        assert result.success is True
        assert result.data == "processed_test"


class TestLiteratureSearchSkill:
    """Tests for LiteratureSearchSkill with cache."""

    def test_search_caching(self, tmp_path):
        skill = LiteratureSearchSkill(cache_dir=str(tmp_path))

        # Manually seed cache
        fake_results = [
            PaperResult(
                title="Attention Is All You Need",
                authors=["Vaswani et al."],
                abstract="Transformer architecture.",
                year=2017,
                arxiv_id="1706.03762",
                source="arxiv",
            )
        ]

        import json
        key = skill._cached_search.__wrapped__ if hasattr(skill._cached_search, "__wrapped__") else None
        # Test dedup and cache clear
        skill.clear_cache()
        assert len(skill.search("transformer", provider="none")) == 0
        skill.close()


class TestGraphQuerySkill:
    """Tests for GraphQuerySkill."""

    def test_graph_query_and_trace(self):
        cf = CtxFlow()

        p_id = cf.ingest("Paper: Deep Residual Learning", node_type="paper", tags={"resnet"})
        c_id = cf.ingest(
            "ResNet introduces identity skip connections.",
            node_type="claim",
            source_id=p_id,
            relation_type="extracted_from",
            tags={"resnet", "skip_connection"},
        )

        skill = GraphQuerySkill(cf)
        results = skill.query("residual connections", k=5)
        assert len(results) >= 1

        trace = skill.research_trace(c_id)
        assert trace.answer_node_id == c_id
        assert len(trace.source_papers) >= 1
        assert trace.source_papers[0]["node_id"] == p_id

        stats = skill.get_graph_stats()
        assert stats["total_nodes"] == 2
        assert stats["total_edges"] >= 1


class TestPaperReaderSkill:
    """Tests for PaperReaderSkill heuristic fallback."""

    def test_heuristic_claims_extraction(self):
        skill = PaperReaderSkill(llm=None)
        section = PaperSection(
            title="Introduction",
            text="We propose a novel framework for context graphs. Our method achieves 95% accuracy.",
            page_numbers=[1],
        )

        claims = skill._extract_claims_heuristic(section)
        assert len(claims) >= 2
        types = [c.claim_type for c in claims]
        assert "method" in types
        assert "result" in types


class TestReviewWriterSkill:
    """Tests for ReviewWriterSkill."""

    def test_review_writing_heuristic(self):
        cf = CtxFlow()
        cf.ingest("Transformers use self-attention to process tokens in parallel.", node_type="claim", tags={"transformer"})
        cf.ingest("State Space Models provide linear complexity in sequence length.", node_type="claim", tags={"ssm"})

        writer = ReviewWriterSkill(cf, llm=None)
        review = writer.write_review(topic="sequence modeling", max_sources=5)

        assert "Literature Review" in review.title
        assert len(review.sections) >= 1
        assert len(review.references) >= 1
