#!/usr/bin/env bash
# =============================================================================
# update.sh - update WSPR Logger from GitHub, restart the service, check it
#
#   bash update.sh              show what is new, ask, update, restart, verify
#   bash update.sh -y           the same without asking
#   bash update.sh --rollback   go back to the version that ran before the last update
#
# Put this file in the wspr_logger folder (next to wspr_logger.py) and run it
# from anywhere:   bash ~/wspr_logger/update.sh
#
# Safe by design
#   * only fast-forwards (git merge --ff-only); never resets, stashes or discards
#   * local files stay as they are: config.ini edits, api_keys.py, the databases
#   * if GitHub changed a file that is also modified here, it stops and tells you
#   * new .py files and templates are syntax-checked BEFORE anything is changed
#   * both SQLite databases are copied to <folder>_backups/ before every update
#
# Environment overrides:   SERVICE=wspr-logger   VERIFY_SECONDS=40
# =============================================================================

set -uo pipefail

say()   { printf '%s\n' "$*"; }
warn()  { printf 'WARNING: %s\n' "$*" >&2; }
die()   { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
short() { git rev-parse --short "$1"; }

usage() {
  cat <<'EOF'
Usage: bash update.sh [-y|--yes] [--rollback] [-h|--help]
  (no option)   show what is new on GitHub, ask, update, restart, verify
  -y, --yes     do not ask for confirmation
  --rollback    return to the version that was running before the last update
  -h, --help    this text
EOF
}

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  local ans
  read -r -p "$1 [y/N] " ans || { echo; return 1; }
  case "$ans" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

# --- settings from config.ini (port, host, database paths) --------------------
read_config() {
  local out
  out=$("$PY" - <<'PY'
import configparser
c = configparser.ConfigParser()
c.read("config.ini")
def g(sec, key, default):
    try:
        return c.get(sec, key)
    except Exception:
        return default
print(g("server", "host", "127.0.0.1"))
print(g("server", "port", "5008"))
print(g("database", "path", "wspr_data.db"))
print(g("replay", "path", "wspr_replay.db"))
PY
  ) || die "could not read config.ini"
  { read -r CFG_HOST; read -r CFG_PORT; read -r CFG_DB; read -r CFG_RDB; } <<< "$out"
  CFG_PORT="${CFG_PORT%%[!0-9]*}"; : "${CFG_PORT:=5008}"
  case "$CFG_HOST" in ""|0.0.0.0) CFG_HOST=127.0.0.1 ;; esac
  case "$CFG_DB"  in /*) ;; *) CFG_DB="$APP_DIR/$CFG_DB" ;; esac
  case "$CFG_RDB" in /*) ;; *) CFG_RDB="$APP_DIR/$CFG_RDB" ;; esac
}

warn_environment() {
  [ -f api_keys.py ] || warn "api_keys.py is missing - map tiles will show the CARTO watermark (copy api_keys.py.example to api_keys.py and add the key)"
}

show_service_state() {
  if systemctl is-active --quiet "$SERVICE"; then
    say "Service : $SERVICE is running"
  else
    warn "service $SERVICE is NOT running (sudo systemctl start $SERVICE)"
  fi
}

show_logs() { journalctl -u "$SERVICE" -n "${1:-25}" --no-pager 2>/dev/null | sed 's/^/    /'; }

# --- database copy (SQLite online backup, safe while the service is running) --
backup_databases() {
  BACKUP_DIR="$BACKUP_ROOT/pre_update_$(date +%Y%m%d_%H%M%S)"
  mkdir -p "$BACKUP_DIR" || die "cannot create $BACKUP_DIR"
  local db n=0
  for db in "$CFG_DB" "$CFG_RDB"; do
    [ -s "$db" ] || continue
    "$PY" - "$db" "$BACKUP_DIR/$(basename "$db")" <<'PY' || die "database backup failed ($db) - update cancelled, nothing was changed"
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=30)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close()
src.close()
PY
    n=$((n + 1))
  done
  if [ "$n" -eq 0 ]; then
    rmdir "$BACKUP_DIR" 2>/dev/null
    BACKUP_DIR=""
    say "Backup  : no database files found, nothing to copy"
  else
    say "Backup  : $BACKUP_DIR ($n file(s))"
    # keep the 7 newest backup folders
    # shellcheck disable=SC2012
    ls -1dt "$BACKUP_ROOT"/pre_update_* 2>/dev/null | tail -n +8 | while read -r old; do rm -rf -- "$old"; done
  fi
}

# --- syntax-check the incoming files straight from git, before touching anything
preflight() {
  local f out bad=0
  CHECKED=0
  while IFS= read -r f; do
    case "$f" in
      *.py)
        CHECKED=$((CHECKED + 1))
        out=$(git show "$UPSTREAM:$f" | "$PY" -c 'import ast, sys; ast.parse(sys.stdin.read(), sys.argv[1])' "$f" 2>&1) \
          || { printf '  FAIL  %s\n        %s\n' "$f" "$(printf '%s' "$out" | tail -n 1)"; bad=1; } ;;
      templates/*.html)
        CHECKED=$((CHECKED + 1))
        out=$(git show "$UPSTREAM:$f" | "$PY" -c 'import sys; from jinja2 import Environment; Environment().parse(sys.stdin.read())' 2>&1) \
          || { printf '  FAIL  %s\n        %s\n' "$f" "$(printf '%s' "$out" | tail -n 1)"; bad=1; } ;;
    esac
  done < <(git diff --name-only --no-renames --diff-filter=AM "$OLD" "$NEW")
  return "$bad"
}

# --- files GitHub wants to change that are also modified (or untracked) here ---
find_conflicts() {
  local up loc
  up=$(printf '%s\n' "$CHANGED" | LC_ALL=C sort -u)
  loc=$(git status --porcelain | cut -c4- | LC_ALL=C sort -u)
  LC_ALL=C comm -12 <(printf '%s\n' "$up") <(printf '%s\n' "$loc")
}

explain_conflicts() {
  say
  say "Cannot update: GitHub changes file(s) that are also modified on this machine:"
  printf '%s\n' "$1" | sed 's/^/    /'
  if printf '%s\n' "$1" | grep -q '\.db$'; then
    cat <<'EOF'

One of them is a DATABASE file that is tracked by git. It holds your live data -
never run "git checkout" on it. Nothing was changed. To get past this: stop the
service, move the database aside TOGETHER WITH its -wal and -shm files (for
example: mkdir ../keep && mv wspr_data.db* ../keep/), restore the placeholder
with "git checkout -- <file>", run update.sh, stop the service again and move
the database files back.
EOF
  else
    cat <<'EOF'

Updating would overwrite your local edits, so nothing was changed. To keep them:
copy the file(s) aside, run "git checkout -- <file>", run update.sh again, then
re-apply your edits (on this server config.ini needs:  host = 127.0.0.1).
EOF
  fi
}

# --- a hand-copied update.sh that GitHub is about to provide: make room for it --
adoptable_update_sh() {
  [ -f update.sh ] || return 1
  git ls-files --error-unmatch update.sh >/dev/null 2>&1 && return 1
  git cat-file -e "$NEW:update.sh" 2>/dev/null
}

adopt_update_sh_if_needed() {
  [ "$ADOPT_UPDATE_SH" = 1 ] || return 0
  if git show "$NEW:update.sh" | cmp -s - update.sh; then
    rm -f update.sh
  else
    mv -f update.sh update.sh.bak
    say "Note    : your own update.sh was replaced by the one from GitHub (old copy: update.sh.bak)"
  fi
}

# --- restart the service and wait until the web page answers -------------------
restart_and_verify() {
  say "Restarting $SERVICE"
  sudo systemctl restart "$SERVICE" || { warn "systemctl restart failed"; return 1; }
  local code url="http://$CFG_HOST:$CFG_PORT/"
  for _ in $(seq 1 "$VERIFY_SECONDS"); do
    if systemctl is-active --quiet "$SERVICE"; then
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" || true)
      if [ "$code" = 200 ]; then
        say "  $SERVICE is running and $url answers (HTTP 200)"
        show_logs 8
        return 0
      fi
    fi
    sleep 1
  done
  warn "$SERVICE did not answer on $url within ${VERIFY_SECONDS}s"
  return 1
}

do_rollback() {
  local prev cur keep
  [ -f "$BACKUP_ROOT/previous_commit" ] || die "no earlier version recorded - there is nothing to roll back to"
  prev=$(cat "$BACKUP_ROOT/previous_commit")
  git cat-file -e "${prev}^{commit}" 2>/dev/null || die "the recorded version ($prev) no longer exists in this checkout"
  cur=$(git rev-parse HEAD)
  if [ "$prev" = "$cur" ]; then
    say "Already on the previous version ($(short "$cur"))."
    return 0
  fi
  git merge-base --is-ancestor "$prev" "$cur" || die "$(short "$prev") is not an ancestor of the running version - refusing to roll back"
  say "Running : $(git log -1 --date=iso --format='%h %ad  %s' "$cur")"
  say "Back to : $(git log -1 --date=iso --format='%h %ad  %s' "$prev")"
  confirm "Roll back to $(short "$prev")?" || { say "Cancelled - nothing was changed."; return 0; }
  # an older version may not contain update.sh: keep a copy so it can still be run
  keep=$(mktemp) || die "cannot create a temporary file"
  cp -- "$SELF" "$keep"
  if ! git reset --keep --quiet "$prev"; then
    rm -f "$keep"
    die "git could not roll back without touching your local changes. Nothing was changed."
  fi
  if [ ! -e "$SELF" ]; then
    cp -- "$keep" "$SELF"
    say "Note    : update.sh is not part of the older version - your copy was put back"
  fi
  rm -f "$keep"
  if restart_and_verify; then
    say
    say "Rolled back to $(git log -1 --date=iso --format='%h %ad  %s' HEAD) - OK"
    say "  Run  bash update.sh  to move forward to GitHub's version again."
    return 0
  fi
  show_logs 25
  return 1
}

do_update() {
  say "Checking GitHub ..."
  timeout 60 git fetch --quiet origin || die "cannot reach GitHub (git fetch failed)"

  local branch ahead behind conflicts
  branch=$(git rev-parse --abbrev-ref HEAD)
  [ "$branch" != HEAD ] || die "this checkout is on a detached HEAD - run: git checkout main"
  UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || UPSTREAM="origin/$branch"
  git rev-parse --verify --quiet "$UPSTREAM^{commit}" >/dev/null || die "cannot find $UPSTREAM"

  OLD=$(git rev-parse HEAD)
  NEW=$(git rev-parse "$UPSTREAM")
  ahead=$(git rev-list --count "$UPSTREAM..HEAD")
  behind=$(git rev-list --count "HEAD..$UPSTREAM")

  say "Running : $(git log -1 --date=iso --format='%h %ad  %s' HEAD)"
  warn_environment

  if [ "$behind" -eq 0 ]; then
    if [ "$ahead" -gt 0 ]; then
      say "GitHub  : nothing new ($ahead local commit(s) are not on GitHub)"
    else
      say "GitHub  : already up to date"
    fi
    show_service_state
    return 0
  fi
  [ "$ahead" -eq 0 ] || die "diverged: this checkout has $ahead commit(s) that are not on GitHub and GitHub has $behind new one(s). Nothing was changed. See: git log --oneline $UPSTREAM..HEAD"

  CHANGED=$(git diff --name-only --no-renames "$OLD" "$NEW")

  say "GitHub  : $behind new commit(s):"
  git log --reverse --date=iso -n 15 --format='          %h %ad  %s' "HEAD..$UPSTREAM"
  [ "$behind" -le 15 ] || say "          ... and $((behind - 15)) older commit(s) not listed"
  say "Changes :$(git diff --shortstat "$OLD" "$NEW")"
  git diff --name-status --no-renames "$OLD" "$NEW" | head -n 20 | awk '{printf "          %s  %s\n", $1, $2}'
  [ "$(printf '%s\n' "$CHANGED" | wc -l)" -le 20 ] || say "          ... more files not listed"

  # GitHub must not overwrite local edits (config.ini host, live database, ...)
  ADOPT_UPDATE_SH=0
  conflicts=$(find_conflicts)
  if [ -n "$conflicts" ] && adoptable_update_sh; then
    ADOPT_UPDATE_SH=1
    conflicts=$(printf '%s\n' "$conflicts" | grep -vx 'update.sh' || true)
  fi
  if [ -n "$conflicts" ]; then
    explain_conflicts "$conflicts"
    return 1
  fi

  if preflight; then
    if [ "$CHECKED" -eq 0 ]; then
      say "Checks  : no Python files or templates changed"
    else
      say "Checks  : $CHECKED changed Python file(s)/template(s) pass the syntax check"
    fi
  else
    die "the version on GitHub failed the checks above - nothing was changed, the service keeps running the old version"
  fi
  if printf '%s\n' "$CHANGED" | grep -qx 'requirements.txt'; then
    say "Note    : requirements.txt changed - packages will be installed"
  fi

  say
  confirm "Update to $(short "$NEW")?" || { say "Cancelled - nothing was changed."; return 0; }

  mkdir -p "$BACKUP_ROOT" || die "cannot create $BACKUP_ROOT"
  backup_databases
  adopt_update_sh_if_needed
  printf '%s\n' "$OLD" > "$BACKUP_ROOT/previous_commit"

  say "Updating $(short "$OLD") -> $(short "$NEW")"
  git merge --ff-only --quiet "$UPSTREAM" || die "git could not update the files (see above). The service was not touched."

  if printf '%s\n' "$CHANGED" | grep -qx 'requirements.txt'; then
    say "Installing packages ..."
    "$PIP" install -q -r requirements.txt || die "pip failed. The new code is already in place but the service was NOT restarted. Fix the problem, or go back with: bash update.sh --rollback"
  fi

  if restart_and_verify; then
    say
    say "Updated to $(git log -1 --date=iso --format='%h %ad  %s' HEAD) - OK"
    [ -z "$BACKUP_DIR" ] || say "  Database copy before the update: $BACKUP_DIR"
    say "  Undo: bash update.sh --rollback"
    return 0
  fi
  show_logs 25
  say
  say "The service does not look healthy after the update."
  say "  Undo: bash update.sh --rollback"
  return 1
}

main() {
  ASSUME_YES=0
  local do_rollback=0
  while [ $# -gt 0 ]; do
    case "$1" in
      -y|--yes)   ASSUME_YES=1 ;;
      --rollback) do_rollback=1 ;;
      -h|--help)  usage; return 0 ;;
      *)          usage; return 2 ;;
    esac
    shift
  done

  SELF="$(readlink -f "${BASH_SOURCE[0]}")"
  APP_DIR="$(cd "$(dirname "$SELF")" && pwd)"
  cd "$APP_DIR" || die "cannot enter $APP_DIR"
  SERVICE="${SERVICE:-wspr-logger}"
  VERIFY_SECONDS="${VERIFY_SECONDS:-40}"
  BACKUP_ROOT="${APP_DIR}_backups"
  PY="$APP_DIR/venv/bin/python"
  PIP="$APP_DIR/venv/bin/pip"
  BACKUP_DIR=""

  command -v git  >/dev/null || die "git is not installed"
  command -v curl >/dev/null || die "curl is not installed"
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$APP_DIR is not a git checkout"
  [ -z "$(git rev-parse --show-prefix)" ] || die "update.sh must be in the root folder of the repository"
  [ -x "$PY" ] || die "no virtualenv at $APP_DIR/venv  (create it: python3 -m venv venv && venv/bin/pip install -r requirements.txt)"
  read_config

  if [ "$do_rollback" = 1 ]; then
    do_rollback
  else
    do_update
  fi
}

# One line, so bash has read the whole script before anything runs: git may
# replace this very file during the update without upsetting the running copy.
main "$@"; exit $?
