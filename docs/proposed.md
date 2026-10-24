# ResearchOS

## A Multi-Agent Research Assistant with Graph-Structured Memory

**Final Year Project Proposal**

Core engine: **CtxFlow** — a schema-agnostic, incrementally-built graph memory framework

> Status: Proposal / Working Draft
>
> This Markdown copy was recovered from `docs/ResearchOS_FYP_Proposal.docx` (the
> previously committed `docs/proposed.md` was empty).

---

## 1. Executive Summary

Autonomous research requires an assistant that remembers not just facts but how
those facts relate: which claim came from which paper, which experiment tested
which hypothesis, and which later finding overturned an earlier one. Flat chat
history and flat vector retrieval cannot represent this structure, and generic
"AI research chatbots" have become a crowded, undifferentiated category.

This project proposes: a project-centric research workspace in which a small
multi-agent system — **Retriever, Reader, Synthesizer, and Critic** — answers
research questions by reading and writing to **CtxFlow**, a lightweight graph
memory engine purpose-built for agent context. The system's defining capability,
and its central research question, is whether graph-structured memory with
explicit contradiction tracking lets a multi-agent assistant correctly surface a
superseded claim and show its provenance, where flat retrieval would not.

The project is scoped deliberately narrow: four agents, four skills, one
vertical use case (literature-grounded question answering with provenance), and
one evaluation axis. Breadth — a skills marketplace, MCP ecosystem, experiment
manager, adaptive routing layer — is treated as architecture that is
demonstrably extensible, not as something built out in full. This keeps the
project defensible as a complete, working application within a single semester.

---

## 2. Problem Statement & Motivation

### 2.1 Why existing memory approaches fail for research assistance

- **Sliding-window buffers** discard anything outside a recent turn count — a
  credential, constraint, or finding from early in a project is permanently
  lost.
- **Flat-vector RAG** treats every note or paper as an independent point in
  embedding space. It cannot represent that claim B was derived from claim A, or
  that result C contradicts result A — it will happily retrieve both the
  original and the outdated claim with no signal that one superseded the other.
- **Enterprise knowledge graphs** (RDF/SPARQL/Neo4j) require a predefined schema
  and heavyweight entity resolution, which is a poor fit for an agent ingesting
  unstructured papers and notes in real time.
- **Naive agent-graph implementations** suffer from super-hub bias:
  frequently-referenced nodes accumulate disproportionate connectivity and start
  dominating retrieval regardless of actual relevance to the current query.

### 2.2 Why this matters specifically for research assistants

Research is the use case where these failures are most visible and most costly.
Findings get superseded by later work; hypotheses need to be checked against
accumulating, sometimes contradictory, evidence; and a researcher needs to be
able to ask not just "what does the literature say" but "why do you think that,
and is it still true." A system that cannot represent supersession, or cannot
show where an answer came from, is not trustworthy enough to delegate research
synthesis to.

---

## 3. Related Work & Positioning

CtxFlow synthesizes ideas from four lines of work rather than proposing a wholly
new retrieval mechanism:

- **HippoRAG** — neuroscience-inspired associative retrieval using Personalized
  PageRank over a knowledge graph, as opposed to one-shot vector search.
- **RAPTOR** — recursive abstractive clustering, used here as the inspiration for
  "summarize rather than delete" pruning of stale context.
- **Mem0** — dynamic, continuously-updated agent memory and the motivating
  example of hub-domination in naive graph-memory systems.
- **GraphReader** — exposing direct graph-walk APIs so an agent can deliberately
  explore memory step by step, rather than only receiving a retrieved blob.

The closest existing systems are Mem0 (and its graph variant, Mem0g) and
Zep/Graphiti, both of which build temporal or relational memory graphs for
agents. This project's differentiation is twofold: (a) explicit insertion-time
degree caps and query-time degree normalization as a first-class governance
mechanism against hub bias, which is not a focus of either system, and (b) the
application of supersession/contradiction edges specifically to the
research-assistant setting, surfaced through a dedicated provenance view
(Research Trace) rather than left implicit in retrieval scores. Before
implementation, Graphiti's edge-invalidation mechanism will be reviewed directly
to confirm this differentiation holds and to avoid duplicating existing work.

---

## 4. System Architecture

### 4.1 Overview

The system has three layers: a project workspace (UI, minimal), a four-agent
pipeline that answers research questions, and CtxFlow, the graph memory engine
both agents and the UI read from and write to.

**Data flow.** Researcher asks a question → Skill Router selects agents/tools →
Retriever/Reader ingest new material into CtxFlow if needed → Synthesizer queries
the graph via composite scoring → Critic checks the draft answer against
contradiction/supersession edges → Answer returned with a Research Trace showing
the supporting (and any contradicting) nodes.

### 4.2 CtxFlow — graph memory engine

