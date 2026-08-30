#!/bin/sh
# Uninstall ticket-runner.
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/uninstall.sh | sh
# Add TR_PURGE=1 to remove the configuration, logs and history as well.
set -eu

say() { printf '==> %s\n' "$1"; }

if command -v systemctl >/dev/null 2>&1; then
    say "Stopping the timer and the console"
    systemctl --user disable --now ticket-runner.timer >/dev/null 2>&1 || true
    systemctl --user disable --now ticket-runner-web.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/ticket-runner.timer" \
          "$HOME/.config/systemd/user/ticket-runner.service" \
          "$HOME/.config/systemd/user/ticket-runner-web.service"
    systemctl --user daemon-reload || true
fi

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ticket-runner"
if [ -d "$STATE/worktrees" ] && [ -n "$(ls -A "$STATE/worktrees" 2>/dev/null)" ]; then
    say "Worktrees left in $STATE/worktrees"
    printf '    they still belong to their repositories: run "ticket-runner clean --force"\n'
    printf '    before uninstalling, or "git worktree prune" in each repository.\n'
fi

say "Removing files"
rm -f "$HOME/.local/bin/ticket-runner"
rm -rf "$HOME/.local/share/ticket-runner"

if [ "${TR_PURGE:-0}" = "1" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/ticket-runner" "$STATE"
    say "Configuration, logs and history removed"
else
    say "Configuration and history kept (TR_PURGE=1 to remove them)"
fi

printf '\nticket-runner is uninstalled.\n'
printf 'Branches already pushed are left untouched.\n'
