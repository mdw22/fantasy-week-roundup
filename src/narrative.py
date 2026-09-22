"""Builds the Commissioner's Letter: structured week summary -> Claude prompt -> prose.

Kept separate from report_data.py so the prompt can be iterated on independently
of the data pipeline (see design spec §5).
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic
import yaml

from .report_data import WeekReport
from .stats import InjuryNote, PlayerStat, TeamStat

MODEL = "claude-opus-5"

LORE_NOTE_MARKER = "===LORE NOTE==="
NICKNAME_MARKER = "===NICKNAMES==="
NOTHING_NEW_SENTINEL = "nothing new"

SYSTEM_PROMPT = f"""You are the ghostwriter for a fantasy football league's weekly recap letter. \
You write in the voice of the persona the user gives you, staying fully in the theme the user \
gives you. You are given structured data about the week's matchups and standout performances, \
plus a running "lore" log of nicknames and storylines from prior weeks.

Player titles: every skill-position player you name gets a title before their name, by position —
QB: "Lord", RB: "Knight", WR: "Swordsman", TE: "Squire", K: "Cannoneer" (a nod to the siege weapons
of the era). A defense/special-teams unit isn't a person, so never give it one of those titles —
call it "the Shield Wall" or "the Men-at-Arms" instead (pick one and stay consistent within a
single letter). Apply titles by the `position` field in the structured data, not guesswork.

First mention vs. later mentions: the *first* time a player appears in the letter, use their title
plus full name (first and last) — Lord Patrick Mahomes, Knight Derrick Henry, Swordsman Justin
Jefferson, Squire Travis Kelce, Cannoneer Justin Tucker. Every mention of that same player after
the first drops to just the title and surname — Lord Mahomes, Knight Henry — rather than repeating
the full name each time.

Legendary nicknames: a handful of the season's standout players — a dominant season-long scorer, an
especially historic single-week performance — earn a legendary nickname woven into their title,
between the title and their name: Lord "The Dragon" Patrick Mahomes on first mention, shortening to
Lord "The Dragon" Mahomes (or just "the Dragon") on later mentions in the same letter, following the
same first-mention/later-mention rule as any other titled player. Use judgment on who's earned one;
not every MVP or top scorer needs one, and a mediocre week from an already-legendary player doesn't
cost them theirs. The prompt below lists nicknames already established in past weeks — you MUST
reuse those exact nicknames whenever that player comes up again, word for word; never rename a
player who already has one, and never invent a second nickname for the same player. Only coin a
brand new nickname for a player who doesn't have one yet.

Write one flowing narrative, roughly 500-800 words, that:
- References every matchup listed, using real scores and margins naturally rather than just
  restating a table
- Stays in-theme throughout
- Weaves in the team/individual highlights and standings context where they add color
- If the structured data lists any injuries, you may work in a mention of one or two if they fit
  naturally (e.g. a fantasy team's win explained by a key player leaving the game) — this is
  optional color, not a requirement; skip it entirely on a week where none feel narratively
  relevant. Severity is unknown (all that's known is the player left a game and didn't return), so
  stay vague and don't invent detail (body part, diagnosis, timeline) — treat it the way you'd
  actually feel about a rival's starter going down: closer to "hope they're alright" / "here's
  hoping [team] gets good news" than a medical report
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

After that, on its own line, write the exact marker "{NICKNAME_MARKER}", then list every BRAND
NEW legendary nickname you coined in this letter (see "Legendary nicknames" above) — one per
line, exactly in this format, nothing else on the line:
Full Player Name | POSITION | Full styled title+nickname+full name
For example: Patrick Mahomes | QB | Lord "The Dragon" Patrick Mahomes
Only list players who did not already have an established nickname going into this week. Do not
list players who only got the plain positional title (Lord/Knight/Swordsman/Squire/Cannoneer)
without an actual nickname. If you didn't coin any new nicknames this week, write
"{NOTHING_NEW_SENTINEL}" instead.

Output nothing else — no preamble, no meta-commentary before the letter or after the nicknames."""


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


def _injury_note_to_dict(note: InjuryNote) -> dict:
    return {
        "player": note.player_name,
        "fantasy_team": note.team_name,
        "pro_team": note.pro_team,
        "position": note.position,
        "note": note.description,
    }


def _season_scorer_to_dict(scorer) -> dict:
    return {
        "player": scorer.player_name,
        "fantasy_team": scorer.team_name,
        "pro_team": scorer.pro_team,
        "position": scorer.position,
        "season_points": round(scorer.points, 2),
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
        "injuries": [_injury_note_to_dict(note) for note in report.injuries],
        "season_leaders": (
            {
                "top_teams": [
                    {"team": name, "season_points": round(points, 2)}
                    for name, points in report.season_leaders.top_teams
                ],
                "top_scorers": [
                    _season_scorer_to_dict(s) for s in report.season_leaders.top_scorers
                ],
            }
            if report.season_leaders
            else None
        ),
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


_NICKNAME_REGISTRY_HEADER = """\
# Legendary player nicknames coined in the Commissioner's Letter, carried across the season.
# Auto-updated after each week: once a player is listed here, the letter is instructed to keep
# using their exact nickname rather than coining a new one. Safe to hand-edit (e.g. to fix a
# nickname, or delete an entry to let the letter retire/replace it).
"""


def read_nicknames(nicknames_path: str | Path) -> dict[str, dict]:
    path = Path(nicknames_path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def format_nickname_registry(nicknames: dict[str, dict]) -> str:
    """Renders the registry for the prompt — plain text, not YAML, since the model only needs to
    read these, never edit them in place."""
    if not nicknames:
        return "(none established yet — this is the first player to earn one, if any do)"
    return "\n".join(
        f'- {name} ({info.get("position", "?")}): {info["nickname"]}'
        for name, info in nicknames.items()
    )


def parse_new_nicknames(nicknames_text: str) -> dict[str, dict]:
    """Parses the model's raw "{name} | {position} | {nickname}" lines (see NICKNAME_MARKER's
    instructions in SYSTEM_PROMPT) into {name: {"position": ..., "nickname": ...}}. Malformed
    lines (wrong number of '|'-fields, or a blank name/nickname) are skipped rather than raising —
    a stray line in freeform model output shouldn't take down the whole run."""
    text = nicknames_text.strip()
    if not text or text.lower().startswith(NOTHING_NEW_SENTINEL):
        return {}
    result = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.strip().lstrip("-").split("|")]
        if len(parts) != 3:
            continue
        name, position, nickname = parts
        if name and nickname:
            result[name] = {"position": position, "nickname": nickname}
    return result


