# fantasy-week-roundup

Generates a styled weekly PDF recap of the Phi Fantasy Football League from ESPN's fantasy API —
a scoreboard, stat-highlight tables, current standings, and an AI-written "Commissioner's Letter"
narrating the week in the league's running Game of Thrones theme.

## Setup

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

WeasyPrint (PDF rendering) needs system libraries beyond pip:

- **macOS:** `brew install pango`
- **Ubuntu/Debian** (also what the GitHub Actions workflow installs):
  `apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0`

### Configuration

1. Copy `.env.example` to `.env` and fill in:
   - `LEAGUE_ID`, `SEASON_YEAR` — from your league's ESPN URL
   - `ESPN_S2`, `SWID` — session cookies from browser dev tools while logged into ESPN Fantasy
     (private-league auth; quote both values)
   - `ANTHROPIC_API_KEY` — for the Commissioner's Letter narrative
2. Copy `config/league.yaml.example` to `config/league.yaml` and fill in league name,
   commissioner persona, narrative theme, and any team nickname overrides.
3. (Optional) Copy `config/power_rankings_override.yaml.example` to
   `config/power_rankings_override.yaml` to manually set the "Commissioner" power-rankings column
   before a run; omitted teams fall back to ESPN's algorithmic ranking.

`.env`, `config/league.yaml`, and `config/power_rankings_override.yaml` are all gitignored —
they're account-specific and shouldn't be committed. `config/lore.md` *is* committed: it's an
append-only running log the narrative generator reads for continuity and writes to after each
run. Each week's entry combines a factual, code-generated score summary with a short lore note
Claude writes alongside the letter itself (any new nicknames, running jokes, or callbacks worth
remembering) — so storylines the model invents can carry forward automatically, not just raw
scores. If a week's letter didn't introduce anything new, only the factual summary is kept.

## Usage

```bash
python -m src.main                # most recently completed week
python -m src.main --week 3       # explicit week override, for backfilling/testing
```

Output lands in `reports/week_<N>_<year>.pdf` and is committed back to the repo (see §7/§9 of
the design spec for why: the tool is stateless and re-fetches ESPN data each run, except for the
lore file).

### Editing the Commissioner's Letter before it renders

To review or hand-edit the narrative before it's baked into a PDF, split the run into two steps:

```bash
python -m src.main --week 3 --draft-only
# -> writes drafts/week_3_2026_letter.txt and prints the follow-up command

# edit drafts/week_3_2026_letter.txt by hand, then:
python -m src.main --week 3 --letter-file drafts/week_3_2026_letter.txt
```

`--draft-only` generates the letter and stops — it doesn't touch the lore file or render a PDF.
`--letter-file` skips narrative generation entirely and uses that file's contents verbatim as the
letter, then proceeds normally (lore update + PDF render). `drafts/` is gitignored — it's scratch
space, not part of the committed report history. Note that each step re-fetches ESPN data
independently (per the stateless design above), so if scores get corrected between the two steps,
the rendered tables could reflect newer data than what the letter was written against — rare, but
worth a re-read if you edit long after generating the draft.

The draft file has a trailing section marked `===LORE NOTE===` below the letter — that's Claude's
own short summary of anything worth remembering next week, and it's what feeds `config/lore.md`
once you finalize with `--letter-file`. You can edit it just like the letter, or delete it
entirely if you'd rather that week not add anything to the lore log.

## Running tests

```bash
pip install pytest
pytest tests/
```

`tests/test_stats.py` covers the highlight math in `src/stats.py` against fixture data — no live
ESPN connection or API key required.

## Project layout

See `src/espn_client.py` (league connection + raw fetches), `src/stats.py` (highlight math),
`src/narrative.py` (Commissioner's Letter prompt + Claude API call), `src/report_data.py`
(assembles one `WeekReport` per run), `src/render.py` (Jinja2 + WeasyPrint → PDF), and
`src/main.py` (CLI entry point).

## Known gaps (Phase 2)

- **Rookie Spotlight** and **Gamecock of the Week** are stubbed in `src/stats.py` — both need
  cross-referencing ESPN roster data against `nflreadpy` (rookie-year flags; South Carolina alums
  and their weekly stat lines), which isn't wired up yet.
- **Season-finale bonus sections** (PF trendlines, All-Fantasy Team, season appendix, etc.) have
  a template hook (`report.is_season_finale`) but no data yet — `report_data.py` doesn't populate
  `WeekReport.season_extras`.

## Automation

`.github/workflows/weekly-report.yml` runs the generator on a schedule (Tuesday mornings, after
Monday Night Football stats finalize) and on manual dispatch, committing the new PDF and updated
lore file back to the repo. Requires repo secrets: `LEAGUE_ID`, `SEASON_YEAR`, `ESPN_S2`, `SWID`,
`ANTHROPIC_API_KEY`.
