---
name: researchos-evidence-retrieval
description: Implement scholarly search, paper metadata normalization, PDF/text extraction, structured evidence, source provenance, citation validation, and evidence-grounded report synthesis for ResearchOS.
---

# ResearchOS Evidence & Retrieval Skill

## Mission

Make ResearchOS perform real research and produce verifiable, source-linked outputs. Extend the existing retrieval/evidence code in `src/researchos/skills/` and `src/researchos/agents/`; reuse what works.

The repository is `ProjectZero24/CtxFlow` (integration branch `Adi/feat/v1`), not `quantum-coderX/Research_Agent`. There is no LangGraph here; the retriever/reader/critic are plain `BaseAgent` subclasses.

## Current implementation (verified at `34cf19f`)

Read these before planning:

- `src/researchos/skills/literature_search.py`
  - `PaperResult` dataclass: `title`, `authors`, `abstract`, `year`, `doi`, `arxiv_id`, `url`, `source`, `metadata`.
  - `search_arxiv(query, max_results, sort_by)` and `search_semantic_scholar(query, max_results, fields)` — both use `urllib`, 30 s timeout, and **return `[]` on any error** (log only).
  - `LiteratureSearchSkill.search(query, max_results=5, provider="both")` — SQLite cache at `.cache/literature_cache.db`, 7-day TTL, `provider ∈ {"arxiv", "semantic_scholar", "both"}`, per-provider `max_results`, then dedupe by lowercased `title`.
- `src/researchos/skills/paper_reader.py`
  - `extract_text_from_pdf(pdf_path)` and `extract_sections_from_pdf(pdf_path)` via PyMuPDF (`fitz`); raises `ImportError` with the `pip install ctxflow[researchos]` hint when missing.
  - `PaperSection(title, text, page_numbers)`.
  - `PaperReaderSkill.read_pdf(pdf_path)` → `{title, sections, full_text, page_count}`.
  - `PaperReaderSkill.extract_claims(pdf_path)` → `list[ExtractedClaim]`; LLM path via `ctxflow.llm_extractor.LLMExtractor`, heuristic sentence-split fallback. `ExtractedClaim` already has `claim_type`, `text`, `confidence`, `tags`, `source_section`, `page_number`.
- `src/researchos/agents/retriever.py` — queries the graph first, and only calls external search when `_has_knowledge_gap()` (fewer than 2 results or average score < 0.3).
- `src/researchos/agents/reader.py` — creates a `paper` node plus claim nodes with `relation_type="extracted_from"`. It uses `PaperReaderSkill` **only if `paper["pdf_path"]` is present** (there is no downloader).
- `src/researchos/agents/critic.py` — `verify_claim()` classifies graph hits as supporting / contradicting / superseded from node status and `contradicts` / `supersedes` edges. It does **not** parse or validate citation strings.
- `src/researchos/skills/review_writer.py` — `ReviewWriterSkill.write_review(topic, max_sources, include_superseded, token_budget)`; cites nodes by ID (`[Node:<id>]` in the LLM prompt, `[<id>]` in the heuristic fallback); has positional-bias-aware ordering.
- `src/researchos/api/routes/papers.py` — `/api/papers/ingest` and `/api/papers/upload`; the upload path stores `section` and `page` metadata, the ingest path does not.
- `tests/test_skills.py`, `tests/test_agents.py`, `tests/test_api.py`.

## Gaps to close (pick one per PR)

1. **PDF acquisition.** Nothing downloads a paper URL/arXiv PDF. `ReaderAgent` silently falls back to abstract-only when `pdf_path` is absent, so the system often produces abstract-derived "evidence".
2. **Metadata normalization.** `doi` and `arxiv_id` are captured but not used for dedupe; `_parse_arxiv_xml` never sets DOI, and `search_semantic_scholar` may return an empty `url`.
3. **Provenance fidelity.** `ReaderAgent` stores `source_paper` as the paper *title* and drops `section`/`page`; only `/api/papers/upload` preserves page numbers.
4. **Citation validation.** No step checks that `[Node:ID]` references or quoted excerpts resolve to stored nodes.
5. **Failure visibility.** Provider errors become empty result lists, indistinguishable from "no matches".
6. **Politeness.** No rate limiting or backoff; `max_results` is per provider, so `both` can return up to `2 × max_results`.

## Before coding

1. Inspect the files above and confirm which providers/parsers actually work in this environment (network access may be unavailable).
2. Run `pytest -q tests/test_skills.py tests/test_agents.py` and report the real result.
3. Identify what is implemented versus documented. Do not claim a provider works because the module exists.
4. Agree interface changes with orchestration, memory, and UI owners before touching shared shapes.
5. Write a short plan naming the exact file and gap.

