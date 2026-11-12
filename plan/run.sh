#!/usr/bin/env bash
# fomo improvement plan: unattended runner (see plan/README.md).
#
#   plan/run.sh                 run the next pending group, then stop for review
#   plan/run.sh --group 3       run the pending phases of group 3
#   plan/run.sh --phase 03a     run one phase
#   plan/run.sh --until 4       run every pending phase in groups <= 4 without stopping
#   plan/run.sh --dry           print what would run and change nothing
#
# Env: FOMO_PLAN_BRANCH  FOMO_PLAN_MODEL  FOMO_PLAN_EFFORT  FOMO_PLAN_BUDGET_USD
#      FOMO_PLAN_LIMIT_WAIT  FOMO_PLAN_MAX_LIMIT_WAITS  FOMO_PLAN_MAX_FIX
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PLAN="plan"
LOGS="$PLAN/logs"
mkdir -p "$LOGS/scratch"
export PATH="$ROOT/$PLAN/bin:$PATH"   # `az` is a stub that always fails

BRANCH="${FOMO_PLAN_BRANCH:-audit/improvements}"
MODEL="${FOMO_PLAN_MODEL:-}"
EFFORT="${FOMO_PLAN_EFFORT:-}"
BUDGET="${FOMO_PLAN_BUDGET_USD:-}"
LIMIT_WAIT="${FOMO_PLAN_LIMIT_WAIT:-1800}"
MAX_LIMIT_WAITS="${FOMO_PLAN_MAX_LIMIT_WAITS:-24}"
MAX_FIX="${FOMO_PLAN_MAX_FIX:-1}"

MODE="next"; TARGET=""; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --group) MODE="group"; TARGET="${2:?--group needs a number}"; shift 2 ;;
    --phase) MODE="phase"; TARGET="${2:?--phase needs an id}"; shift 2 ;;
    --until) MODE="until"; TARGET="${2:?--until needs a number}"; shift 2 ;;
    --dry)   DRY=1; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Tools Claude may use without asking (anything else is denied: --permission-prompts none).
ALLOWED=( Read Edit Write Glob Grep
  "Bash(.venv/bin/python *)" "Bash(.venv/bin/pytest *)" "Bash(.venv/bin/ruff *)"
  "Bash(.venv/bin/mypy *)" "Bash(.venv/bin/basedpyright *)" "Bash(uv run *)"
  "Bash(git status*)" "Bash(git diff*)" "Bash(git log*)" "Bash(git show*)" "Bash(git add *)"
  "Bash(git commit *)" "Bash(git mv *)" "Bash(git rm *)" "Bash(git restore *)"
  "Bash(git rev-parse *)" "Bash(git ls-files*)" "Bash(git grep *)"
  "Bash(ls*)" "Bash(grep *)" "Bash(rg *)" "Bash(wc *)" "Bash(man *)" "Bash(mkdir *)" )
DENIED=( "Bash(az *)" "Bash(git push*)" "Bash(git reset*)" "Bash(git rebase*)"
  "Bash(git switch*)" "Bash(git checkout*)" "Bash(git tag*)" "Bash(uv add*)" "Bash(uv sync*)"
  "Bash(uv lock*)" "Bash(uv pip*)" "Bash(uv build*)" "Bash(pip*)" "Bash(curl*)" "Bash(wget*)"
  WebFetch WebSearch Agent Workflow )

