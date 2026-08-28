#!/bin/sh
# Désinstallation de ticket-runner.
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/uninstall.sh | sh
# Ajoutez TR_PURGE=1 pour supprimer aussi la configuration, les journaux et l'historique.
set -eu

say() { printf '==> %s\n' "$1"; }

if command -v systemctl >/dev/null 2>&1; then
    say "Arrêt du minuteur"
    systemctl --user disable --now ticket-runner.timer >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/ticket-runner.timer" \
          "$HOME/.config/systemd/user/ticket-runner.service"
    systemctl --user daemon-reload || true
fi

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ticket-runner"
if [ -d "$STATE/worktrees" ] && [ -n "$(ls -A "$STATE/worktrees" 2>/dev/null)" ]; then
    say "Worktrees restants dans $STATE/worktrees"
    printf '    ils appartiennent encore à leurs dépôts : « ticket-runner clean --force »\n'
    printf '    avant de désinstaller, sinon « git worktree prune » dans chaque dépôt.\n'
fi

say "Suppression des fichiers"
rm -f "$HOME/.local/bin/ticket-runner"
rm -rf "$HOME/.local/share/ticket-runner"

if [ "${TR_PURGE:-0}" = "1" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/ticket-runner" "$STATE"
    say "Configuration, journaux et historique supprimés"
else
    say "Configuration et historique conservés (TR_PURGE=1 pour les supprimer)"
fi

printf '\nticket-runner est désinstallé.\n'
printf 'Les branches ticket/* déjà poussées ne sont pas touchées.\n'
