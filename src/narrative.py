"""Builds the Commissioner's Letter: structured week summary -> Claude prompt -> prose.

Kept separate from report_data.py so the prompt can be iterated on independently
of the data pipeline (see design spec §5).
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic

from .report_data import WeekReport
from .stats import PlayerStat, TeamStat

MODEL = "claude-opus-5"

LORE_NOTE_MARKER = "===LORE NOTE==="
NOTHING_NEW_SENTINEL = "nothing new"

SYSTEM_PROMPT = f"""You are the ghostwriter for a fantasy football league's weekly recap letter. \
You write in the voice of the persona the user gives you, staying fully in the theme the user \
gives you. You are given structured data about the week's matchups and standout performances, \
plus a running "lore" log of nicknames and storylines from prior weeks.

Write one flowing narrative, roughly 500-800 words, that:
- References every matchup listed, using real scores and margins naturally rather than just
  restating a table
- Stays in-theme throughout
- Weaves in the team/individual highlights and standings context where they add color
- Builds on established lore/callbacks where natural, rather than starting cold
- Ends with a short closing line in the persona's voice (e.g. "Until next week," or an in-theme
  equivalent) — do NOT sign the name or title at the end. The document this letter is rendered
  into already appends a formatted signature block with the persona's name below the body, so
  signing it yourself would duplicate that.

Write in plain prose: no markdown formatting of any kind (no **bold**, no headers, no bullet
points) — the letter is rendered as plain paragraphs in a PDF, so markdown syntax would appear
as literal asterisks.

After the letter, on its own line, write the exact marker "{LORE_NOTE_MARKER}", then on the
following line write one or two short, plain (out-of-character, third person) sentences naming
any new nicknames, running jokes, storylines, or callbacks you introduced this week that are
worth remembering and possibly referencing in future weeks. If you didn't introduce anything
worth carrying forward beyond the factual results, write "{NOTHING_NEW_SENTINEL}" instead.

Output nothing else — no preamble, no meta-commentary before the letter or after the lore note."""


def _team_stat_to_dict(stat: TeamStat) -> dict:
    return {"team": stat.team_name, "value": round(stat.value, 2), "detail": stat.detail}


def _player_stat_to_dict(stat: PlayerStat) -> dict:
    return {
        "player": stat.player_name,
        "fantasy_team": stat.team_name,
        "pro_team": stat.pro_team,
        "position": stat.position,
        "points": round(stat.points, 2),
    }


def build_week_summary(report: WeekReport) -> dict:
    return {
        "week": report.week,
        "matchups": [
            {
                "home_team": m.home_team_name,
                "away_team": m.away_team_name,
                "home_score": m.home_score,
                "away_score": m.away_score,
                "margin": round(abs(m.home_score - m.away_score), 2),
                "projected_margin_home": round(m.home_projected - m.away_projected, 2),
                "winner": m.winner_name,
            }
            for m in report.matchups
        ],
        "team_highlights": {
            label: _team_stat_to_dict(stat) for label, stat in report.team_highlights.items()
        },
        "individual_highlights": {
            label: _player_stat_to_dict(stat) for label, stat in report.individual_highlights.items()
        },
        "standings": [
            {
                "team": row.team_name,
                "division": row.division_name,
                "record": f"{row.wins}-{row.losses}-{row.ties}",
                "points_for": round(row.points_for, 2),
                "streak": row.streak,
                "playoff_pct": row.playoff_pct,
            }
            for row in report.standings
        ],
    }


def read_lore(lore_path: str | Path) -> str:
    path = Path(lore_path)
    return path.read_text() if path.exists() else ""


def append_lore_entry(lore_path: str | Path, week: int, summary_line: str) -> None:
    """Add this week's one-line summary, replacing any existing entry for the same week rather
    than duplicating it — re-running a week (e.g. after editing a letter draft, or backfilling)
    is a normal part of the workflow, not a new event in the league's history."""
    path = Path(lore_path)
    new_line = f"- **Week {week}:** {summary_line}"
    week_marker = f"- **Week {week}:**"

    lines = path.read_text().splitlines() if path.exists() else []
    if any(line.startswith(week_marker) for line in lines):
        lines = [new_line if line.startswith(week_marker) else line for line in lines]
        path.write_text("\n".join(lines) + "\n")
    else:
        with open(path, "a") as f:
            f.write(new_line + "\n")


def build_prompt(theme: str, commissioner_name: str, week_summary: dict, lore_text: str) -> str:
    return f"""League theme: {theme}
Persona: {commissioner_name}

Running lore log (prior weeks' storylines and callbacks):
{lore_text or "(no prior lore yet — this is the first entry)"}

This week's structured data:
{json.dumps(week_summary, indent=2)}

Write this week's letter now."""


def split_letter_and_lore_note(raw_text: str) -> tuple[str, str]:
    """Split the model's raw response into (letter, lore_note). Falls back to treating the
    whole thing as the letter with no note if the marker is missing — e.g. when a hand-edited
    draft dropped it, or an older-format draft file is passed to --letter-file."""
    if LORE_NOTE_MARKER in raw_text:
        letter_part, _, note_part = raw_text.partition(LORE_NOTE_MARKER)
        return letter_part.strip(), note_part.strip()
    return raw_text.strip(), ""


def generate_commissioners_letter(
    report: WeekReport,
    theme: str,
    commissioner_name: str,
    lore_path: str | Path,
    client: anthropic.Anthropic | None = None,
) -> tuple[str, str]:
    """Returns (letter, lore_note) — lore_note is a short out-of-character summary of anything
    new this week's letter introduced that's worth remembering, or "" if nothing was."""
    client = client or anthropic.Anthropic()
    week_summary = build_week_summary(report)
    lore_text = read_lore(lore_path)
    prompt = build_prompt(theme, commissioner_name, week_summary, lore_text)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = next(block.text for block in response.content if block.type == "text")
    return split_letter_and_lore_note(raw_text)


def summarize_matchups_for_lore(report: WeekReport) -> str:
    """One-line, plain-English recap for the lore file — independent of the letter's prose,
    so future runs have a factual record even if the narrative style drifts."""
    lines = []
    for m in report.matchups:
        winner_score = max(m.home_score, m.away_score)
        loser_score = min(m.home_score, m.away_score)
        loser = m.away_team_name if m.winner_name == m.home_team_name else m.home_team_name
        lines.append(f"{m.winner_name} beat {loser} {winner_score:.1f}-{loser_score:.1f}")
    return "; ".join(lines)


def combine_lore_summary(factual_summary: str, lore_note: str) -> str:
    """Merges the factual score summary with the model's own lore note, if it offered one
    worth keeping (skips the "nothing new" sentinel and empty notes)."""
    note = lore_note.strip()
    if not note or note.lower().startswith(NOTHING_NEW_SENTINEL):
        return factual_summary
    return f"{factual_summary} — {note}"