log()    { printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOGS/run.log" >&2; }
notify() { if command -v notify-send >/dev/null 2>&1; then notify-send "fomo plan" "$*" || true; fi; }
die()    { log "STOP: $*"; notify "$*"; exit 1; }

decision()     { sed -n "s/^$1=\([^[:space:]#]*\).*/\1/p" "$PLAN/DECISIONS.md" | head -n1; }
is_done()      { grep -qE "^- \[x\] $1( |$)" "$PLAN/STATUS.md"; }
queue()        { grep -Ev '^[[:space:]]*(#|$)' "$PLAN/QUEUE"; }
lock_tracked() { git ls-files --error-unmatch uv.lock >/dev/null 2>&1; }
uvq()          { if lock_tracked; then UV_FROZEN=1 uv "$@"; else uv "$@"; fi; }

group_done() {
  local p
  for p in $(queue | awk -v g="$1" '$2 == g {print $1}'); do is_done "$p" || return 1; done
  return 0
}

select_phases() {
  local id group file model effort first=""
  while read -r id group file model effort; do
    is_done "$id" && continue
    case "$MODE" in
      phase) [[ "$id" == "$TARGET" ]] && echo "$id $group $file ${model:--} ${effort:--}" ;;
      group) [[ "$group" == "$TARGET" ]] && echo "$id $group $file ${model:--} ${effort:--}" ;;
      until) (( group <= TARGET )) && echo "$id $group $file ${model:--} ${effort:--}" ;;
      next)  [[ -z "$first" ]] && first="$group"
             [[ "$group" == "$first" ]] && echo "$id $group $file ${model:--} ${effort:--}" ;;
    esac
  done < <(queue)
  return 0
}

# Tracked changes anywhere, or untracked files inside project directories.
dirty() {
  git status --porcelain --untracked-files=no -- . ":(exclude)fomo/_version.py" | grep -q . && return 0
  git status --porcelain --untracked-files=all -- fomo tests scripts docs man .github plan \
    ":(exclude)$LOGS" | grep -q '^??' && return 0
  return 1
}
not_dirty() { if dirty; then git status --short; return 1; fi; }

preflight() {
  command -v claude  >/dev/null || die "claude CLI not found on PATH"
  command -v uv      >/dev/null || die "uv not found on PATH"
  command -v python3 >/dev/null || die "python3 not found on PATH"
  git ls-files --error-unmatch "$PLAN/run.sh" >/dev/null 2>&1 \
    || die "commit plan/ first (see plan/README.md, Quick start)"
  local cur; cur="$(git branch --show-current)"
  if [[ "$cur" == "main" || "$cur" == "master" ]]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then git switch -q "$BRANCH"
    else git switch -q -c "$BRANCH"; fi
    log "switched to branch $BRANCH"
  fi
  if dirty; then git status --short >&2; die "uncommitted changes; commit or stash them first"; fi
}

sync_env() {
  log "uv sync --group dev"
  uvq sync --group dev >>"$LOGS/run.log" 2>&1 || die "uv sync failed (see $LOGS/run.log)"
}

resolve_action_shas() {
  local a repo tag sha
  for a in actions/checkout@v4 astral-sh/setup-uv@v6 googleapis/release-please-action@v4 \
           actions/upload-artifact@v4 softprops/action-gh-release@v2; do
    repo="${a%@*}"; tag="${a#*@}"
    sha="$(git ls-remote --tags "https://github.com/$repo" 2>/dev/null \
      | awk -v t="refs/tags/$tag" '$2 == t"^{}" {p=$1} $2 == t {l=$1} END {print (p != "" ? p : l)}')"
    echo "$a ${sha:-UNRESOLVED}"
  done
}

# Pre-steps that need the network run here, in your shell, outside Claude's sandbox.
pre_hook() {
  local deps
  case "$1" in
    01)
      if [[ "$(decision D3_SNAPSHOT_TESTS)" == yes ]]; then
        log "uv add --dev pytest-textual-snapshot"
        uv add --dev pytest-textual-snapshot >>"$LOGS/run.log" 2>&1 || die "uv add failed"
      fi ;;
    02a)
      deps="$(decision D1_DEV_DEPS)"
      if [[ -n "$deps" && "$deps" != none ]]; then
        log "uv add --dev ${deps//,/ }"
        # shellcheck disable=SC2086
        uv add --dev ${deps//,/ } >>"$LOGS/run.log" 2>&1 || die "uv add failed"
      fi
      if [[ "$(decision D2_LOCK_AND_PIN)" == yes ]]; then
        log "uv add 'textual>=8.2,<9'"
        uv add 'textual>=8.2,<9' >>"$LOGS/run.log" 2>&1 || die "uv add failed"
      fi
      log "resolving GitHub Action SHAs -> $LOGS/action-shas.txt"
      resolve_action_shas > "$LOGS/action-shas.txt" ;;
    03b)
      if [[ "$(decision D5_TIERING)" == pin-sha ]]; then
        git ls-remote https://github.com/emiliensocchi/azure-tiering refs/heads/main \
          | cut -f1 > "$LOGS/tiering-sha.txt" || true
        log "tiering main SHA: $(cat "$LOGS/tiering-sha.txt" 2>/dev/null || echo unresolved)"
      fi ;;
  esac
  return 0
}

