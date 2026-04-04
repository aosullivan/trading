# Phase 1: Build Trend-Following Knowledge Base - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Read every transcript `.txt` file in `audio/` in a deterministic chapter order, extract trend-following principles and implementation-relevant rules, and produce a reusable knowledge-base artifact that can directly guide Phase 2 strategy design. This phase does not implement the strategy itself.

</domain>

<decisions>
## Implementation Decisions

### Corpus ordering and coverage
- **D-01:** Process every `.txt` file under `audio/` in filename order, which matches chapter sequence for this corpus.
- **D-02:** Treat the transcript corpus as the source of strategy requirements; do not cherry-pick only a few chapters unless a file is unreadable, and record any skipped file explicitly.

### Knowledge-base artifact format
- **D-03:** Produce a human-readable Markdown knowledge base under `.planning/` so it can be inspected directly and consumed by later GSD planning/research steps.
- **D-04:** Organize the artifact by strategy-relevant themes, not chapter-by-chapter narration only. At minimum include entries/exits, position sizing, risk control, drawdown discipline, trend persistence, whipsaw handling, portfolio/market selection, and regime assumptions.
- **D-05:** Include a compact per-chapter/source index so each extracted principle can be traced back to one or more transcript files.

### Citation and source traceability
- **D-06:** Every major extracted principle should include source references to the transcript filename and chapter number so Phase 2 can justify why a rule exists.
- **D-07:** Prefer concise summaries/paraphrases over large copied transcript passages. If short quotes are useful, keep them minimal and attach source-file references.

### Strategy synthesis handoff
- **D-08:** The Phase 1 output should not just summarize the book; it should end with an explicit "strategy design implications" section translating the extracted principles into candidate rule families and constraints for Phase 2.
- **D-09:** If the corpus implies several competing interpretations, preserve them as labeled alternatives with tradeoffs instead of collapsing prematurely to one rule set.

### the agent's Discretion
- Exact Markdown schema, filenames, and whether to generate one consolidated knowledge-base file or a small set of topic files.
- Whether to add a lightweight machine-readable sidecar (for example JSON) if it makes Phase 2 implementation easier, as long as Markdown remains the primary review artifact.
- Text-cleaning heuristics for transcript artifacts such as intro/outro credits, repeated phrases, or transcription glitches.

</decisions>

<specifics>
## Specific Ideas

- The user explicitly clarified that the real project output is "learning from the text files and using that information to build the strategy."
- The source corpus currently consists of 75 transcript text files in `audio/`, including opening/end credits and Chapter 1 through Chapter 73 from *Trend Following, 5th Edition*.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project and roadmap scope
- `.planning/PROJECT.md` — Product goal, constraints, and user clarification that corpus-driven learning is the main output.
- `.planning/REQUIREMENTS.md` — Phase 1 requirements `KB-01` through `KB-03`.
- `.planning/ROADMAP.md` — Phase 1 goal, success criteria, and phase boundary.
- `.planning/STATE.md` — Current position and known concerns.

### Existing codebase context
- `.planning/codebase/STACK.md` — Runtime/dependency context.
- `.planning/codebase/STRUCTURE.md` — Repository layout and likely integration points.
- `.planning/codebase/CONVENTIONS.md` — Existing coding and persistence conventions.
- `.planning/codebase/CONCERNS.md` — Known implementation risks to avoid.

### Transcript corpus
- `audio/` — Source transcript `.txt` files to ingest and summarize.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/transcribe_audiobook.py`: likely relevant as a clue for how transcript text files were generated, but this phase should primarily consume existing `.txt` outputs.
- `lib/paths.py`: use if the knowledge-base artifact or any generated sidecar needs project-relative or user-data path handling.

### Established Patterns
- The repo favors straightforward file-based artifacts and plain Markdown documentation, which fits a `.planning/` knowledge-base output.
- Existing workflows rely on deterministic, inspectable artifacts and source files rather than hidden state.

### Integration Points
- Phase 2 strategy implementation will likely use the Phase 1 artifact as design input before touching `lib/technical_indicators.py`, `lib/backtesting.py`, `routes/chart.py`, and UI templates/scripts.

</code_context>

<deferred>
## Deferred Ideas

- Implementing the actual corpus-derived strategy belongs to Phase 2.
- Running optimizer sweeps on the resulting strategy belongs to a later phase or v2 scope after an initial implementation exists.

</deferred>

---

*Phase: 01-build-trend-following-knowledge-base*
*Context gathered: 2026-04-04*
