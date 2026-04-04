#!/usr/bin/env python3
"""Generate a source-indexed trend-following knowledge base from transcripts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


AUDIO_DIR = Path("audio")
PHASE_DIR = Path(".planning/phases/01-build-trend-following-knowledge-base")
KB_MD_PATH = PHASE_DIR / "trend-following-knowledge-base.md"
KB_JSON_PATH = PHASE_DIR / "trend-following-knowledge-base.json"

PRINCIPLE_CATEGORIES = [
    "entries",
    "exits",
    "position_sizing",
    "risk_control",
    "drawdown_discipline",
    "trend_persistence",
    "whipsaw_handling",
    "portfolio_market_selection",
    "regime_assumptions",
]

PRINCIPLE_BLUEPRINTS = [
    {
        "id": "entry-001",
        "category": "entries",
        "claim": (
            "Use objective price action to enter in the direction of strength, with "
            "breakouts, moving-average confirmation, or direct momentum signals "
            "preferred over opinion-driven entries."
        ),
        "strategy_implication": (
            "Phase 2 should start with long/short breakout or moving-average entry "
            "rules driven only by price and trend confirmation."
        ),
        "confidence": "high",
        "terms": [
            "buy when the price",
            "breakouts",
            "moving averages",
            "price momentum",
            "rising in price",
            "objective, price-based approach",
        ],
        "allow_margin_quotes": False,
        "alternatives": [
            "Moving-average and breakout families both appear in the corpus; Phase 2 "
            "can compare those implementations while keeping the signal price-based."
        ],
    },
    {
        "id": "exit-001",
        "category": "exits",
        "claim": (
            "Let winning trends continue, but define systematic sell/stop rules so "
            "exits are triggered by the same rule set rather than discretionary "
            "forecast changes."
        ),
        "strategy_implication": (
            "Use deterministic trailing-stop, channel-break, or moving-average exit "
            "logic that can hold a trend while cutting reversals mechanically."
        ),
        "confidence": "medium",
        "terms": [
            "buy and sell signals",
            "sell signal",
            "stop",
            "exit",
            "let it fly",
            "trend following system",
        ],
        "allow_margin_quotes": True,
        "alternatives": [
            "The transcripts emphasize staying with a system, but do not mandate one "
            "single stop formula; Phase 2 should choose a concrete exit family and test it."
        ],
    },
    {
        "id": "sizing-001",
        "category": "position_sizing",
        "claim": (
            "Position sizing and money management are core parts of the edge; trade "
            "size should be adjusted to risk/volatility instead of treating every "
            "signal equally."
        ),
        "strategy_implication": (
            "Include a volatility-scaled or fixed-risk sizing layer so position size "
            "is derived from market risk and account limits, not arbitrary share counts."
        ),
        "confidence": "high",
        "terms": [
            "position sizing",
            "money management",
            "trade size",
            "bet size",
            "one percent",
            "risk that keeps your trading",
        ],
        "allow_margin_quotes": False,
        "alternatives": [
            "The corpus supports risk-budgeted sizing, but the exact unit size and "
            "portfolio-level cap should be selected during Phase 2 implementation."
        ],
    },
    {
        "id": "risk-001",
        "category": "risk_control",
        "claim": (
            "Trend followers accept that losses are unavoidable, so risk management "
            "must be built into the system and focused on controlling downside rather "
            "than predicting what happens next."
        ),
        "strategy_implication": (
            "Add explicit per-trade and portfolio-level loss controls and evaluate "
            "strategy quality through drawdown-aware metrics, not hit-rate alone."
        ),
        "confidence": "high",
        "terms": [
            "risk management",
            "possibility of loss",
            "control what they know they can control",
            "risk management built into it",
            "no risk, no return",
        ],
        "allow_margin_quotes": True,
        "alternatives": [],
    },
    {
        "id": "drawdown-001",
        "category": "drawdown_discipline",
        "claim": (
            "The book repeatedly warns against changing a sound system during "
            "drawdowns; discipline means continuing to follow the rules through "
            "losses, boredom, and slow recoveries."
        ),
        "strategy_implication": (
            "Phase 2 should avoid adaptive parameter tweaks triggered by recent "
            "drawdowns and should report drawdown depth/duration so discipline costs "
            "are visible up front."
        ),
        "confidence": "high",
        "terms": [
            "drawdown",
            "no changes because of a drawdown",
            "keep trading the way you were before",
            "willing to live through this",
            "tough out some difficult sledding",
        ],
        "allow_margin_quotes": True,
        "alternatives": [
            "Some interview chapters discuss risk-awareness, but the clearest corpus "
            "constraint is to avoid abandoning rules purely because performance recently hurt."
        ],
    },
    {
        "id": "trend-001",
        "category": "trend_persistence",
        "claim": (
            "Trend following is built on the premise that trends persist across time, "
            "asset classes, and market history more than news narratives explain them."
        ),
        "strategy_implication": (
            "Use medium/long lookbacks and evaluate whether the chosen signal captures "
            "persistent trend continuation across bull, bear, and crisis periods."
        ),
        "confidence": "high",
        "terms": [
            "persistent, pervasive, robust",
            "nature of markets is to trend",
            "trends create events",
            "following the trend",
            "long-term in nature",
        ],
        "allow_margin_quotes": False,
        "alternatives": [],
    },
    {
        "id": "whipsaw-001",
        "category": "whipsaw_handling",
        "claim": (
            "Whipsaws and flat periods are treated as a cost of doing business; the "
            "discipline is to wait through neutral markets and avoid overreacting to "
            "short-term chop."
        ),
        "strategy_implication": (
            "Expect false starts in sideways regimes, keep trade frequency controlled, "
            "and prefer exits/re-entries that reduce churn without losing the next major trend."
        ),
        "confidence": "medium",
        "terms": [
            "whipsaw",
            "neutral, and you are doing nothing",
            "bored through periods of tedium",
            "false breakout",
            "nothing to lose mentality",
        ],
        "allow_margin_quotes": True,
        "alternatives": [
            "The transcripts accept whipsaw as unavoidable; Phase 2 can compare faster "
            "versus slower signals to trade off responsiveness against churn."
        ],
    },
    {
        "id": "portfolio-001",
        "category": "portfolio_market_selection",
        "claim": (
            "Trend following should be diversified across many markets and asset "
            "classes, with portfolio and risk management doing much of the work "
            "once a common signal family is in place."
        ),
        "strategy_implication": (
            "Design the strategy so the same rules can run across broad market groups "
            "and do not tie the logic to one ticker, one asset class, or a stock-only assumption."
        ),
        "confidence": "high",
        "terms": [
            "trade everything",
            "all asset classes",
            "diversified",
            "portfolio and risk management",
            "same strategies apply across all asset classes",
        ],
        "allow_margin_quotes": True,
        "alternatives": [],
    },
    {
        "id": "regime-001",
        "category": "regime_assumptions",
        "claim": (
            "The corpus argues that trend systems should not depend on macro "
            "forecasting, fundamental narratives, or claims that 'this time is "
            "different'; price is treated as the reliable input across regimes."
        ),
        "strategy_implication": (
            "Keep Phase 2 rules price-only by default, avoid macro/fundamental filters "
            "as hard requirements, and explicitly test crisis and quiet regimes."
        ),
        "confidence": "high",
        "terms": [
            "does not require any predictions",
            "fundamentals are not relevant",
            "irrelevant",
            "different this time",
            "there are no facts about the future",
            "price-based approach",
        ],
        "allow_margin_quotes": True,
        "alternatives": [
            "Interview chapters discuss market structure changes, but the book's "
            "strongest repeated stance is to keep the system robust without macro prediction."
        ],
    },
]

FILENAME_RE = re.compile(
    r"^(?P<title>.+?) - (?P<sequence>\d+) - (?P<section>.+)\.txt$"
)


def _parse_source_metadata(path: Path) -> dict[str, object]:
    match = FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Unexpected transcript filename format: {path.name}")

    section = match.group("section")
    chapter_number = None
    chapter_match = re.search(r"Chapter\s+(\d+)", section, flags=re.IGNORECASE)
    if chapter_match:
        chapter_number = int(chapter_match.group(1))

    return {
        "file": str(path),
        "sequence": int(match.group("sequence")),
        "chapter_label": section,
        "chapter": chapter_number,
    }


def _classify_transcript_mode(text: str, chapter_label: str) -> str:
    lowered_label = chapter_label.lower()
    normalized_text = " ".join(text.lower().split())

    if "credits" in lowered_label:
        return "credits"
    if normalized_text.startswith("these are the side-margin quotations"):
        return "margin-quotes"
    if "side-margin quotations" in normalized_text[:500]:
        return "mixed"
    return "narrative"


def _read_transcripts() -> list[dict[str, object]]:
    corpus = []
    for transcript_path in sorted(AUDIO_DIR.glob("*.txt")):
        text = transcript_path.read_text(encoding="utf-8").strip()
        metadata = _parse_source_metadata(transcript_path)
        metadata.update(
            {
                "_text": text,
                "_normalized_text": " ".join(text.lower().split()),
                "mode": _classify_transcript_mode(
                    text=text,
                    chapter_label=str(metadata["chapter_label"]),
                ),
                "processed": True,
                "skip_reason": None,
                "extraction_notes": (
                    "Low-signal audiobook credits retained for coverage."
                    if "credits" in str(metadata["chapter_label"]).lower()
                    else "Quote-heavy chapter supplement retained for citation context."
                    if text.lower().startswith("these are the side-margin quotations")
                    else "Narrative transcript available for principle extraction."
                ),
            }
        )
        corpus.append(metadata)
    return corpus


def _strip_internal_text(corpus_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in corpus_rows
    ]


def _select_sources(
    corpus_rows: list[dict[str, object]],
    terms: list[str],
    *,
    allow_margin_quotes: bool,
    max_sources: int = 4,
) -> list[dict[str, object]]:
    selected = []

    for row in corpus_rows:
        mode = str(row["mode"])
        if mode == "credits":
            continue
        if mode == "margin-quotes" and not allow_margin_quotes:
            continue

        normalized_text = str(row["_normalized_text"])
        if not any(term in normalized_text for term in terms):
            continue

        selected.append(
            {
                "file": str(row["file"]),
                "chapter": row["chapter"],
                "chapter_label": str(row["chapter_label"]),
                "mode": mode,
                "evidence_type": "paraphrase",
            }
        )
        if len(selected) >= max_sources:
            break

    if not selected:
        raise ValueError(f"No transcript evidence found for terms: {terms}")

    return selected


def _build_principles(corpus_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    principles = []
    for blueprint in PRINCIPLE_BLUEPRINTS:
        principles.append(
            {
                "id": blueprint["id"],
                "category": blueprint["category"],
                "claim": blueprint["claim"],
                "sources": _select_sources(
                    corpus_rows,
                    blueprint["terms"],
                    allow_margin_quotes=bool(blueprint["allow_margin_quotes"]),
                ),
                "strategy_implication": blueprint["strategy_implication"],
                "confidence": blueprint["confidence"],
                "alternatives": blueprint["alternatives"],
            }
        )
    return principles


def _build_kb_payload() -> dict[str, object]:
    corpus_rows = _read_transcripts()
    principles = _build_principles(corpus_rows)

    return {
        "corpus": _strip_internal_text(corpus_rows),
        "principles": principles,
        "category_notes": {
            category: "Corpus-backed principle extracted."
            for category in PRINCIPLE_CATEGORIES
        },
        "strategy_handoff": {
            "candidate_rule_families": [
                "Breakout or moving-average entries that act only on price-confirmed trend direction.",
                "Systematic trailing-stop or channel/moving-average exits that let winners run while cutting reversals.",
                "A diversified cross-market implementation so one signal family can trade multiple asset classes.",
            ],
            "candidate_rule_map": [
                {
                    "name": "price_breakout_or_moving_average_entries",
                    "principle_ids": ["entry-001", "trend-001", "regime-001"],
                },
                {
                    "name": "systematic_trailing_or_channel_exits",
                    "principle_ids": ["exit-001", "whipsaw-001", "drawdown-001"],
                },
                {
                    "name": "volatility_scaled_cross_market_portfolio",
                    "principle_ids": ["sizing-001", "risk-001", "portfolio-001"],
                },
            ],
            "risk_constraints": [
                "Use explicit volatility- or risk-budget-based position sizing and cap per-trade and portfolio losses.",
                "Do not change parameters just because the system is in drawdown; report drawdown depth and recovery time instead.",
                "Avoid macro prediction or discretionary fundamental overrides as required inputs to the first strategy spec.",
            ],
            "open_questions": [
                "Which entry/exit family should be implemented first: breakout channels, moving-average trend confirmation, or a hybrid?",
                "What lookback horizon best matches the corpus preference for longer-term trend capture while limiting whipsaw?",
                "What initial volatility/risk budget should be used per position and across the portfolio?"
            ],
            "principle_ids": [principle["id"] for principle in principles],
        },
    }


def _validate_kb_payload(kb_payload: dict[str, object]) -> None:
    expected_files = [str(path) for path in sorted(AUDIO_DIR.glob("*.txt"))]
    corpus_rows = kb_payload.get("corpus", [])
    corpus_files = [str(row.get("file", "")) for row in corpus_rows]
    errors = []

    if corpus_files != expected_files:
        missing_files = sorted(set(expected_files) - set(corpus_files))
        duplicate_files = sorted(
            file_path for file_path in set(corpus_files) if corpus_files.count(file_path) > 1
        )
        errors.append(
            "Corpus index does not match deterministic transcript ordering "
            f"(missing={missing_files}, duplicates={duplicate_files})."
        )

    if len(corpus_files) != len(set(corpus_files)):
        errors.append("Corpus index contains duplicate transcript rows.")

    existing_audio_files = set(expected_files)
    principles = kb_payload.get("principles", [])
    category_notes = kb_payload.get("category_notes", {})
    represented_categories = {
        str(principle.get("category", "")).strip()
        for principle in principles
        if str(principle.get("category", "")).strip()
    }

    for index, principle in enumerate(principles, start=1):
        sources = principle.get("sources")
        if not sources:
            errors.append(f"Principle #{index} is missing `sources`.")
            continue

        if not str(principle.get("strategy_implication", "")).strip():
            errors.append(f"Principle #{index} is missing `strategy_implication`.")

        for source_ref in sources:
            source_file = str(source_ref.get("file", "")).strip()
            if source_file not in existing_audio_files:
                errors.append(
                    f"Principle #{index} references nonexistent source file: {source_file}"
                )

    for category in PRINCIPLE_CATEGORIES:
        if category in represented_categories:
            continue
        note = str(category_notes.get(category, "")).strip().lower()
        if "no strong evidence found" not in note:
            errors.append(
                f"Category `{category}` has no principle and no explicit "
                "`no strong evidence found` note."
            )

    if errors:
        raise ValueError("KB validation failed:\n- " + "\n- ".join(errors))


def _render_markdown(kb_payload: dict[str, object]) -> str:
    corpus = kb_payload["corpus"]
    principles = kb_payload["principles"]
    category_notes = kb_payload["category_notes"]
    strategy_handoff = kb_payload["strategy_handoff"]

    lines = [
        "# Trend-Following Knowledge Base",
        "",
        "Generated from transcript files in `audio/`.",
        "",
        "## Corpus Coverage",
        "",
        f"- Total transcript files processed: {len(corpus)}",
        "- Ordering rule: `sorted(AUDIO_DIR.glob(\"*.txt\"))`",
        "- Skipped files: none",
        "",
        "## Source Index",
        "",
        "| Sequence | Chapter | Mode | File | Extraction Notes |",
        "|----------|---------|------|------|------------------|",
    ]

    for row in corpus:
        lines.append(
            "| {sequence} | {chapter_label} | {mode} | `{file}` | {extraction_notes} |".format(
                sequence=row["sequence"],
                chapter_label=row["chapter_label"],
                mode=row["mode"],
                file=row["file"],
                extraction_notes=row["extraction_notes"],
            )
        )

    lines.extend(
        [
            "",
            "## Principle Catalog",
            "",
        ]
    )

    for category in PRINCIPLE_CATEGORIES:
        category_principles = [
            principle
            for principle in principles
            if principle["category"] == category
        ]
        lines.extend(
            [
                f"### {category}",
                "",
                f"- Status: {category_notes[category]}",
            ]
        )

        for principle in category_principles:
            source_labels = ", ".join(
                f"`{source['file']}` ({source['chapter_label']}, {source['mode']})"
                for source in principle["sources"]
            )
            lines.extend(
                [
                    f"- {principle['id']}: {principle['claim']}",
                    f"  - Evidence: {source_labels}",
                    f"  - Strategy implication: {principle['strategy_implication']}",
                    f"  - Confidence: {principle['confidence']}",
                ]
            )
            if principle["alternatives"]:
                lines.append(
                    "  - Alternatives: "
                    + " | ".join(str(item) for item in principle["alternatives"])
                )
        lines.append("")

    lines.extend(
        [
            "## Strategy Design Implications",
            "",
            "- Candidate rule families:",
        ]
    )

    for rule_family in strategy_handoff["candidate_rule_families"]:
        lines.append(f"  - {rule_family}")

    lines.append("- Principle-linked rule map:")
    for item in strategy_handoff["candidate_rule_map"]:
        lines.append(
            f"  - {item['name']}: {', '.join(item['principle_ids'])}"
        )

    lines.extend(
        [
            "- Risk constraints:",
        ]
    )

    for constraint in strategy_handoff["risk_constraints"]:
        lines.append(f"  - {constraint}")

    lines.extend(
        [
            "- Principle IDs referenced: "
            + ", ".join(strategy_handoff["principle_ids"]),
            "- Open questions:",
        ]
    )

    for question in strategy_handoff["open_questions"]:
        lines.append(f"  - {question}")

    lines.append("")
    return "\n".join(lines)


def write_kb_artifacts() -> dict[str, object]:
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    kb_payload = _build_kb_payload()

    KB_JSON_PATH.write_text(
        json.dumps(kb_payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    KB_MD_PATH.write_text(_render_markdown(kb_payload), encoding="utf-8")
    return kb_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Regenerate the KB scaffold and run validation checks.",
    )
    args = parser.parse_args()

    kb_payload = write_kb_artifacts()
    if args.validate:
        _validate_kb_payload(kb_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
