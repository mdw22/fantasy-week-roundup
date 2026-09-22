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

**macOS runtime note:** installing Pango isn't enough by itself — Python needs
`DYLD_LIBRARY_PATH=/opt/homebrew/lib` set *every time you run the program*, or WeasyPrint fails
to import with `OSError: cannot load library 'libgobject-2.0-0'`. `./run.sh` (see Usage) sets
this for you; if you'd rather run `python -m src.main` directly, export it yourself first:
`export DYLD_LIBRARY_PATH=/opt/homebrew/lib`.

**If ESPN/nflreadpy requests fail with `CERTIFICATE_VERIFY_FAILED`** (seen on a network whose
proxy injects its own root certificate, e.g. some corporate networks): export a CA bundle built
from your Mac's own trusted certificates and point Python at it —

```bash
mkdir -p .python
security find-certificate -a -p /Library/Keychains/System.keychain \
  /System/Library/Keychains/SystemRootCertificates.keychain > .python/macos-ca-bundle.pem
export SSL_CERT_FILE="$PWD/.python/macos-ca-bundle.pem"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
```

`./run.sh` picks this up automatically if the file exists at that path — regenerate it if your
network's certificate ever changes. `.python/` is gitignored, so this stays local to the machine.

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
they're account-specific and shouldn't be committed. `config/lore.md` and `config/nicknames.yaml`
*are* committed: they're the narrative generator's persistent memory, read for continuity and
written to after each run.

- `config/lore.md` — one line per week, combining a factual, code-generated score summary with a
  short lore note Claude writes alongside the letter itself (running jokes, storylines, callbacks
  worth remembering). If a week's letter didn't introduce anything new, only the factual summary
  is kept.
- `config/nicknames.yaml` — legendary player nicknames (e.g. `Lord "The Dragon" Mahomes`) Claude
  coins for standout performers over the season. Once a player is in this registry, every future
  letter is instructed to reuse that exact nickname rather than renaming them or coining a second
  one. See "Player titles" and "Legendary nicknames" in `src/narrative.py`'s `SYSTEM_PROMPT` for
  the full rules (a title by position for every named player — QB/RB/WR/TE/K each get one; D/ST
  is referred to collectively — plus this registry for the subset who earn an actual nickname).

## Usage

```bash
python -m src.main                # most recently completed week
python -m src.main --week 3       # explicit week override, for backfilling/testing
```

On macOS, `./run.sh` is a drop-in replacement for `python -m src.main` (same arguments, e.g.
`./run.sh --week 3 --draft-only`) that sets `DYLD_LIBRARY_PATH` and, if present, the local CA
bundle described below — so you don't have to export either by hand. It's a local dev convenience,
not used by CI.

Output lands in `reports/week_<N>_<year>.pdf` and is committed back to the repo (see §7/§9 of
the design spec for why: the tool is stateless and re-fetches ESPN data each run, except for the
lore file).

### Editing the Commissioner's Letter before it renders

To review or hand-edit the narrative before it's baked into a PDF, split the run into two steps:

```bash
./run.sh --week 3 --draft-only
# -> writes drafts/week_3_2026_letter.txt and prints the follow-up command

# edit drafts/week_3_2026_letter.txt by hand, then:
./run.sh --week 3 --letter-file drafts/week_3_2026_letter.txt
```

(On Linux/CI, or if you're not using `run.sh`, the same two commands work as
`python -m src.main --week 3 --draft-only` and `python -m src.main --week 3 --letter-file ...`.)

`--draft-only` generates the letter and stops — it doesn't touch the lore file or render a PDF.
`--letter-file` skips narrative generation entirely and uses that file's contents verbatim as the
letter, then proceeds normally (lore update + PDF render). `drafts/` is gitignored — it's scratch
space, not part of the committed report history. Note that each step re-fetches ESPN data
independently (per the stateless design above), so if scores get corrected between the two steps,
the rendered tables could reflect newer data than what the letter was written against — rare, but
worth a re-read if you edit long after generating the draft.

The draft file has trailing sections marked `===LORE NOTE===` and `===NICKNAMES===` below the
letter — Claude's own summary of anything worth remembering next week, and any brand-new legendary
nicknames it coined this week, respectively. These are what feed `config/lore.md` and
`config/nicknames.yaml` once you finalize with `--letter-file`. Edit either section like the
letter, or delete one entirely if you'd rather that week not add anything to that particular log —
deleting `===NICKNAMES===` (or the whole file) is also how you'd veto a nickname you don't like
before it becomes permanent.

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

## What's in each report

Cover, then scoreboard (with a "Week N at a Glance" score bar chart), standings, team highlights,
individual highlights, and the Commissioner's Letter.

- **Rank movement** — Power Rank and Mike's Rankings show how many places a team moved since last
  week. ESPN's power rankings are recomputed from each team's scoring history through a given week
  (`espn_api` `power_rankings(week)`), so last week's ranking is available on demand and **no state
  is stored between runs**. Week 1 shows no markers. Mike's Rankings compares against last week's
  manual override where a team has one, otherwise last week's algorithmic rank.
- **Luckiest Win / Unluckiest Loss** — from the week's all-play record (how many of the other 13
  teams' scores a team would have beaten). A row only appears when its "despite ranking Nth of 14"
  claim is true.
- **Season Leaders** (Week 2 onward) — top 3 teams by season points and top 3 players by season
  fantasy points, counting only points earned while starting (same rule as Individual MVP). This
  fetches every week's box scores each run (~0.6s per week, about 10s for a full season).

## Supplemental NFL data

**Rookie Spotlight** and **Gamecock of the Week** are the two league-wide awards: they use
`nflreadpy` (via `src/nfl_supplemental.py`) for facts ESPN doesn't expose, and either can go to
a player no fantasy team rosters (the report shows a "Free agent" tag).

- **Rookie Spotlight** — best rookie QB/RB/WR/TE of the week (`years_exp == 0`), scored with
  nflverse's `fantasy_points_ppr`, which matches this league's ESPN scoring exactly for those
  positions (verified 192/192 on rostered players). Rookies with no ESPN ID in nflverse (mostly
  undrafted/practice-squad players) are skipped, since we can't tell whether a team rosters them.
- **Gamecock of the Week** — South Carolina alumni (any school in a player's semicolon-delimited
  `college` list, so transfers count) with their weekly defensive/offensive stat lines.

Every other individual award (MVP, Top QB/RB/WR/TE/D-ST/K, Bench MVP) deliberately stays
best-rostered-*starter* (Bench MVP: rostered bench), computed from ESPN box scores. If an nflreadpy
lookup fails or its schema changes, that award is skipped with a printed warning rather than
failing the report.

## Known gaps (Phase 2)

- **Season-finale bonus sections** (PF trendlines, All-Fantasy Team, season appendix, etc.) have
  a template hook (`report.is_season_finale`) but no data yet — `report_data.py` doesn't populate
  `WeekReport.season_extras`.

## Automation

`.github/workflows/weekly-report.yml` can generate the report on GitHub, committing the new PDF and
updated lore file back to the repo. **The weekly schedule is currently turned off** — the workflow
only runs when started by hand from the Actions tab ("Run workflow", with an optional week number).
To re-enable the Tuesday-morning schedule, restore the `schedule:` trigger described in a comment at
the top of the workflow file. Runs need the repo secrets `LEAGUE_ID`, `SEASON_YEAR`, `ESPN_S2`,
`SWID`, `ANTHROPIC_API_KEY`.
