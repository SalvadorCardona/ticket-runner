#!/bin/sh
# Installation de ticket-runner.
#
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh
#
# Variables d'environnement acceptées :
#   TR_REPO       dépôt source                (défaut : SalvadorCardona/ticket-runner)
#   TR_REF        branche ou tag              (défaut : main)
#   TR_SRC        dossier local à copier      (installation depuis un clone, sans réseau)
#   TR_INTERVAL   minutes entre deux tours    (défaut : 30)
#   TR_NO_SERVICE=1   n'installe pas le minuteur systemd
set -eu

TR_REPO="${TR_REPO:-SalvadorCardona/ticket-runner}"
TR_REF="${TR_REF:-main}"
TR_INTERVAL="${TR_INTERVAL:-30}"

APP_DIR="$HOME/.local/share/ticket-runner/app"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/ticket-runner"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ticket-runner"
CONFIG="$CONFIG_DIR/config.toml"
UNIT_DIR="$HOME/.config/systemd/user"

BOLD=""; DIM=""; GREEN=""; YELLOW=""; RESET=""
if [ -t 1 ]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GREEN=$(printf '\033[32m')
    YELLOW=$(printf '\033[33m'); RESET=$(printf '\033[0m')
fi

say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$1"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
die()  { printf '%serreur:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. dépendances ---------------------------------------------------------
say "Vérification des dépendances"
have python3 || die "python3 est requis"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "python3 ≥ 3.11 est requis (tomllib fait partie de la bibliothèque standard depuis cette version)"
ok "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

have git || die "git est requis"
ok "git présent"

if have claude; then
    ok "claude $(claude --version 2>/dev/null | head -1)"
else
    warn "claude absent — installez Claude Code, sinon aucun ticket ne pourra être traité"
fi

if have gh; then
    if gh auth status >/dev/null 2>&1; then
        ok "gh authentifié"
    else
        warn "gh présent mais non authentifié : gh auth login"
    fi
else
    warn "gh absent — les branches seront poussées, mais aucune pull request ouverte"
fi

# --- 2. sources -------------------------------------------------------------
mkdir -p "$APP_DIR" "$BIN_DIR" "$CONFIG_DIR"
if [ -n "${TR_SRC:-}" ]; then
    say "Copie des sources depuis $TR_SRC"
    [ -d "$TR_SRC/src/ticket_runner" ] || die "$TR_SRC ne contient pas src/ticket_runner"
    rm -rf "$APP_DIR"; mkdir -p "$APP_DIR"
    tar -C "$TR_SRC" --exclude='.git' --exclude='__pycache__' -cf - . | tar -C "$APP_DIR" -xf -
else
    say "Téléchargement de $TR_REPO ($TR_REF)"
    have curl || die "curl est requis"
    have tar  || die "tar est requis"
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT INT TERM
    curl -fsSL "https://codeload.github.com/$TR_REPO/tar.gz/refs/heads/$TR_REF" -o "$TMP/src.tar.gz" \
        || die "téléchargement impossible (dépôt privé ou branche inexistante ?)"
    rm -rf "$APP_DIR"; mkdir -p "$APP_DIR"
    tar -xzf "$TMP/src.tar.gz" -C "$APP_DIR" --strip-components=1
fi
ok "sources dans $APP_DIR"

# --- 3. exécutable ----------------------------------------------------------
PYTHON="$(command -v python3)"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$APP_DIR/bin/ticket-runner.in" > "$BIN"
chmod +x "$BIN"
ok "commande installée : $BIN"

# --- 4. configuration -------------------------------------------------------
if [ -f "$CONFIG" ]; then
    ok "configuration existante conservée : $CONFIG"
else
    cp "$APP_DIR/config.example.toml" "$CONFIG"
    chmod 600 "$CONFIG"
    ok "configuration créée : $CONFIG"

    # Le jeton et la base sont les deux seules choses que le script ne peut pas
    # deviner — autant les demander tant qu'un terminal est là pour répondre.
    if (exec 3</dev/tty) 2>/dev/null; then
        printf '\n    %sJeton d'"'"'intégration Notion%s (https://www.notion.so/my-integrations)\n' "$BOLD" "$RESET"
        printf '    %s(entrée pour remplir plus tard)%s > ' "$DIM" "$RESET"
        read -r token </dev/tty || token=""
        if [ -n "$token" ]; then
            python3 - "$CONFIG" "$token" <<'PY'
import sys, pathlib
path, token = pathlib.Path(sys.argv[1]), sys.argv[2].strip()
text = path.read_text()
path.write_text(text.replace('token = "ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"', f'token = "{token}"'))
PY
            ok "jeton enregistré"
        fi
        printf '    %sURL de la base de tickets Notion%s > ' "$BOLD" "$RESET"
        read -r database </dev/tty || database=""
        if [ -n "$database" ]; then
            python3 - "$CONFIG" "$database" <<'PY'
import sys, pathlib
path, value = pathlib.Path(sys.argv[1]), sys.argv[2].strip()
text = path.read_text()
path.write_text(text.replace('tickets_database = ""', f'tickets_database = "{value}"'))
PY
            ok "base de tickets enregistrée"
        fi
        printf '\n'
    fi
fi

# --- 5. minuteur ------------------------------------------------------------
if [ "${TR_NO_SERVICE:-0}" != "1" ] && have systemctl; then
    say "Installation du minuteur (un tour toutes les $TR_INTERVAL min)"
    mkdir -p "$UNIT_DIR"
    # Le PATH de la session est recopié dans l'unité : un service systemd n'a ni
    # ~/.local/bin ni node dans le sien, et ne trouverait donc ni claude ni npm.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ticket-runner.service.in" > "$UNIT_DIR/ticket-runner.service"
    sed -e "s|@INTERVAL@|$TR_INTERVAL|g" \
        "$APP_DIR/systemd/ticket-runner.timer.in" > "$UNIT_DIR/ticket-runner.timer"
    systemctl --user daemon-reload
    systemctl --user enable --now ticket-runner.timer >/dev/null 2>&1 \
        && ok "ticket-runner.timer activé" \
        || warn "minuteur à activer à la main : systemctl --user enable --now ticket-runner.timer"
    # Sans linger, le minuteur s'arrête à la fermeture de session.
    if have loginctl && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
        warn "pour qu'il tourne session fermée : sudo loginctl enable-linger $USER"
    fi
else
    warn "minuteur non installé — lancez les tours à la main avec « ticket-runner run »"
fi

# --- 6. résumé --------------------------------------------------------------
printf '\n%sinstallation terminée.%s\n\n' "$BOLD" "$RESET"
printf '  Vérifiez que tout est en place :\n\n    %sticket-runner doctor%s\n\n' "$BOLD" "$RESET"
printf '  %sconfiguration%s  %s\n' "$DIM" "$RESET" "$CONFIG"
printf '  %stickets prêts%s  ticket-runner list\n' "$DIM" "$RESET"
printf '  %sun tour%s        ticket-runner run\n' "$DIM" "$RESET"
printf '  %ssuivi%s          ticket-runner logs -f\n\n' "$DIM" "$RESET"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) printf '  %s!%s ajoutez %s à votre PATH : echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.bashrc\n\n' "$YELLOW" "$RESET" "$BIN_DIR" ;;
esac
