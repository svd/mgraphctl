#!/usr/bin/env bash
# extract-changelog.sh <version>   e.g. scripts/extract-changelog.sh 0.2.0
# Prints the CHANGELOG.md body for one version, for use as GitHub Release notes.
# Emits nothing if no heading of the form `## [<version>] — <date>` exists.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
awk -v v="$1" '
  $0 ~ "^## \\[" v "\\]" { on=1; next }
  on && /^## \[/         { exit }
  on                     { print }
' CHANGELOG.md
