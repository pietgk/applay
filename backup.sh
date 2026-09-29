#!/usr/bin/env bash
# Copy working data from this checkout into ~/apply-backup.
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
dest="${APPLY_BACKUP:-$HOME/apply-backup}"

mkdir -p "$dest"

if [[ ! -d "$root/applications" ]]; then
  echo "backup.sh: missing $root/applications" >&2
  exit 1
fi

rsync -a --delete "$root/applications/" "$dest/applications/"
echo "backed up applications/ -> $dest/applications/"

if [[ -d "$root/data" ]]; then
  rsync -a --delete "$root/data/" "$dest/data/"
  echo "backed up data/ -> $dest/data/"
else
  echo "skipped data/ (not present in this checkout)"
fi