def append_nicknames(nicknames_path: str | Path, new_nicknames: dict[str, dict], week: int) -> None:
    """Adds newly-coined nicknames to the registry, keyed by player name. Never overwrites an
    already-established nickname (the model is instructed not to send one, but this is the backstop
    if it does anyway). Appends rather than rewriting the whole file, same reasoning as
    report_data.ensure_power_rankings_override: round-tripping through yaml.safe_load + safe_dump
    would silently strip the header comment and any comments on existing entries."""
    if not nicknames_path or not new_nicknames:
        return
    path = Path(nicknames_path)
    existing_text = path.read_text() if path.exists() else ""
    existing = yaml.safe_load(existing_text) or {} if existing_text.strip() else {}

    to_add = {
        name: {"position": info["position"], "nickname": info["nickname"], "established_week": week}
        for name, info in new_nicknames.items()
        if name not in existing
    }
    if not to_add:
        return

    block = yaml.safe_dump(to_add, default_flow_style=False, sort_keys=False, allow_unicode=True)
    with open(path, "a") as f:
        if not existing_text:
            f.write(_NICKNAME_REGISTRY_HEADER + "\n")
        elif not existing_text.endswith("\n"):
            f.write("\n")
        f.write("\n" + block)


def build_prompt(
    theme: str, commissioner_name: str, week_summary: dict, lore_text: str, nickname_registry_text: str
) -> str:
    return f"""League theme: {theme}
Persona: {commissioner_name}

Running lore log (prior weeks' storylines and callbacks):
{lore_text or "(no prior lore yet — this is the first entry)"}

Established player nicknames so far this season (reuse these exact nicknames verbatim; do not
rename anyone or invent a second nickname for a player already on this list):
{nickname_registry_text}

This week's structured data:
{json.dumps(week_summary, indent=2)}

Write this week's letter now."""


def split_response(raw_text: str) -> tuple[str, str, str]:
    """Split the model's raw response into (letter, lore_note, nicknames_text). Falls back
    gracefully when a marker is missing — e.g. a hand-edited draft that dropped a section, or an
    older-format draft file passed to --letter-file from before a marker existed."""
    if LORE_NOTE_MARKER not in raw_text:
        return raw_text.strip(), "", ""
    letter_part, _, rest = raw_text.partition(LORE_NOTE_MARKER)
    if NICKNAME_MARKER not in rest:
        return letter_part.strip(), rest.strip(), ""
    lore_part, _, nickname_part = rest.partition(NICKNAME_MARKER)
    return letter_part.strip(), lore_part.strip(), nickname_part.strip()


def generate_commissioners_letter(
    report: WeekReport,
    theme: str,
    commissioner_name: str,
    lore_path: str | Path,
    nicknames_path: str | Path,
    client: anthropic.Anthropic | None = None,
) -> tuple[str, str, str]:
    """Returns (letter, lore_note, nicknames_text) — lore_note is a short out-of-character summary
    of anything new this week's letter introduced that's worth remembering (or "" if nothing was);
    nicknames_text is the raw "Name | Position | Nickname" lines for any brand-new legendary
    nicknames coined this week (or "" if none), meant to be passed to parse_new_nicknames()."""
    client = client or anthropic.Anthropic()
    week_summary = build_week_summary(report)
    lore_text = read_lore(lore_path)
    nickname_registry_text = format_nickname_registry(read_nicknames(nicknames_path))
    prompt = build_prompt(theme, commissioner_name, week_summary, lore_text, nickname_registry_text)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = next(block.text for block in response.content if block.type == "text")
    return split_response(raw_text)


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
