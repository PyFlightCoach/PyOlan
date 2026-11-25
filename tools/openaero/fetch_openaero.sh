#!/usr/bin/env bash
# Fetch the pinned OpenAero commit from upstream into an ignored directory.
#
#   tools/openaero/fetch_openaero.sh [sha]
#
# The sha defaults to tools/openaero/OPENAERO_SHA. The tree is written to
# $OPENAERO_DIR, or to .test-artifacts/openaero/<sha> under the PyOlan package.
# Nothing here depends on a local OpenAero checkout. Prints the directory.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package="$(cd "$here/../.." && pwd)"
sha="${1:-$(tr -d '[:space:]' < "$here/OPENAERO_SHA")}"
repo="${OPENAERO_REPO:-https://github.com/OpenAero/main}"
dest="${OPENAERO_DIR:-$package/.test-artifacts/openaero/$sha}"

if [ -f "$dest/.openaero-sha" ] && [ "$(cat "$dest/.openaero-sha")" = "$sha" ]; then
    echo "$dest"
    exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git -C "$work" init -q
git -C "$work" fetch -q --depth 1 "$repo" "$sha"
mkdir -p "$dest"
git -C "$work" archive FETCH_HEAD | tar -x -C "$dest"
echo "$sha" > "$dest/.openaero-sha"
echo "$dest"
