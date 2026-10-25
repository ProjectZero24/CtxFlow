# Adithyan — Evidence & Retrieval Handbook
## Scholarly Search, PDF Ingestion, Provenance & Citations

| | |
|---|---|
| **Role** | Evidence owner: real research inputs, traceable excerpts, resolvable citations |
| **Seminar** | *Cache-Aware Serving and Token-Budgeted Retrieval for LLM Agents* |
| **Primary skill** | [`researchos_team_skills/researchos-evidence-retrieval/SKILL.md`](../../researchos_team_skills/researchos-evidence-retrieval/SKILL.md) |
| **Secondary reading** | `researchos-orchestration/SKILL.md` (how your skills are invoked) and `researchos-ctxflow-memory/SKILL.md` (token/provenance conventions). Read only; do not follow their edit scopes. |
| **Working branch** | `feat/adithyan-evidence` |
| **Baseline** | `Adi/feat/v1` @ `e1f43c6` (PR #3 merged); `144 passed, 6 skipped` (verified 25 Oct 2026) |
| **Contract freeze** | Fri 30 Oct 2026, 18:00 |

---

## 0. Read this first

1. This file is your complete brief. The primary skill is the detailed audit; both must agree. Where they differ, the **skill's verified code facts** win over the ownership doc.
2. The repository is `ProjectZero24/CtxFlow`, branch `Adi/feat/v1`. It has **no LangGraph, no separate frontend framework, no Laya model**.
3. The evidence pipeline already exists and works in parts. Your job is to make it **honest**: real sources, real pages, real citations, visible failures.
4. One gap per PR. A PR that adds a downloader, rewrites the reader, and changes schemas will be rejected.
5. Interface shapes in `src/researchos/api/schemas.py`, `paper_reader.py`, and `critic.py` are shared. Coordinate before changing them.
6. If an interface must change, update **every** consumer in the same PR: `reader.py`, `papers.py`, `critic.py`, `review_writer.py`, `api/schemas.py`, and tests.

---

## 1. Context in 60 seconds

ResearchOS answers research questions from a CtxFlow graph. For that to mean anything, the evidence entering the graph must be real and inspectable.

Current flow:

```text
query
  → RetrieverAgent: graph first, external search only on knowledge gap
  → LiteratureSearchSkill: arXiv + Semantic Scholar, SQLite TTL cache
  → ReaderAgent: paper node + claim nodes (extracted_from)
  → SynthesizerAgent: packs graph nodes into a prompt, cites [Node:ID]
  → CriticAgent: checks cited nodes for supersession/contradiction
```

What is broken or missing:

- `search_arxiv` / `search_semantic_scholar` use blocking `urllib` (30 s timeout) and **return `[]` on any error**. A provider outage is indistinguishable from "no papers found".
- Deduplication uses **lowercased title only**. DOI and arXiv ID are captured but unused; `_parse_arxiv_xml` never sets DOI; Semantic Scholar may return an empty URL.
- **No PDF downloader exists.** `ReaderAgent` only parses a PDF when `paper["pdf_path"]` is already present; otherwise it derives "evidence" from the abstract.
- `ReaderAgent` stores `source_paper` as the paper **title** and drops `section` / `page`; only `/api/papers/upload` preserves page metadata.
- **No citation validator exists.** `CriticAgent` checks node status/edges but does not parse or validate citation strings or quoted excerpts.
- No rate limiting or backoff; `provider="both"` can return up to `2 × max_results`.

That list is your backlog.

---

## 2. Your mandate

> Every claim ResearchOS shows must trace to a source the system actually read, at a page/section it can name, and every citation it emits must resolve to a stored record.

Three rules:

1. **No silent failure.** "Empty" and "provider failed" are different states and must be different in the data.
2. **No invented provenance.** Never fabricate a page number, a quote, or a full-text claim for an abstract-only source.
3. **No dead citations.** An unresolvable citation is removed or explicitly flagged, never rendered as if it were verified.

---

## 3. Skill assignment (what to load and why)

### Load this

`researchos_team_skills/researchos-evidence-retrieval/SKILL.md`

It defines:
- the exact current implementation and its six gaps,
- the existing `PaperResult` / `ExtractedClaim` shapes you must extend, not replace,
- the provenance fields to persist,
- the implementation order and acceptance criteria.

### Read for contracts only

- `researchos-orchestration/SKILL.md` — how `RetrieverAgent`, `ReaderAgent`, and the router pass `data` between agents.
- `researchos-ctxflow-memory/SKILL.md` — `SimpleTokenizer` and provenance/supersession conventions, if the memory adapter lands.

### Do not use as instructions

- `researchos-frontend-integration-evaluation` — UI and evaluation are Abinav's.
- `researchos-ctxflow-memory` — the memory adapter is Christo's.

### Assignment reconciliation

The skills split (commit `6ae8b0f`) assigns you evidence/retrieval. The older layer doc gives you Layer 4 (serving/caching). Your **primary delivery is evidence**; the caching, timeout, allowlist, and HTTP-discipline parts of L4 are naturally yours because they live in the retrieval client. Server routing, run lifecycle, and UI are not yours. If the team confirms the old L1–L4 split instead, your file list expands to `skills/registry.py`, `gateway/`, `api/`; until that decision is recorded, do not edit those areas.

---

## 4. Ownership map

### You own — write access

| Path | Responsibility |
|---|---|
| `src/researchos/skills/literature_search.py` | Providers, result normalization, cache, dedupe, politeness |
| `src/researchos/skills/paper_reader.py` | PDF text/section extraction, page tracking, `ExtractedClaim` |
| `src/researchos/agents/reader.py` | Source → paper node → claim nodes with provenance |
| `src/researchos/agents/retriever.py` | Knowledge-gap logic and external-search invocation (coordinate with Harikesh, who owns orchestration) |
| New `src/researchos/evidence/` or `src/researchos/skills/pdf_fetch.py` | Downloader with host allowlist, size/time caps, `access_status` |
| New `src/researchos/evidence/citations.py` (name negotiable) | Citation and excerpt validation helpers |
| `tests/test_skills.py`, `tests/test_agents.py` (evidence portions), new evidence tests | Regression surface |

### Shared — edit only with the named owner in the PR

| Path | Owner | Why |
|---|---|---|
| `src/researchos/api/schemas.py` | Abinav | New fields: `access_status`, `page`, `section`, citation status |
| `src/researchos/api/routes/papers.py` | Abinav / Harikesh | Upload/ingest behaviour and metadata |
| `src/researchos/agents/critic.py` | Harikesh | Citation **verdict** and strip/flag policy; you provide the resolver |
| `src/researchos/skills/review_writer.py` | Abinav (eval/UI) per current split | Report synthesis consumes your citation helpers |
| `src/researchos/agents/router.py` | Harikesh | Do not add provider logic to routing |
| `pyproject.toml` | Adithyan / Christo | Any new dependency, with measured need |

### Read-only for you

`src/ctxflow/**`, `src/researchos/memory/**`, `src/researchos/web/**`, `src/researchos/eval/**`, `src/researchos/orchestration/**`.

---

## 5. P0 deliverables

| # | Deliverable | Acceptance |
|---|---|---|
| 1 | Explicit provider outcomes: `ok`, `empty`, `error`, with provider and reason | A simulated 500/timeout is visible in the API payload and logs, not `[]` |
| 2 | Metadata normalization + robust dedupe: DOI → arXiv ID → cautious normalized title; keep winning provider | Duplicate fixture collapses to one record; no false merge of distinct papers |
| 3 | PDF acquisition with host allowlist, 20 MB cap, timeout, content-type check, `access_status` | Denied host and oversized file fail closed with a recorded reason |
| 4 | Page/section preservation through extraction and persistence | 95 % of claims on the demo corpus have a non-null page or an explicit `abstract_only` reason |
| 5 | Evidence node metadata: `source_paper_node_id`, `section`, `page`, `confidence`, `access_status` | A trace can go claim → paper → arXiv ID/DOI without guessing |
| 6 | Citation validator: every `[Node:ID]` and quoted excerpt resolves to a stored node/span | Unresolvable citations are reported/removed; validator has tests |
| 7 | Failure and politeness: timeouts, bounded retries with backoff, per-host rate limit, no unbounded download | Fault-injection tests; no retry storm; `both` result cap documented |
| 8 | Honest abstract-vs-full-text distinction in data and API | UI/consumer can tell them apart without inspecting prose |
| 9 | Regression corpus: duplicate, missing metadata, malformed PDF, provider error, unresolvable citation | Tests committed and green |

### Quality bar

- Quotations are exact text from the source. If you cannot verify the span, do not call it a quotation.
- `source_paper` (a title) is **not** sufficient provenance. Add the paper node ID.
- Respect robots/terms/access controls. Do not bypass paywalls.
- Every external call has a timeout, a bounded retry, and a fallback.

---

## 6. Implementation order

1. **Run the baseline.** `pytest -q tests/test_skills.py tests/test_agents.py`. Report the real result.
2. **Confirm what actually works in this environment.** Network may be unavailable; mocks are acceptable for tests, never for demo claims.
3. **Provider status first.** Change the return contract from `list[PaperResult]` to an explicit outcome object *with a compatibility path*, and update one provider end to end.
4. **Normalize and dedupe.** One canonical `PaperResult`; keep `metadata["provider"]`, `metadata["dedupe_key"]`.
5. **Downloader.** Allowlist, size cap, timeout, content-type, temp-file cleanup, `access_status`.
6. **Extraction.** Preserve `page_numbers`, section titles; mark malformed/inaccessible sources explicitly.
7. **Persist evidence** using the existing node convention; do not create a parallel schema.
8. **Citation validation.** Resolve node IDs and exact spans; return a deterministic result; let Harikesh decide verdict semantics.
9. **Tests.** Duplicate, missing metadata, parser failure, provider timeout, unsupported citation, oversized download.
10. **Document.** Update the skill's endpoint/field table and the README so the next person does not guess.

### Proposed shapes (extend, do not fork)

```python
# literature_search.py
class ProviderStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"

@dataclass
class SearchOutcome:
    status: ProviderStatus
    results: list[PaperResult]
    provider: str
    error: str | None = None
```

```python
# evidence/download.py or skills/pdf_fetch.py
class AccessStatus(str, Enum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
```

```python
# evidence/citations.py (proposed; Harikesh consumes it)
@dataclass(frozen=True)
class CitationCheck:
    citation: str
    resolved: bool
    node_id: str | None = None
    reason: str = ""
```

If any of these become a shared contract, publish it in the S0 contract note and add a test under `tests/contract/`.

---

## 7. What NOT to do

Hard prohibitions.

1. **Do not return `[]` for an error.** That is the single most misleading behaviour in the current code.
2. **Do not dedupe by title only**, and do not merge records on a fuzzy title when DOI/arXiv IDs disagree.
3. **Do not fabricate page numbers, sections, quotations, or DOIs.** An unknown page is `None`, not a guess.
4. **Do not present abstract-only content as full-text evidence.** Mark it.
5. **Do not store an excerpt you did not read from the source.**
6. **Do not create a competing `EvidenceRecord` / `Paper` schema.** Extend `PaperResult`, `ExtractedClaim`, and the node metadata convention.
7. **Do not add a new vector database or embedding service.** The graph and `ctxflow.memory` exist.
8. **Do not build a direct Semantic Scholar integration** if the MCP plan is adopted; the MVP plan explicitly removes it from the critical path. Prefer one reliable provider, then the MCP wrapper.
9. **Do not spawn unpinned MCP servers** (`npx -y latest`, unversioned `uvx`). Pin, allowlist, cap output, restrict env.
10. **Do not bypass paywalls, login walls, robots, or rate limits.** Respect terms and copyright.
11. **Do not call blocking `urllib` / `time.sleep` directly from an async path.** Use `asyncio.to_thread` and mark `# sync-bridge` (MVP plan AD-7).
12. **Do not edit the router, run lifecycle, memory adapter, UI, or evaluation harness.** Request the change from the owner.
13. **Do not claim a report is "verified" because it contains citations.** Verification means resolution against stored records.
14. **Do not add a dependency without a measured need** and an extras entry.
15. **Do not exceed 400 changed lines in a PR** or mix a refactor with a contract change.

---

## 8. Contracts you publish / consume

### You publish by S0 Friday

- `SearchOutcome` / provider status contract.
- Canonical `PaperResult` fields and dedupe key rule.
- `AccessStatus` vocabulary.
- Evidence metadata keys on claim nodes.
- `CitationCheck` shape (with Harikesh's agreement).

### You consume

| From | Contract |
|---|---|
| Harikesh | agent `data` keys: `internal_results`, `external_results`, `knowledge_gap`; invocation order |
| Christo | `CtxFlow.ingest`, node IDs, `research_trace`, provenance edge vocabulary |
| Abinav | API schema fields; UI expectations for source/access display |
| Runtime | model callable shape `(prompt, system) -> str`; no provider SDK imports outside the gateway |

### Preserved invariants

- Claim nodes remain `relation_type="extracted_from"` from the paper node.
- `source_paper`, `source_doi`, `section`, `page`, `confidence` keys keep their existing meaning; add, don't repurpose.
- `PaperReaderSkill.extract_claims` still returns `list[ExtractedClaim]` unless all consumers change together.

---

## 9. Sprint plan (yours only)

| Sprint | Deliverable | Gate |
|---|---|---|
| **S0** 26–30 Oct | Audit; provider/evidence contract; demo sub-literature shortlist; no code churn | Contract published |
| **S1** 2–6 Nov | Provider status + normalization + dedupe; one provider reliable end to end | Error vs empty visible |
| **S2** 9–13 Nov | Downloader + allowlist + access status; PDF path into `ReaderAgent` | Inaccessible source marked, not guessed |
| **S3** 16–20 Nov | Page/section provenance through extraction and persistence; evidence metadata | Trace resolves claim → paper |
| **S4** 23–27 Nov | Citation validator + failure/politeness tests; abstract-only surfacing | Unresolvable citation removed/flagged |
| **S5** 30 Nov–4 Dec | Regression corpus; provider error fixtures; extraction precision on demo corpus | Tests green; precision reported |
| **S6** 7–11 Dec | Demo corpus fetch/freeze; docs; known-limitations section | Reproducible ingest |
| **S7** 14–18 Dec | Freeze; no risky changes | Frozen build |

---

## 10. Definition of Done

- [ ] Happy path + one failure path tested.
- [ ] `pytest -q` green; exact command and result reported.
- [ ] Provider errors and parser failures visible in data, not swallowed.
- [ ] Every new external call has timeout, retry bound, fallback.
- [ ] No blocking I/O on the event loop, or explicitly bridged and marked.
- [ ] Structured output validated; no raw `json.loads` without a guard.
- [ ] Provenance fields present on demo-corpus evidence.
- [ ] Docs and field tables updated.
- [ ] Cost/latency impact noted in the PR.

### Commands

```bash
python -m pytest -q
python -m pytest -q tests/test_skills.py tests/test_agents.py
python -m pytest -q tests/test_api.py tests/test_workspace_api.py
python -m researchos.eval
researchos-api
```

---

## 11. Known landmines in your area

| Landmine | Consequence | Action |
|---|---|---|
| `search_*` returns `[]` on any exception | Impossible to tell outage from empty | Fix first |
| Cache key includes `max_results` | Changing `k` misses the cache; cache fills with near-duplicates | Include provider + normalized query + relevant params deliberately |
| `provider="both"` doubles `max_results` | Unbounded result sets | Cap the merged list |
| `_parse_arxiv_xml` never sets DOI | Dedupe falls back to title | Parse DOI/arXiv ID reliably |
| S2 may return empty `url` | Downloader cannot resolve | Resolve via DOI/arXiv, or mark unavailable |
| `ReaderAgent` gate on `paper["pdf_path"]` | Abstract silently becomes "evidence" | Add explicit `access_status` |
| `ReaderAgent` stores title as `source_paper` | Title collision destroys provenance | Add paper node ID |
| `read_pdf` `page_count = len(sections)` | Misleading counts | Correct after extraction |
| Temp PDFs on upload | Leak if an exception path misses cleanup | `try/finally`; test it |
| `CriticAgent` only parses node status | Citations can be dead | Provide resolver; Harikesh owns verdict |
| `ReviewWriterSkill` emits `[Node:ID]` | Not DOI citations | Do not overclaim; validate IDs |
| `tests/llm.py` executed network code at import | Removed in PR #3 | Do not reintroduce network code at import time |

---

## 12. Coordination and escalation

| Topic | Person | Rule |
|---|---|---|
| Agent data keys / invocation order | Harikesh | Publish evidence payload shape first |
| API fields, UI display | Abinav | One schema PR, all consumers updated |
| Graph node/edge/provenance | Christo | Use existing vocabulary; do not add a parallel store |
| Citation verdict policy | Harikesh | You resolve; he decides strip/flag |
| MCP adoption | Harikesh / team | ADR first; do not smuggle a server in a retrieval PR |

**Escalate immediately if:** a provider blocks automated access, a demo paper cannot be legally fetched, or a schema change would break the UI.

---

## 13. Copy-paste kickoff prompt

```text
You are Adithyan, evidence/retrieval owner for ResearchOS in D:\DEEPLEARNIING\CtxFlow.

Read, in this order:
1. docs/team/ADITHYAN.md
2. researchos_team_skills/researchos-evidence-retrieval/SKILL.md
3. docs/MVP_IMPLEMENTATION_PLAN.md sections 1, 3.1, 9 (G3–G5, G7), 10, 12, 13
4. REPO_HANDOFF_SUMMARY.md sections 5, 6.3, 7.1, 11
5. src/researchos/skills/literature_search.py, paper_reader.py, agents/reader.py, agents/critic.py

Then run `python -m pytest -q tests/test_skills.py tests/test_agents.py` and report the real result.
Your first task: make one provider return an explicit ok/empty/error outcome without breaking
existing callers. Do not add a downloader or citation validator in the same PR. Do not edit the
router, UI, memory adapter, or eval harness. Do not fabricate page numbers or citations.
Report exact commands, results, and limitations.
```

---

## 14. One-screen summary

- **Own:** literature search, PDF reading, downloader, evidence provenance, citation resolver.
- **Ship:** honest provider states, dedupe, access status, page spans, resolvable citations.
- **Never:** silent `[]`, title-only dedupe, invented pages/quotes, abstract-as-full-text, new schema, paywall bypass, blocking I/O.
- **Skills:** `researchos-evidence-retrieval` (primary); read orchestration/memory for contracts only.
- **Done means:** tests green, failures visible, every demo claim resolves to a real source.
