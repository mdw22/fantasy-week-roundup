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

### Standard Weekly vs. Big Report

Every run builds the full report data; the mode only decides what the PDF shows, so switching back
to the Big Report never needs anything rebuilt.

- **Standard Weekly** (the default): scoreboard and Week at a Glance, standings with playoff odds
  and both rankings, Season Leaders, all team and individual highlights, a short **Waiver Report**
  (the best free agent at each position for next week), next week's projected scores, highlight
  picks and Bold Prediction, one **compact matchup card** per game (records, projections, the top three
  projected players per side, Lineup Watch, the all-time series, and a one-line takeaway: toss-up under 3
  projected points, slight edge under 10, otherwise a clear favorite), and the letter.
- **Big Report**: everything in Standard, but with the graded Waiver Report Card, the full
  Matchup Analysis cards and full Suggested Pickups list in place of their short versions, plus
  Appendix A (season stats) and Appendix B (lifetime stats), and a "Big Edition" cover.

Big Report weeks are listed in `config/league.yaml`:

```yaml
big_report_weeks: [3, 8]
```

Override the schedule for a single run with `--big` or `--standard`, e.g.
`./run.sh --week 5 --letter-file drafts/week_5_2026_letter.txt --big`. The mode only affects
rendering, so the letter draft is the same either way.

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

A third section, `===BOLD PREDICTION===`, holds one prediction for next week's games (the same
letter call writes it, from a compact `next_week` block of projections and records that it's told
to use only for the prediction). It appears as the last row of the preview's highlights. Edit it
freely; delete the section, or write `nothing new`, to leave that row out. Sections are found by
marker, in any order, so older drafts without this section still work.

## Running tests

```bash
pip install pytest
pytest tests/
```

`tests/test_stats.py` covers the highlight math in `src/stats.py`, and `tests/test_history.py` the
lifetime stats in `src/history.py`, against fixture data — no live ESPN connection or API key
required.

## Project layout

See `src/espn_client.py` (league connection + raw fetches), `src/stats.py` (highlight math),
`src/narrative.py` (Commissioner's Letter prompt + Claude API call), `src/history.py` (past
seasons and lifetime stats), `src/waivers.py` (report card and pickups), `src/casualties.py` (Casualty Report), `src/preview.py` (next
week's preview), `src/report_data.py`
(assembles one `WeekReport` per run), `src/render.py` (Jinja2 + WeasyPrint → PDF), and
`src/main.py` (CLI entry point).

## What's in each report

Cover, then scoreboard (with a "Week N at a Glance" score bar chart), standings, team highlights,
individual highlights, and the Waiver Report Card (Part I, the week just played); Part II, next
week's preview (projected scores, highlight picks, a Matchup Analysis card per game, Suggested
Pickups); two appendices (Big Report weeks only, see above); and the Commissioner's Letter last.

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
- **Waiver Report Card** — every add (waiver, free agent, trade) made after the previous week's
  last game through this week's last game, graded on the player's points that week (A 20+, B 12+,
  C 6+, D above 0, F zero or less; thresholds in `src/waivers.py`), with a "Bench" tag when the new
  team didn't start him. Current Status shows where the player is as of the report: On Roster,
  Dropped (back on waivers or free agency), or on another team. Dropped players who scored 15+ anyway show under "Drops That Bit Back".
  A week ends at 6 a.m. ET the morning after its last game (from the nflverse schedule), so moves
  made Monday night or Tuesday are graded in the next report instead.
- **Suggested Pickups** — the top two free agents at each position by ESPN's projection for next
  week, with last week's points and % rostered. Only built when the report is for the latest completed week (a
  backfill can't know who was available back then) and there is a next week.
- **Casualty Report** — under the waiver table in both modes: which teams have lost the most
  starters to injury this season, and who was hurt this week. A regular starter (started for the
  team at least once, or was one of its first four draft picks) is hurt in a week if he missed
  the game hurt (on that week's injury report, on NFL injured reserve, or in the fantasy IR slot)
  or left the game and didn't return, confirmed by him still being hurt afterwards so one-play
  breathers don't count. Byes never count. Columns: **Starters Hurt** (distinct players, the
  ranking number), **Weeks Affected** ("3 of 4": weeks with at least one starter hurt, never more
  than the weeks played), **Biggest Loss** (earliest draft pick, e.g. "1st-round pick"), and
  **Hurt in Week N** (surnames one per line, "(out)" / "(IR)" if still out today, or "None").
  Ties break on total player-games missed, then draft position, then standings; none of those
  are printed. Up to 6 teams in Standard and 3 in Big, fewer if their Hurt column runs long, so
  it never spills off the page. Latest completed week only, and never sent to the letter
  (`src/casualties.py`, with nflverse injury reports, weekly rosters and play-by-play for past
  weeks).
- **Week N+1 Preview** — ESPN's projected scores for next week (lineups as of the report, which
  managers can still change), then rule-based picks, each on a different game where possible:
  Game of the Week (most combined wins, then closest projection), Blowout Watch (widest projected
  margin), Upset Alert (the underdog who out-averages the favorite by the most, else the closest
  game left), and Biggest Playoff Implications (the game whose seeds sit nearest the playoff line;
  regular season only). The Bold Prediction row comes from the letter call, written plainly
  (no theme, titles or nicknames). Each **Matchup
  Analysis** card shows both teams' abbreviation, manager, record, streak, seed, season average,
  last week's result, top three projected starters, a Lineup Watch (starters flagged Out /
  Doubtful / Questionable / IR / Suspended / Bye, plus IR-slot players who are Questionable or
  Doubtful and might return), the projected favorite, and the all-time regular-season
  series. Playoff odds stay on the Standings page. Like the pickups, the preview is only built
  for the latest completed week.
- **Appendix A: Season Stats** — per team through the report week: record, all-play record, PF,
  PA, average, high and low week, points left on the bench (best possible lineup minus actual,
  filling single-position slots first, then the flex), the latest week's max (what the best
  possible lineup would have scored that week), and weeks beating their own projection.
- **Appendix B: Lifetime Stats** — all-time records (seasons, W-L-T, win %, PF, average, titles,
  playoff appearances), champions, a record book, and a rivalry summary (for each manager, Best Record
  Against, the opponent they have the best record against, and Nemesis, the opponent with the best record
  against them; minimum two meetings). Regular-season games only, since ESPN's
  playoff weeks include consolation games. Managers are keyed by ESPN owner ID, so team renames
  don't split a record, and owner IDs that ever shared a team (co-owners, or one person with two
  ESPN accounts) count as one manager.

  Past seasons are cached in `data/history/<year>.json` (committed; a finished season never
  changes) and fetched automatically the first time a year is missing. Pass `--refresh-history`
  to re-download them. The current season is always read live. If history can't be loaded, the
  appendix is skipped with a warning.

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
