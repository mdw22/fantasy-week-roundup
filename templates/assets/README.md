Drop these in here:

- `league_logo.png` — referenced by `logo_path` in `config/league.yaml`. If missing (or the file
  doesn't exist), the cover page falls back to a generated wax-seal emblem instead.
- `espn_logo.png`, `nfl_logo.png` — footer logos, referenced directly in `report.html.jinja`

Missing files degrade gracefully (checked via `render.asset_exists()`), so the report still
renders without them.

## Bundled assets

- `fonts/` — Cinzel (headings/display) and EB Garamond (body text), both Google Fonts under the
  SIL Open Font License. Embedded locally via `@font-face` in `styles.css` rather than fetched
  from Google's CDN, so rendering doesn't depend on network access at report-generation time
  (important for the GitHub Actions runner).
- `corner-flourish.svg`, `divider-ornament.svg` — original line-art ornaments (not show/book
  artwork) used on the cover page and the letter section for a heraldic feel.

The wax-seal emblem (used as the cover fallback and next to the letter's signature) is generated
inline in `report.html.jinja` rather than a static file, since its monogram letter is derived
from `commissioner_name` in `config/league.yaml`.
