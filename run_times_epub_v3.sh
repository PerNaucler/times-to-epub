#!/usr/bin/env bash
set -Eeuo pipefail

echo "******** Nu startar run_times_epub_v3.sh ***************"

LOCKFILE="/home/pelle_user/.cache/times_cron.lock"
mkdir -p /home/pelle_user/.cache
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "$(date) – redan igång, avbryter."
  exit 0
fi
# ...resten av skriptet...

HOME="/home/pelle_user"
USER="pelle_user"

# --- Load .env for cron runs ---
if [ -f "$HOME/.env" ]; then
  set -a            # exportera allt vi sourcar
  # shellcheck disable=SC1090
  source "$HOME/.env"
  set +a
fi

# --- Konfig ---
VENV="$HOME/venvs/times"
PY="$VENV/bin/python"
SCRIPT="$HOME/times_to_epub_thin_v2.py"
OUTDIR="$HOME/times_dump"
HTML="$OUTDIR/times_$(date +%F).html"
EPUB="$OUTDIR/times_$(date +%F).epub"

# SMTP (måste finnas i env, exportera i .bashrc/.profile eller i crontab)
: "${KINDLE_USER:?KINDLE_USER saknas}"
: "${GMX_USER:?GMX_USER saknas}"
: "${GMX_PASS:?GMX_PASS saknas}"
: "${TIMES_USER:?TIMES_USER saknas}"
: "${TIMES_PASS:?TIMES_PASS saknas}"

# --- Miljö som ofta saknas i script/cron ---
export TZ="${TZ:-Europe/Stockholm}"
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PATH="/usr/bin:/usr/local/bin:$PATH"

# Liten säkerhetsstädning (om förra körningen dog)
pkill -9 -u "$USER" chrome || true
pkill -9 -u "$USER" chromedriver || true
rm -rf /tmp/times_chrome_* 2>/dev/null || true


# Egen, ren Chrome-profil per körning (undviker låsningar)
CHROME_TMP="$(mktemp -d -t chrome-prof-XXXXXX)"
cleanup() {
  rm -rf "$CHROME_TMP" || true
}
trap cleanup EXIT

# Visa vad vi använder (bra för felsökning)
echo "python:        $PY"
echo "google-chrome: $(command -v google-chrome || echo 'not found')"
echo "ebook-convert: $(command -v ebook-convert || echo 'not found')"
"$PY" -V

# Säkerställ venv
if [[ ! -x "$PY" ]]; then
  echo "❌ Hittar inte venv på $PY" >&2
  exit 1
fi

# Skapa ut-katalog
mkdir -p "$OUTDIR"

echo "🚀 Startar Times→EPUB …"
echo "🔐 Loggar in …"

# KÖR PYTHON MED TILLFÄLLIG PROFIL & HEADLESS
# (scriptet läser TIMES_USER/TIMES_PASS från env)
# Vi skickar även vidare CHROME_USER_DATA_DIR så Python kan lägga in det i options.
export CHROME_USER_DATA_DIR="$CHROME_TMP"
export CHROME_FORCE_HEADLESS=1

# -u = unbuffered (ser logg i realtid)
set +e
"$PY" -u "$SCRIPT" 2>&1
PY_RC=$?
set -e

if [[ $PY_RC -ne 0 ]]; then
  echo "❌ Python-skriptet returnerade kod $PY_RC" >&2
  exit $PY_RC
fi

# Konvertera → EPUB (Calibre)
if [[ -f "$HTML" ]]; then
  echo "📄 Hittade HTML: $HTML – konverterar till EPUB…"
  ebook-convert "$HTML" "$EPUB" \
    --authors "The Times" \
    --title   "The Times $(date +%F)" \
    --pretty-print \
    --chapter "//*[(self::h1 or self::h2)][1]"
else
  echo "❌ Hittade inte HTML ($HTML). Avbryter." >&2
  exit 2
fi

# Skicka e-post (bara om EPUB finns)
if [[ -f "$EPUB" ]]; then
  echo "✉️  Skickar EPUB…"
  calibre-smtp "$GMX_USER" "$KINDLE_USER" "Detta aer text" \
      -v -r smtp.gmx.com --port 465 --encryption-method SSL \
      -u "$GMX_USER" -p "$GMX_PASS" \
      --subject "Nyheter $(date +%F)" \
      --attachment "$EPUB"
  echo "✅ Klart."
else
  echo "❌ Ingen EPUB hittades efter konvertering." >&2
  exit 3
fi
