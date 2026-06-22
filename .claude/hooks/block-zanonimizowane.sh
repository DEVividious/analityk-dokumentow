#!/usr/bin/env bash
# Blokuje ODCZYT TREŚCI plików mapowań (.json) w docs/zanonimizowane/.
# Te pliki zawierają oryginalne dane osobowe (placeholder → oryginał), więc asystent
# nie może ich czytać. Dozwolone: listowanie nazw (ls/find) oraz odczyt zanonimizowanych .md.
#
# PreToolUse hook: czyta JSON ze stdin, zwraca decyzję "deny" gdy wykryje próbę odczytu.

input=$(cat)
tool=$(printf '%s' "$input" | jq -r '.tool_name // empty')
reason='Odczyt plików mapowań (.json) w docs/zanonimizowane/ jest zablokowany regułą bezpieczeństwa — zawierają oryginalne dane osobowe.'

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$reason"
  exit 0
}

case "$tool" in
  Read|Grep)
    target=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')
    printf '%s' "$target" | grep -Eq 'docs/zanonimizowane/.*\.json$' && deny
    ;;
  Bash)
    cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
    if printf '%s' "$cmd" | grep -Eq 'docs/zanonimizowane/[^[:space:]]*\.json' \
       && printf '%s' "$cmd" | grep -Eiq '(^|[|&;( ])(cat|head|tail|less|more|bat|grep|egrep|fgrep|rg|ag|sed|awk|nl|tac|xxd|od|hexdump|strings|cut|paste|jq|yq|python3?|node|ruby|perl|vi|vim|view|nano|emacs|open|cp|mv|rsync|scp|dd|tee)([[:space:]]|$)'; then
      deny
    fi
    ;;
esac

exit 0
