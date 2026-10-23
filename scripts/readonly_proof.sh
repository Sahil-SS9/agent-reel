#!/usr/bin/env bash
# Prove the Hermes history adapter never needs write access to Hermes state.
#
# Three independent checks:
#
#   A. Live run under strace: every data file in the Hermes home is opened
#      O_RDONLY; no file is created, renamed, truncated or deleted; no
#      rename/unlink/mkdir/truncate/chmod/link/symlink happens under the home.
#      SQLite's own -wal/-shm sidecars are reported separately: a WAL database
#      always has those opened by the library, and existing -shm wal-index pages
#      are updated by normal SQLite read locking (the sqlite3 CLI does the same).
#      Part B proves the adapter does not need write access even for those.
#
#   B. Strict run: a read-only-locked copy (0444 files, 0555 dir) of one real
#      profile store is read successfully. Every write-flag open under that copy
#      must FAIL, which is only possible if the adapter never needs to write.
#
#   C. The same strict check on the synthetic fixture home, so the result does
#      not depend on which live profile happened to be copied.
#
# Usage: scripts/readonly_proof.sh [evidence-dir]
# Exit: 0 = all checks pass, 1 = a check failed, 2 = the run itself failed.

set -uo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT" || exit 2

HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"
EVIDENCE="${1:-$HOME/handoffs/agent-story-replay/build-evidence/M0}"
DAYS="${DAYS:-7}"
# The scratch tree must live OUTSIDE the Hermes home, or this script's own
# temporary files would show up as "created under the home".
SCRATCH="${SCRATCH:-$EVIDENCE/.proof-scratch}"
PYTHON="$REPO_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "no venv python at $PYTHON" >&2
  exit 2
fi

rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/tmp" "$EVIDENCE" || exit 2
# TMPDIR is redirected out of the Hermes home so Python's own scratch files
# cannot be mistaken for a write into Hermes state.
export TMPDIR="$SCRATCH/tmp"

TRACE="$EVIDENCE/strace-openat.log"
SUMMARY="$EVIDENCE/readonly-proof-summary.txt"
VERDICT="$EVIDENCE/readonly-proof-verdict.txt"
SYSCALLS="openat,open,rename,renameat,renameat2,unlink,unlinkat,mkdir,mkdirat,rmdir,truncate,ftruncate,chmod,fchmod,symlink,link"

WRITE_FLAGS='O_WRONLY|O_RDWR|O_CREAT|O_TRUNC|O_APPEND'
SIDECARS='\-(wal|shm)"'
MUTATING='rename|renameat|unlink|mkdir|rmdir|truncate|ftruncate|chmod|fchmod|symlink|link\('

fail=0
: >"$VERDICT"
report() { printf '%s\n' "$*" >>"$VERDICT"; }

report "read-only proof: Hermes Scrollback Reel history adapter"
report "date:           $(date -Is)"
report "hermes home:    $HERMES_ROOT"
report "window:         last $DAYS days"
report "python:         $($PYTHON --version 2>&1)"
report ""

# --------------------------------------------------------------------------- #
# A. live run
# --------------------------------------------------------------------------- #
# Sidecar files that already exist before the run: an O_CREAT open on one of
# these creates nothing.
find "$HERMES_ROOT" -maxdepth 4 -type f \( -name '*-wal' -o -name '*-shm' \) 2>/dev/null \
  | sort >"$SCRATCH/sidecars-before.txt"
strace -f -q -e trace="$SYSCALLS" -o "$TRACE" \
  "$PYTHON" -m adapters.hermes.history --days "$DAYS" --summary \
  >"$SUMMARY" 2>&1
A_STATUS=$?

if [[ $A_STATUS -ne 0 ]]; then
  report "A. live run FAILED (status $A_STATUS); see $SUMMARY"
  cat "$VERDICT"
  exit 2
fi