Each ingested unit (a paper's claim, a method description, a result, a
researcher's note) becomes a node with content, an abstractive summary,
open-vocabulary tags, an open-vocabulary type, and timestamps. Edges are directed
and typed (`follows`, `related_to`, `supersedes`). Ingestion is O(1) amortized:
an extractor pulls tags, the node is linked to its explicit source (if any) and to
its top-k tag-similar neighbors via an inverted tag index — no full graph rescan
is required.

Retrieval scores candidates on a convex combination of three signals — lexical
tag overlap (Jaccard), recency decay, and graph proximity (BFS hop distance from
the agent's current anchor node) — and divides the result by `(degree + 1)` to
prevent high-connectivity hub nodes from dominating every query. A decoupled
maintenance pass computes a staleness score per node and either drops stale nodes
(with edge healing) or collapses stale, densely-connected clusters into summary
nodes.

### 4.3 The four agents

| Agent | Role | Tools / Skills used |
|---|---|---|
| **Retriever** | Decides what literature is worth pulling in for the current question | Literature Search skill (arXiv / Semantic Scholar API) |
| **Reader** | Turns a paper into structured nodes (claims, methods, results) | Paper Reader skill (extractor pipeline) |
| **Synthesizer** | Queries the graph and drafts an answer, citing which nodes it used | Graph Query skill (composite retrieval) |
| **Critic** | Checks the draft against contradiction/supersession edges; flags unsupported claims | Graph Query skill; Review Writer skill for final formatting |

Routing between agents is fixed or lightly branching for v1 (e.g., a query about
new literature engages Retriever + Reader; a query about the existing project
state engages Synthesizer + Critic). An adaptive, learned routing layer is
explicitly deferred (see Section 6).

### 4.4 Skill registry

Skills are registered as independently callable units with a declared
input/output schema, so the set of skills is extensible without changing the agent
or UI code. Four skills are built as real, working tools:

1. **Literature Search** — wraps the arXiv and Semantic Scholar APIs.
2. **Paper Reader** — the CtxFlow extractor, exposed as an invokable tool that
   turns a PDF into graph nodes.
3. **Graph Query** — the composite retrieval scorer, exposed as a tool the
   Synthesizer and Critic call directly.
4. **Literature Review Writer** — takes a set of graph nodes and produces a
   structured document.

The registry and UI additionally list further skills (e.g., Zotero, GitHub,
statistical analysis) as "available / roadmap" to demonstrate the architecture's
extensibility without implying they are built.

### 4.5 Project workspace & Research Trace

The UI is intentionally minimal scaffolding: a project holds papers, notes, a
chat interface to the agent pipeline, and a graph view. The one UI feature
treated as a core deliverable, not scaffolding, is **Research Trace**: clicking
"why do you think this" on any answer shows the chain of supporting nodes and,
where relevant, a contradicting claim that was taken into account. This is the
feature that makes the graph architecture visible and auditable rather than a
hidden implementation detail.

---

## 5. Research Question & Evaluation

### 5.1 Primary research question

Does a multi-agent research assistant backed by CtxFlow's graph memory — with
explicit contradiction/supersession edges — produce answers that correctly
reflect superseded claims and expose accurate provenance, compared to the same
agent pipeline running on flat vector-RAG memory?

### 5.2 Systems compared

| System | Memory | Agents |
|---|---|---|
| Baseline A | Flat vector RAG (ChromaDB, top-k) | Single agent |
| Baseline B | Flat vector RAG (ChromaDB, top-k) | 4-agent pipeline (same as proposed) |
| Proposed system | CtxFlow graph memory | 4-agent pipeline |

### 5.3 Benchmark construction

A test set of research questions will be built where an early paper's finding was
later overturned or qualified by subsequent work (a "superseded claim" test set),
drawn from a focused sub-literature (e.g., agent memory / long-context retrieval,
kept consistent with the project's own domain so ingested papers are reused as
the evaluation corpus). Each test item has a known correct "current" answer and a
known superseded answer.

### 5.4 Metrics

- **Answer correctness** — does the final answer reflect the up-to-date claim
  rather than the superseded one.
- **Provenance correctness** — does the Research Trace actually cite the
  correction (not just the original claim).
- **Token cost** — prompt tokens consumed per query, graph system vs. flat RAG.
- **Retrieval recall** on a secondary multi-hop test (adapted from
  HotpotQA/MuSiQue-style chained facts), to check the graph's structural-traversal
  advantage independent of the supersession scenario.

### 5.5 Secondary check: does provenance change trust

A small supplementary check — a handful of participants or an LLM-judge proxy —
comparing whether seeing the Research Trace changes how readily users accept vs.
verify an answer, relative to seeing the same answer with no trace. This is
explicitly secondary and will be cut first if time is short.

---

## 6. Scope: Built vs. Deferred

The single biggest risk to this project is scope creep — the same pattern that
affected earlier design iterations of this proposal. The table below is the
binding commitment for v1.

| Built in v1 (this project) | Explicitly deferred (roadmap) |
|---|---|
| Graph memory: nodes/edges, tag index, degree caps + normalization, BFS proximity, Jaccard+recency+proximity composite scoring, drop/summarize pruning | Personalized PageRank, Louvain/Leiden hierarchical compaction, dense-vector hybrid retrieval backend |
| 4 agents (Retriever, Reader, Synthesizer, Critic) with fixed/lightly-branching routing | Adaptive/learned routing layer ("Laya"), multi-agent negotiation, more than 4 roles |
| 4 real skills (Literature Search, Paper Reader, Graph Query, Review Writer) in a lightweight registry | Skill marketplace UI, install/browse flow, more than 4 working skills |
| Direct API calls to arXiv / Semantic Scholar | MCP server integration, LangGraph/CrewAI/AutoGen adapters |
| Supersedes/invalidates edges for contradicting claims (simple similarity + LLM check) | Full automated conflict-resolution pipeline, fact deduplication at scale |
| Minimal project workspace: papers, notes, chat, graph view, Research Trace | Experiment Manager, Data Analysis Workspace, Documentation Center, Timeline, Task Planner |

Everything in the right-hand column is retained as an architecture diagram and a
short roadmap slide in the final report and defense — described, not built — so
the project can still communicate the full product vision without risking the
delivered system.

---

## 7. Timeline

| Milestone | Deliverable |
|---|---|
| Core graph engine | Node/edge schema, tag index, degree-capped governance, BFS proximity (library, tested in isolation) |
| Extractor + ingestion | spaCy/LLM extractor producing claim/method/result nodes from a paper; O(1) ingestion pipeline wired end to end |
| Skill registry + 4 skills | Literature Search, Paper Reader, Graph Query, Review Writer — each a callable unit with declared schema |
| Four-agent pipeline | Retriever, Reader, Synthesizer, Critic agents wired to skills/tools and to the graph; fixed routing |
| Project workspace shell | Minimal UI: project, papers, notes, chat — scaffolding only, not a research deliverable |
| Research Trace view | Provenance UI: answer → claim → paper/experiment, including contradiction edges |
| Benchmark construction | Superseded-claim test set; baseline system (flat vector RAG, single agent) implemented |
| Evaluation run | CtxFlow+multi-agent vs. baseline on accuracy, provenance correctness, token cost |
| User check on Research Trace | Small trust/verification check: does exposing provenance change how users treat answers |
| Write-up & defense prep | Final report, demo script, roadmap slide for deferred scope |

---

## 8. Deliverables & Success Criteria

**Deliverables**

1. Working CtxFlow library: ingestion, composite scoring, degree governance,
   pruning — unit tested in isolation.
2. Four-agent pipeline, each agent wired to its listed skills, operating against
   a live project's graph.
3. Skill registry with four real skills and a documented schema for adding more.
4. Research Trace UI showing provenance, including at least one real
   contradiction/supersession case from the demo project.
5. Evaluation report comparing the proposed system against both baselines on the
   superseded-claim benchmark, with the multi-hop recall test as a secondary
   result.
6. Final report with an explicit, labeled roadmap section covering deferred scope
   (Section 6, right column).

**Success criteria**

- The system correctly identifies and cites the superseded claim in a clear
  majority of benchmark items where Baseline A/B do not.
- Research Trace reliably surfaces the correct supporting (and contradicting)
  nodes for a sampled set of live queries during the demo.
- The skill registry and agent pipeline run end-to-end on at least one live
  project without manual intervention.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Scope expands again mid-build (as in earlier design passes) | Section 6 table is treated as binding; any new feature request gets added to the deferred column, not the build |
| LLM-based contradiction detection is unreliable | Start with a narrow, curated supersession test set where the contradiction is unambiguous; report detection precision/recall honestly rather than assuming correctness |
| Benchmark construction (finding real superseded-claim pairs) takes longer than planned | Scope the benchmark to one sub-literature already being ingested for the demo project, reusing papers rather than sourcing a separate corpus |
| Four-agent pipeline debugging overhead (multi-agent systems are harder to trace than single-agent) | Research Trace doubles as a debugging tool during development, not just a demo feature |
| Graphiti/Mem0g may already cover the degree-governance contribution | Literature check scheduled in Week 1–2 before governance mechanism is finalized; pivot framing to the research-assistant application if overlap is found |

---

## 10. Conclusion

ResearchOS narrows a broad, ambitious product vision — a full research operating
system — down to the one vertical slice that is both buildable in a semester and
genuinely research-worthy: a small multi-agent pipeline, backed by a graph memory
engine with explicit hub-governance and contradiction tracking, evaluated on
whether it correctly handles superseded research claims and can show its
reasoning. The remaining product vision — experiment management, data analysis
workspaces, a skill marketplace, an MCP ecosystem — is preserved as an explicit,
honestly-labeled roadmap rather than claimed as delivered work.
