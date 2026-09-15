Drop these in here:

- `league_logo.png` — referenced by `logo_path` in `config/league.yaml`
- `espn_logo.png`, `nfl_logo.png` — footer logos, referenced directly in `report.html.jinja`

Missing files degrade gracefully (WeasyPrint just omits the image), so the report still renders
without them.