DATA_WRITE_OPENS=$(grep -E "$WRITE_FLAGS" "$TRACE" | grep -F "$HERMES_ROOT" | grep -vE "$SIDECARS" || true)
SIDECAR_OPENS=$(grep -E "$WRITE_FLAGS" "$TRACE" | grep -F "$HERMES_ROOT" | grep -E "$SIDECARS" || true)
MUTATIONS=$(grep -E "$MUTATING" "$TRACE" | grep -F "$HERMES_ROOT" || true)
DATA_READ_OPENS=$(grep -F "$HERMES_ROOT" "$TRACE" | grep -E 'O_RDONLY' | grep -vcE "$SIDECARS" || true)
# Creation is attributed from the trace, not from a directory diff: the fleet
# writes to the Hermes home continuously, so a before/after diff would blame
# unrelated cron output for files this adapter never touched.
CREATE_OPENS=$(grep -E 'O_CREAT' "$TRACE" | grep -F "$HERMES_ROOT" || true)
CREATE_NON_SIDECAR=$(printf '%s' "$CREATE_OPENS" | grep -vE "$SIDECARS" | grep -vE '= -1' || true)
NEW_SIDECARS=$(
  grep -E 'O_CREAT' "$TRACE" | grep -F "$HERMES_ROOT" | grep -E "$SIDECARS" \
    | grep -oE '"[^"]+"' | tr -d '"' | sort -u \
    | comm -13 "$SCRATCH/sidecars-before.txt" - || true
)
SIDECARS_SEEN=$(grep -E 'O_CREAT' "$TRACE" | grep -F "$HERMES_ROOT" | grep -E "$SIDECARS" | grep -c . || true)

report "A. live run over the Hermes home"
report "   data-file read opens (O_RDONLY):        ${DATA_READ_OPENS:-0}"
report "   data-file write opens (must be 0):      $(printf '%s' "$DATA_WRITE_OPENS" | grep -c . || true)"
report "   WAL/SHM sidecar opens (SQLite, see B):  $(printf '%s' "$SIDECAR_OPENS" | grep -c . || true)"
report "   mutating syscalls under the home:       $(printf '%s' "$MUTATIONS" | grep -c . || true)"
report "   sidecars that O_CREAT touched (all pre-existing): $SIDECARS_SEEN"
report "   sidecar files newly created (must be 0):          $(printf '%s' "$NEW_SIDECARS" | grep -c . || true)"
report "   non-sidecar O_CREAT opens that succeeded (0):     $(printf '%s' "$CREATE_NON_SIDECAR" | grep -c . || true)"
if [[ -n "$DATA_WRITE_OPENS" ]]; then
  report "   FAIL data-file write opens:"
  report "$DATA_WRITE_OPENS"
  fail=1
fi
if [[ -n "$MUTATIONS" ]]; then
  report "   FAIL mutating syscalls:"
  report "$MUTATIONS"
  fail=1
fi
if [[ -n "$CREATE_NON_SIDECAR" ]]; then
  report "   FAIL non-sidecar create/open-for-write succeeded:"
  report "$CREATE_NON_SIDECAR"
  fail=1
fi
if [[ -n "$NEW_SIDECARS" ]]; then
  report "   FAIL sidecar files were created:"
  report "$NEW_SIDECARS"
  fail=1
fi
if [[ "${DATA_READ_OPENS:-0}" -lt 1 ]]; then
  report "   FAIL no read opens traced (weak evidence)"
  fail=1
fi
report ""

# --------------------------------------------------------------------------- #
# B. strict run: read-only-locked copy of one real profile
# --------------------------------------------------------------------------- #
# Prefer the most recently written small profile stores: a busy profile makes
# the strict run a real read, not an empty one.
CANDIDATES="${STRICT_PROFILE:-}"
if [[ -z "$CANDIDATES" ]]; then
  CANDIDATES=$(find "$HERMES_ROOT/profiles" -mindepth 2 -maxdepth 2 -name state.db -size -200M \
      -printf '%T@ %h\n' 2>/dev/null | sort -rn | head -5 | awk '{print $2}' | xargs -r -n1 basename)