tick() { # mark a phase done in STATUS.md (used for runner-only phases)
  python3 - "$PLAN/STATUS.md" "$1" <<'PY'
import re, sys
path, pid = sys.argv[1], sys.argv[2]
text = open(path).read()
text = re.sub(rf"^- \[ \] {re.escape(pid)}( |$)", rf"- [x] {pid}\1", text, count=1, flags=re.M)
open(path, "w").write(text)
PY
}

# Phases done by the runner itself, without Claude. Returns 1 for normal phases.
runner_only() {
  case "$1" in
    04z)
      log "regenerating screenshots"
      uvq run python scripts/screenshot.py >>"$LOGS/run.log" 2>&1 || die "screenshot generation failed"
      tick 04z
      git add docs/screenshots "$PLAN/STATUS.md" || die "git add failed"
      git commit -q -m "docs: regenerate screenshots" \
        -m "Regenerated by plan/run.sh after the UX phases (04a-04g)." || die "git commit failed"
      return 0 ;;
  esac
  return 1
}

json_get() { # json_get FILE KEY -> value of KEY in claude's JSON result ("" if absent)
  python3 - "$1" "$2" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except Exception:
    sys.exit(0)
if isinstance(data, list):
    data = next((m for m in reversed(data) if isinstance(m, dict) and m.get("type") == "result"), {})
val = data.get(key, "") if isinstance(data, dict) else ""
print(val if isinstance(val, str) else json.dumps(val))
PY
}

run_claude() { # run_claude ID PROMPT_FILE MODEL EFFORT -> prints the JSON output path
  local id="$1" pf="$2" model="$3" effort="$4" out rc=0
  out="$LOGS/$id-$(date +%Y%m%d-%H%M%S).json"
  local args=( -p --output-format json --permission-mode acceptEdits --permission-prompts none
               -n "fomo-plan-$id" --append-system-prompt "$(cat "$PLAN/RULES.md")" )
  [[ "$model"  != - && -n "$model"  ]] || model="$MODEL"
  [[ "$effort" != - && -n "$effort" ]] || effort="$EFFORT"
  if [[ -n "$model"  ]]; then args+=( --model "$model" ); fi
  if [[ -n "$effort" ]]; then args+=( --effort "$effort" ); fi
  if [[ -n "$BUDGET" ]]; then args+=( --max-budget-usd "$BUDGET" ); fi
  args+=( --allowedTools "${ALLOWED[@]}" --disallowedTools "${DENIED[@]}" )
  log "claude: phase $id${model:+ model=$model}${effort:+ effort=$effort} -> $out"
  claude "${args[@]}" < "$pf" > "$out" 2> "${out%.json}.err" || rc=$?
  echo "$rc" > "${out%.json}.rc"
  echo "$out"
}

hit_limit() { # only consulted when the call failed
  local text
  text="$(json_get "$1" result) $(cat "${1%.json}.err" 2>/dev/null || true)"
  grep -Eiq 'usage limit|rate.?limit|limit (reached|will reset)|resets? at|overloaded|quota|\b429\b|\b529\b' <<<"$text"
}

