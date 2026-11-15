#!/bin/bash
# Publishes the current add-on version so every installed copy can update.
#
#   1. Raise `version` in technical_drawings/blender_manifest.toml
#   2. Commit the change
#   3. Run: tools/release.sh
#
# It builds the extension zip, generates the Blender repository index and
# pushes both to the gh-pages branch (served by GitHub Pages).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
command -v "$BLENDER" >/dev/null 2>&1 || BLENDER="$(command -v blender)"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/technical_drawings/blender_manifest.toml")"
SITE="$(mktemp -d)"
trap 'git -C "$ROOT" worktree remove --force "$SITE" >/dev/null 2>&1 || true; rm -rf "$SITE"' EXIT

cd "$ROOT"
git fetch origin gh-pages >/dev/null 2>&1 || true
if git show-ref --verify --quiet refs/remotes/origin/gh-pages; then
    git worktree add --force -B gh-pages "$SITE" origin/gh-pages >/dev/null
else
    git worktree add --force --detach "$SITE" >/dev/null
    git -C "$SITE" checkout --orphan gh-pages >/dev/null 2>&1
    git -C "$SITE" rm -rf . >/dev/null 2>&1 || true
fi

rm -f "$SITE"/*.zip "$SITE"/index.json "$SITE"/index.html
"$BLENDER" --factory-startup --command extension build \
    --source-dir "$ROOT/technical_drawings" --output-dir "$SITE"
"$BLENDER" --factory-startup --command extension server-generate --repo-dir "$SITE" --html
touch "$SITE/.nojekyll"

git -C "$SITE" add -A
git -C "$SITE" commit -m "Release $VERSION" >/dev/null
git -C "$SITE" push origin gh-pages
git -C "$ROOT" tag -f "v$VERSION" >/dev/null
git -C "$ROOT" push -f origin "v$VERSION" >/dev/null 2>&1 || true
echo "Released $VERSION"
