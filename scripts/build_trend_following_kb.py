#!/usr/bin/env python3
"""Generate a source-indexed trend-following knowledge-base scaffold."""

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


def _build_kb_payload() -> dict[str, object]:
    return {
        "corpus": _read_transcripts(),
        "principles": [],
        "category_notes": {
            category: "no strong evidence found yet - scaffold awaiting 01-02 extraction"
            for category in PRINCIPLE_CATEGORIES
        },
        "strategy_handoff": {
            "candidate_rule_families": [],
            "risk_constraints": [],
            "open_questions": [
                "Populate this section in 01-02 after transcript principles are extracted."
            ],
            "principle_ids": [],
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
        lines.extend(
            [
                f"### {category}",
                "",
                f"- Status: {category_notes[category]}",
                "",
            ]
        )

    lines.extend(
        [
            "## Strategy Design Implications",
            "",
            "- Candidate rule families: "
            + (
                ", ".join(strategy_handoff["candidate_rule_families"])
                if strategy_handoff["candidate_rule_families"]
                else "to be extracted in 01-02"
            ),
            "- Risk constraints: "
            + (
                ", ".join(strategy_handoff["risk_constraints"])
                if strategy_handoff["risk_constraints"]
                else "to be extracted in 01-02"
            ),
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
