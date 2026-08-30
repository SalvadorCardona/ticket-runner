#!/bin/sh
# Install ticket-runner.
#
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh
#
# Environment variables:
#   TR_REPO       source repository        (default: SalvadorCardona/ticket-runner)
#   TR_REF        branch or tag            (default: main; a tag pins the version,
#                                          a branch is followed by the auto-update)
#   TR_SRC        local folder to copy     (install from a clone, no network,
#                                          and no auto-update: there is no remote)
#   TR_INTERVAL   seconds between runs     (default: 1800, i.e. 30 min)
#   TR_NO_SERVICE=1   do not install the systemd timer
set -eu

TR_REPO="${TR_REPO:-SalvadorCardona/ticket-runner}"
TR_REF="${TR_REF:-main}"
TR_INTERVAL="${TR_INTERVAL:-1800}"

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
die()  { printf '%serror:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. dependencies --------------------------------------------------------
say "Checking dependencies"
have python3 || die "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "python3 >= 3.11 is required (tomllib has been part of the standard library since then)"
ok "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

have git || die "git is required"
ok "git found"

if have claude; then
    ok "claude $(claude --version 2>/dev/null | head -1)"
else
    warn "claude missing — install Claude Code, or no ticket can ever be handled"
fi

if have gh; then
    if gh auth status >/dev/null 2>&1; then
        ok "gh authenticated"
    else
        warn "gh found but not authenticated: gh auth login"
    fi
else
    warn "gh missing — branches will be pushed, but no pull request opened"
fi

# --- 2. sources -------------------------------------------------------------
mkdir -p "$APP_DIR" "$BIN_DIR" "$CONFIG_DIR"
if [ -n "${TR_SRC:-}" ]; then
    say "Copying sources from $TR_SRC"
    have tar || die "tar is required"
    [ -d "$TR_SRC/src/ticket_runner" ] || die "$TR_SRC does not contain src/ticket_runner"
    rm -rf "$APP_DIR"; mkdir -p "$APP_DIR"
    tar -C "$TR_SRC" --exclude='.git' --exclude='__pycache__' -cf - . | tar -C "$APP_DIR" -xf -
    ok "sources in $APP_DIR (a copy: it will not update itself)"
else
    # A clone rather than a tarball: it is what lets the runner answer "am I
    # still on the latest version" with one git fetch, once an hour, and update
    # itself when the answer is no. Shallow, because no run ever reads history.
    say "Cloning $TR_REPO ($TR_REF)"
    rm -rf "$APP_DIR"
    GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --branch "$TR_REF" \
        "https://github.com/$TR_REPO.git" "$APP_DIR" \
        || die "clone failed (private repository, or no such branch?)"
    ok "sources in $APP_DIR ($(git -C "$APP_DIR" rev-parse --short HEAD))"
fi

# --- 3. executable ----------------------------------------------------------
PYTHON="$(command -v python3)"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$APP_DIR/bin/ticket-runner.in" > "$BIN"
chmod +x "$BIN"
ok "command installed: $BIN"

# --- 4. configuration -------------------------------------------------------
if [ -f "$CONFIG" ]; then
    ok "existing configuration kept: $CONFIG"
else
    cp "$APP_DIR/config.example.toml" "$CONFIG"
    chmod 600 "$CONFIG"
    ok "configuration created: $CONFIG"

    # The token and the database are the only two things this script cannot
    # work out on its own — so ask, while a terminal is still there to answer.
    if (exec 3</dev/tty) 2>/dev/null; then
        printf '\n    %sNotion integration token%s (https://www.notion.so/my-integrations)\n' "$BOLD" "$RESET"
        printf '    %s(press enter to fill it in later)%s > ' "$DIM" "$RESET"
        read -r token </dev/tty || token=""
        if [ -n "$token" ]; then
            python3 - "$CONFIG" "$token" <<'PY'
import sys, pathlib
path, token = pathlib.Path(sys.argv[1]), sys.argv[2].strip()
text = path.read_text()
path.write_text(text.replace('token = "ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"', f'token = "{token}"'))
PY
            ok "token saved"
        fi
        # Nothing needs to exist in Notion yet: give a page shared with the
        # integration and `init` builds the four databases under it.
        printf '    %sURL of a Notion page to build the board under%s\n' "$BOLD" "$RESET"
        printf '    %s(share it with your integration first: the page ... menu -> Connections)%s > ' "$DIM" "$RESET"
        read -r page </dev/tty || page=""
        if [ -n "$page" ] && [ -n "$token" ]; then
            printf '\n'
            "$BIN" init "$page" || warn "run it again once the page is shared: ticket-runner init <url>"
        elif [ -n "$page" ]; then
            warn "no token yet - then: ticket-runner init $page --token ntn_..."
        fi
        printf '\n'
    fi
fi

# --- 5. clickable session links ---------------------------------------------
# Registers ticket-runner:// with the desktop, so the Session cell of a ticket
# opens a terminal already inside that Claude Code session.
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
if [ -d "$APP_DIR/desktop" ]; then
    say "Registering ticket-runner:// links"
    mkdir -p "$DESKTOP_DIR"
    sed -e "s|@BIN@|$BIN|g" \
        "$APP_DIR/desktop/ticket-runner-url-handler.desktop.in" \
        > "$DESKTOP_DIR/ticket-runner-url-handler.desktop"
    have update-desktop-database && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1
    if have xdg-mime; then
        xdg-mime default ticket-runner-url-handler.desktop x-scheme-handler/ticket-runner \
            >/dev/null 2>&1 && ok "ticket-runner:// links open a terminal on the session" \
            || warn "could not register ticket-runner:// with the desktop"
    fi
fi

# --- 6. timer ---------------------------------------------------------------
if [ "${TR_NO_SERVICE:-0}" != "1" ] && have systemctl; then
    # The interval lives in the configuration, so that changing it later is one
    # number and "ticket-runner enable" rather than a reinstall. TR_INTERVAL
    # only seeds it, on a configuration that does not set it yet.
    INTERVAL=$(python3 - "$CONFIG" "$TR_INTERVAL" <<'PY'
import pathlib, re, sys, tomllib
path, seed = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
with path.open("rb") as handle:
    current = tomllib.load(handle).get("runner", {}).get("interval_seconds")
if current is None:
    text = re.sub(r"^(\[runner\]\n)", rf"\g<1>interval_seconds = {int(seed)}\n", text, count=1, flags=re.M)
    path.write_text(text)
    current = int(seed)
print(int(current))
PY
)
    say "Installing the timer (one run every ${INTERVAL}s)"
    mkdir -p "$UNIT_DIR"
    ACCURACY=30s
    [ "$INTERVAL" -lt 60 ] && ACCURACY=1s
    # The login PATH is copied into the unit: a systemd service has neither
    # ~/.local/bin nor node in its own, so it would find neither claude nor npm.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ticket-runner.service.in" > "$UNIT_DIR/ticket-runner.service"
    sed -e "s|@INTERVAL@|$INTERVAL|g" -e "s|@ACCURACY@|$ACCURACY|g" \
        "$APP_DIR/systemd/ticket-runner.timer.in" > "$UNIT_DIR/ticket-runner.timer"
    # The console's unit is installed and left alone. It listens on a port, and
    # behind that port sits a runner that starts Claude Code sessions with
    # bypassPermissions — opening it is a decision, not a default.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ticket-runner-web.service.in" > "$UNIT_DIR/ticket-runner-web.service"
    systemctl --user daemon-reload
    systemctl --user enable --now ticket-runner.timer >/dev/null 2>&1 \
        && ok "ticket-runner.timer enabled" \
        || warn "enable it by hand: systemctl --user enable --now ticket-runner.timer"
    # Without lingering, the timer stops when the session closes.
    if have loginctl && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
        warn "to keep it running with no session open: sudo loginctl enable-linger $USER"
    fi
else
    warn "timer not installed — run passes by hand with “ticket-runner run”"
fi

# --- 7. summary -------------------------------------------------------------
printf '\n%sinstallation complete.%s\n\n' "$BOLD" "$RESET"
printf '  Build the Notion board (skip if you just did):\n\n    %sticket-runner init <page-url>%s\n\n' "$BOLD" "$RESET"
printf '  Check everything is in place:\n\n    %sticket-runner doctor%s\n\n' "$BOLD" "$RESET"
printf '  %sconfiguration%s  %s\n' "$DIM" "$RESET" "$CONFIG"
printf '  %sready tickets%s  ticket-runner list\n' "$DIM" "$RESET"
printf '  %sone run%s        ticket-runner run\n' "$DIM" "$RESET"
printf '  %sfollow along%s   ticket-runner logs -f\n' "$DIM" "$RESET"
printf '  %sweb console%s    ticket-runner serve   %s(board, CLI and chat, on 127.0.0.1)%s\n' "$DIM" "$RESET" "$DIM" "$RESET"
printf '  %sversion%s        kept up to date on its own — ticket-runner update\n\n' "$DIM" "$RESET"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) printf '  %s!%s add %s to your PATH: echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.bashrc\n\n' "$YELLOW" "$RESET" "$BIN_DIR" ;;
esac