wait_for_reset() {
  local text epoch now secs
  text="$(json_get "$1" result) $(cat "${1%.json}.err" 2>/dev/null || true)"
  epoch="$(grep -oE '\|[0-9]{10}' <<<"$text" | tr -d '|' | head -n1 || true)"
  now="$(date +%s)"
  if [[ -n "$epoch" ]] && (( epoch > now )); then secs=$(( epoch - now + 60 )); else secs="$LIMIT_WAIT"; fi
  log "usage/rate limit; sleeping ${secs}s, resuming at $(date -d "@$(( now + secs ))" '+%F %T' 2>/dev/null || echo "+${secs}s")"
  notify "limit hit; resuming in $(( secs / 60 )) min"
  sleep "$secs"
}

claude_until_done() { # claude_until_done ID PROMPT_FILE MODEL EFFORT -> sets LAST_LINE
  local waits=0 out rc err
  while :; do
    out="$(run_claude "$@")"
    rc="$(cat "${out%.json}.rc")"
    err="$(json_get "$out" is_error)"
    if [[ "$rc" != 0 || "$err" == true ]] && hit_limit "$out"; then
      waits=$(( waits + 1 ))
      (( waits <= MAX_LIMIT_WAITS )) || die "still limited after $MAX_LIMIT_WAITS waits"
      wait_for_reset "$out"
      continue
    fi
    break
  done
  LAST_LINE="$(json_get "$out" result | grep -E "^PHASE $1: (DONE|BLOCKED)" | tail -n1 || true)"
  log "phase $1 -> ${LAST_LINE:-no status line} (rc=$rc, cost=$(json_get "$out" total_cost_usd) USD)"
}