## Ownership

- Scholarly search adapters and caching in `src/researchos/skills/literature_search.py`.
- Metadata normalization and deduplication.
- PDF download (new), text extraction, and page tracking.
- Structured evidence extraction and provenance mapping.
- Citation validation and evidence-grounded synthesis helpers.
- Tests for retrieval, parsing, provenance, and citation integrity.

Out of scope: intent routing, run lifecycle, the memory adapter, and the UI.

## Evidence shape (use the existing types)

Do **not** create a competing `EvidenceRecord` schema. Extend the dataclasses already in `src/researchos/skills/paper_reader.py` and persist evidence as CtxFlow nodes using the conventions the agents already read:

```python
# src/researchos/skills/paper_reader.py (existing; extend, don't replace)
@dataclass
class ExtractedClaim:
    claim_type: str = "claim"   # claim | method | result | finding | hypothesis
    text: str = ""
    confidence: float = 0.5
    tags: List[str] = field(default_factory=list)
    source_section: str = ""
    page_number: Optional[int] = None
```

Persisted node convention (`CtxFlow.ingest`):

```python
claim_node_id = ctx.ingest(
    content=claim.text[:500],
    node_type=claim.claim_type,
    source_id=paper_node_id,
    relation_type="extracted_from",
    tags=paper_tags | set(claim.tags),
    metadata={
        "source_paper": paper_title,      # existing key
        "source_doi": doi,                # existing key
        "source_paper_node_id": paper_node_id,  # add if you need a hard link
        "section": claim.source_section,  # currently only on the upload route
        "page": claim.page_number,        # currently only on the upload route
        "confidence": claim.confidence,
    },
)
```

If the shape must change, update every consumer in the same integration cycle: `src/researchos/agents/reader.py`, `src/researchos/api/routes/papers.py`, `src/researchos/agents/critic.py`, `src/researchos/skills/review_writer.py`, and `src/researchos/api/schemas.py`.

## Implementation order

1. Make one provider reliable end-to-end, with an explicit result status (`ok`, `empty`, `error`) instead of a silent `[]`.
2. Normalize into `PaperResult`; dedupe by DOI, then arXiv ID, then cautious normalized title. Keep the winning provider in `metadata`.
3. Add a downloader with an allowlist of hosts, size/time limits, and a clear `access_status` (`full_text`, `abstract_only`, `unavailable`, `failed`). Respect terms, robots/rate limits, and access controls.
4. Extract accessible PDFs; preserve `page_numbers` and section titles. Mark inaccessible/malformed sources explicitly.
5. Extract typed evidence and persist it with the metadata above. Never store an excerpt you did not read from the source.
6. Generate reports using node IDs and source metadata. Validate every `[Node:ID]` and every quoted excerpt against stored records before returning.
7. Add regression tests for duplicates, missing metadata, parser failure, provider error, and an unresolvable citation.

## Quality rules

- Distinguish abstract-only from full-text sources in data and in the UI/API payload.
- Preserve provenance through extraction and synthesis. `source_paper` alone (a title) is not sufficient for audit; add the paper node ID if you rely on it.
- Treat extracted quotations as exact text; do not fabricate page numbers.
- Unsupported claims must be removed, qualified, or explicitly marked unverified.
- Surface provider/parser failures; add timeouts and conservative retries.
- Respect provider terms, rate limits, access restrictions, and copyright.

## Non-goals

- Do not own routing, run state, or user confirmation.
- Do not implement project memory or CtxFlow graph algorithms.
- Do not build the frontend.
- Do not claim a report is fully verified merely because it contains citations.
- Do not add a new vector database or embedding service; the graph and `ctxflow.memory` already exist.

## Acceptance criteria

- A query returns normalized, deduplicated, real paper records with an honest access status.
- Readable source text retains page/source references.
- Evidence nodes point to real papers and contain traceable excerpts (`section`, `page`, `source_paper_node_id`).
- Every emitted citation resolves to a stored source/evidence record; unresolvable citations are reported, not rendered.
- Missing or failed source access is represented honestly.
- Tests cover duplicate papers, missing metadata, parser failures, unsupported citations, and provider errors.
- The module exposes documented functions the orchestration layer can call without importing UI code.
- `pytest -q` passes and the exact command/result is reported.

## Working agreement

Work on a feature branch, preserve current provider functionality, and make small PRs. Coordinate interface changes before merging. Report the actual tests run and known limitations.
