#!/usr/bin/env bash
# Copy working data from ~/apply-backup into this checkout.
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
src="${APPLY_BACKUP:-$HOME/apply-backup}"

if [[ ! -d "$src/applications" ]]; then
  echo "restore.sh: missing $src/applications (run backup.sh first)" >&2
  exit 1
fi

mkdir -p "$root/applications"
rsync -a --delete "$src/applications/" "$root/applications/"
echo "restored applications/ <- $src/applications/"

if [[ -d "$src/data" ]]; then
  mkdir -p "$root/data"
  rsync -a --delete "$src/data/" "$root/data/"
  echo "restored data/ <- $src/data/"
else
  echo "skipped data/ (not present in backup)"
fi
