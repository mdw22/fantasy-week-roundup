#!/bin/sh
# Local convenience wrapper for macOS: sets the environment this machine needs
# and runs the report generator, so you don't have to remember these each time.
#
#   ./run.sh                 same as: python -m src.main
#   ./run.sh --week 3        same as: python -m src.main --week 3
#   ./run.sh --draft-only    same as: python -m src.main --draft-only
#
# Not used by CI (the GitHub Actions workflow calls `python -m src.main`
# directly on Linux, where none of this applies) -- this is dev-machine-only.

set -e
cd "$(dirname "$0")"

# WeasyPrint's native text-rendering libraries (Pango/GObject) come from Homebrew,
# not from pip -- see README.md's Setup section.
export DYLD_LIBRARY_PATH=/opt/homebrew/lib

# Only set if the bundle exists (created once via `security find-certificate`,
# see README.md) -- a fresh clone or a machine without the corporate proxy issue
# doesn't need this, and espn_api/nflreadpy fall back to the system trust store
# when it's unset.
CERT_BUNDLE="$(pwd)/.python/macos-ca-bundle.pem"
if [ -f "$CERT_BUNDLE" ]; then
  export SSL_CERT_FILE="$CERT_BUNDLE"
  export REQUESTS_CA_BUNDLE="$CERT_BUNDLE"
fi

exec .venv/bin/python -m src.main "$@"