phase_prompt() { # phase_prompt ID BRIEF
  cat <<EOF
Unattended run of phase $1 of the fomo improvement plan. Nobody will answer questions.

1. Read plan/RULES.md (also in your system prompt), plan/DECISIONS.md and plan/$2.
   Read only the parts of plan/REPORT.md that the brief cites.
2. Run \`git status\` and \`git log --oneline -25\`. An earlier attempt at this phase may have
   stopped part-way: keep its committed work and continue from where it stopped.
3. Do every step in the brief, in order, and verify as the brief says.
4. Commit using the Conventional Commit messages in the brief. Tick "- [x] $1" in
   plan/STATUS.md in your last commit, and leave the tree clean.
5. If a step is impossible, or needs a decision plan/DECISIONS.md doesn't make, don't guess:
   add "- $1: <reason>" under "## Blocked" in plan/STATUS.md, commit it, and stop.

The runner will then independently run pytest, lint and type checks if present, \`uv build\`, the
man-page check and the contract-test freeze check.

Finish with exactly one line: "PHASE $1: DONE" or "PHASE $1: BLOCKED — <reason>".
EOF
}

fix_prompt() { # fix_prompt ID BRIEF
  cat <<EOF
Unattended fix-up for phase $1 of the fomo improvement plan. Nobody will answer questions.

The runner's independent verification failed after this phase. Tail of its log:
----
$(tail -n 150 "$LOGS/gate-$1.log")
----
Re-read plan/RULES.md and plan/$2. Fix the cause. Don't weaken, skip or delete tests, and don't
edit tests/test_cli_contract.py unless the brief explicitly allows it (only phases 01, 06a, 06b).
If the failure is "no uncommitted changes", commit or remove the leftover files (scratch files
belong in plan/logs/scratch/). Commit with a Conventional Commit message, make sure "- [x] $1"
is ticked in plan/STATUS.md, and leave the tree clean.

Finish with exactly one line: "PHASE $1: DONE" or "PHASE $1: BLOCKED — <reason>".
EOF
}

gate() { # gate ID -> 0 when every check passes; details in $LOGS/gate-ID.log
  local id="$1" gl="$LOGS/gate-$1.log" whl
  : > "$gl"
  check() {
    local name="$1"; shift
    printf '== %s\n' "$name" >>"$gl"
    if "$@" >>"$gl" 2>&1; then return 0; fi
    printf 'FAILED: %s\n' "$name" >>"$gl"; return 1
  }
  check "pytest" uvq run pytest -q || return 1
  if is_done 02a && uvq run ruff --version >/dev/null 2>&1; then
    check "ruff check" uvq run ruff check . || return 1
    check "ruff format --check" uvq run ruff format --check . || return 1
  fi
  if is_done 02a && uvq run mypy --version >/dev/null 2>&1; then
    check "mypy" uvq run mypy fomo || return 1
  fi
  if is_done 02a && uvq run basedpyright --version >/dev/null 2>&1; then
    check "basedpyright" uvq run basedpyright fomo || return 1
  fi
  check "uv build" uv build || return 1
  whl="$(ls -t dist/*.whl | head -n1)"
  check "man page in wheel" sh -c "unzip -l '$whl' | grep -q 'share/man/man1/fomo.1'" || return 1
  if is_done 02d && command -v man >/dev/null 2>&1; then
    check "man EXAMPLES render in full" \
      sh -c "MANWIDTH=140 man -l man/fomo.1 | grep -q 'Break-glass access'" || return 1
  fi
  check "no uncommitted changes" not_dirty || return 1
  check "phase ticked in STATUS.md" is_done "$id" || return 1
  if [[ "$id" != 01 && "$id" != 06* ]] && git rev-parse -q --verify refs/tags/plan-01-done >/dev/null; then
    check "tests/test_cli_contract.py unchanged since plan-01-done" \
      git diff --quiet plan-01-done -- tests/test_cli_contract.py || return 1
  fi
  return 0
}

run_phase() { # run_phase ID GROUP BRIEF MODEL EFFORT
  local id="$1" group="$2" file="$3" model="$4" effort="$5" n
  log "=== phase $id (group $group): $PLAN/$file"
  sync_env
  if runner_only "$id"; then
    gate "$id" || die "verification failed after $id (see $LOGS/gate-$id.log)"
    log "phase $id passed verification"; return 0
  fi
  [[ -f "$PLAN/$file" ]] || die "missing brief $PLAN/$file"
  pre_hook "$id"
  phase_prompt "$id" "$file" > "$LOGS/prompt-$id.txt"
  claude_until_done "$id" "$LOGS/prompt-$id.txt" "$model" "$effort"
  if [[ "$LAST_LINE" == *BLOCKED* ]]; then die "$LAST_LINE (see plan/STATUS.md)"; fi
  for (( n = 0; ; n++ )); do
    if gate "$id"; then break; fi
    (( n < MAX_FIX )) || die "verification failed for $id (see $LOGS/gate-$id.log)"
    log "verification failed for $id; fix-up run $(( n + 1 ))/$MAX_FIX"
    fix_prompt "$id" "$file" > "$LOGS/prompt-$id-fix$n.txt"
    claude_until_done "$id" "$LOGS/prompt-$id-fix$n.txt" "$model" "$effort"
    if [[ "$LAST_LINE" == *BLOCKED* ]]; then die "$LAST_LINE (see plan/STATUS.md)"; fi
  done
  if [[ "$id" == 01 ]]; then git tag -f plan-01-done >/dev/null; fi
  log "phase $id passed verification"
}

main() {
  local phases=() line id group file model effort start
  mapfile -t phases < <(select_phases)
  if (( ${#phases[@]} == 0 )); then log "nothing to run (mode=$MODE${TARGET:+ $TARGET})"; exit 0; fi
  if (( DRY )); then printf 'would run: %s\n' "${phases[@]}"; exit 0; fi
  preflight
  start="$(git rev-parse HEAD)"
  for line in "${phases[@]}"; do
    read -r id group file model effort <<<"$line"
    run_phase "$id" "$group" "$file" "$model" "$effort"
    if group_done "$group"; then
      git tag -f "plan-group-$group-done" >/dev/null
      log "group $group complete (tag plan-group-$group-done)"
    fi
  done
  log "finished: $(printf '%s ' "${phases[@]%% *}")"
  git log --oneline "$start..HEAD" | tee -a "$LOGS/run.log" >&2
  log "review with: git log -p $start..HEAD   then run plan/run.sh again for the next group"
  notify "finished: $(printf '%s ' "${phases[@]%% *}")"
}

main