fi
STRICT_HOME="$SCRATCH/strict-home"
PROFILE=""
B_OK=0
for candidate in $CANDIDATES; do
  PROFILE="$candidate"
  rm -rf "$STRICT_HOME"
  mkdir -p "$STRICT_HOME/profiles/$PROFILE"
  cp -a "$HERMES_ROOT/profiles/$PROFILE/state.db"* "$STRICT_HOME/profiles/$PROFILE/" 2>/dev/null
  chmod -R a-w "$STRICT_HOME"
  chmod 0555 "$STRICT_HOME" "$STRICT_HOME/profiles" "$STRICT_HOME/profiles/$PROFILE"
  STRICT_TRACE="$EVIDENCE/strace-strict.log"
  STRICT_SUMMARY="$EVIDENCE/readonly-proof-strict-summary.txt"
  HERMES_HOME="$STRICT_HOME" strace -f -q -e trace="$SYSCALLS" -o "$STRICT_TRACE" \
    "$PYTHON" -m adapters.hermes.history --profile "$PROFILE" --days "$DAYS" --summary \
    >"$STRICT_SUMMARY" 2>&1
  B_STATUS=$?
  STRICT_ATTEMPTS=$(grep -E "$WRITE_FLAGS" "$STRICT_TRACE" | grep -F "$STRICT_HOME" || true)
  STRICT_SUCCEEDED=$(printf '%s' "$STRICT_ATTEMPTS" | grep -vE '= -1' | grep -c . || true)
  STRICT_EVENTS=$(grep -E '^TOTAL' "$STRICT_SUMMARY" | awk '{print $2}' | tr -d , || true)
  [[ -z "${STRICT_EVENTS:-}" ]] && STRICT_EVENTS=0
  report "B. strict run on a read-only-locked copy of live profile '$PROFILE'"
  report "   run status:                             $B_STATUS"
  report "   events read (TOTAL):                    $STRICT_EVENTS"
  report "   write-flag opens attempted (denied):    $(printf '%s' "$STRICT_ATTEMPTS" | grep -c . || true)"
  report "   write-flag opens that SUCCEEDED (0):    ${STRICT_SUCCEEDED:-0}"
  if [[ $B_STATUS -ne 0 ]]; then
    report "   FAIL strict run did not survive a read-only tree"
    fail=1
  fi
  if [[ "${STRICT_SUCCEEDED:-0}" -ne 0 ]]; then
    report "   FAIL a write-open succeeded on a read-only tree"
    fail=1
  fi
  if [[ "$STRICT_EVENTS" -gt 0 ]]; then
    B_OK=1
    break
  fi
  report "   note: this profile had no activity in the window; trying the next one"
done
if [[ $B_OK -ne 1 ]]; then
  report "   FAIL no probed profile store produced events read-only"
  fail=1
fi
report ""

# --------------------------------------------------------------------------- #
# C. strict run on the synthetic home
# --------------------------------------------------------------------------- #
SYNTH="$SCRATCH/synthetic-home"
if "$PYTHON" -m fixtures.build_synthetic_home "$SYNTH" --seed 7 --days 7 >/dev/null 2>&1; then
  chmod -R a-w "$SYNTH"
  find "$SYNTH" -type d -exec chmod 0555 {} \;
  SYNTH_TRACE="$EVIDENCE/strace-strict-synthetic.log"
  SYNTH_SUMMARY="$EVIDENCE/readonly-proof-synthetic-summary.txt"
  HERMES_HOME="$SYNTH" strace -f -q -e trace="$SYSCALLS" -o "$SYNTH_TRACE" \
    "$PYTHON" -m adapters.hermes.history --days 7 --summary \
    >"$SYNTH_SUMMARY" 2>&1
  C_STATUS=$?
  C_ATTEMPTS=$(grep -E "$WRITE_FLAGS" "$SYNTH_TRACE" | grep -F "$SYNTH" || true)
  C_SUCCEEDED=$(printf '%s' "$C_ATTEMPTS" | grep -vE '= -1' | grep -c . || true)
  C_EVENTS=$(grep -E '^TOTAL' "$SYNTH_SUMMARY" | awk '{print $2}' | tr -d , || true)
  [[ -z "${C_EVENTS:-}" ]] && C_EVENTS=0
  report "C. strict run on a read-only-locked synthetic home"
  report "   run status:                             $C_STATUS"
  report "   events read (TOTAL):                    $C_EVENTS"
  report "   write-flag opens attempted (denied):    $(printf '%s' "$C_ATTEMPTS" | grep -c . || true)"
  report "   write-flag opens that SUCCEEDED (0):    ${C_SUCCEEDED:-0}"
  if [[ $C_STATUS -ne 0 ]]; then
    report "   FAIL synthetic strict run failed"
    fail=1
  fi
  if [[ "${C_SUCCEEDED:-0}" -ne 0 ]]; then
    report "   FAIL a write-open succeeded on the synthetic read-only tree"
    fail=1
  fi
  if [[ "$C_EVENTS" -le 0 ]]; then
    report "   FAIL synthetic strict run produced no events"
    fail=1
  fi
else
  report "C. synthetic strict run SKIPPED (fixture generator failed)"
  fail=1
fi

report ""
if [[ $fail -eq 0 ]]; then
  report "VERDICT: PASS - no files created, renamed, truncated or deleted under the Hermes home"
  report "              (existing -shm wal-index pages are updated by normal SQLite read locking)"
else
  report "VERDICT: FAIL - see the FAIL lines above"
fi

cat "$VERDICT"
chmod -R u+w "$SCRATCH" 2>/dev/null
rm -rf "$SCRATCH"
exit $fail
