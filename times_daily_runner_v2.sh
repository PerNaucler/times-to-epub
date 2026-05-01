#!/usr/bin/env bash
set -Eeuo pipefail

# === KONFIG ===

ENV_FILE="/home/pelle_user/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "Hittar inte env-fil: $ENV_FILE"
  exit 1
fi

TARGET_HOUR=${TARGET_HOUR:-22}
TARGET_MINUTE=${TARGET_MINUTE:-00}
RUNNER="${RUNNER:-$HOME/run_times_epub_v3.sh}"
LOG="${LOG:-$HOME/times_runner.log}"
ALERT_TO="${ALERT_TO:-per.naucler@gmail.com}"
# GMX_USER måste finnas i env (används för varningsmejl)
# GMX_PASS måste finnas i env (export GMX_PASS=...)

LOCK=/tmp/times_runner.lock
PIDFILE=/tmp/times_runner.pid

# === HJÄLPFUNKTIONER ===
log() { printf '%(%Y-%m-%d %H:%M:%S)T : %s\n' -1 "$*" ; } # Skriver bara till StdOut
# log() { printf '%(%Y-%m-%d %H:%M:%S)T : %s\n' -1 "$*" | tee -a "$LOG"; }

# Endast en instans
exec 9>"$LOCK"
if ! flock -n 9; then log "🔒 En annan instans körs redan. Avslutar."; exit 0; fi
echo $$ > "$PIDFILE"

trap 'log "↪️  Fick signal, avslutar."; rm -f "$PIDFILE"; exit 0' INT TERM

next_epoch() {
  local now target
  now=$(date +%s)
  target=$(date -d "today ${TARGET_HOUR}:${TARGET_MINUTE}" +%s)
  (( now >= target )) && target=$(date -d "tomorrow ${TARGET_HOUR}:${TARGET_MINUTE}" +%s)
  printf '%s\n' "$target"
}

sleep_until() {
  local target=$1 now left chunk
  while :; do
    now=$(date +%s)
    left=$(( target - now ))
    (( left <= 0 )) && break
    chunk=$(( left > 60 ? 60 : left ))   # sov i 60-sekunders chunkar
    log "⏳ sover… kvar: ${left}s"
    sleep "$chunk" || true               # ignorera avbruten sleep
  done
}

run_once() {
  local attempt=1 rc
  while (( attempt <= 10 )); do
    log "▶️  Kör $RUNNER (försök #$attempt)…"
    if /bin/bash "$RUNNER" >>"$LOG" 2>&1; then
      log "✅ Körning klar."
      return 0
    fi
    rc=$?
    log "⚠️  Körning misslyckades (rc=$rc). Försöker igen om 15s."
    (( attempt++ ))
    sleep 15
  done

  log "❌ Misslyckades tio gånger – skickar varning."
  # Varningsmejl (använder calibre-smtp som du redan har)
  # calibre-smtp "$ALERT_TO" "$ALERT_TO" \
  #  "The Times misslyckades tio gånger" \
  #  -r smtp.gmx.com --port 465 --encryption-method SSL \
  #  -u "$GMX_USER" -p "${GMX_PASS:-}" \
  #  --subject "The Times misslyckades tio gånger $(date '+%Y-%m-%d %H:%M')" \
  #  --body "Se loggfilen: $LOG"

  echo "Se loggfilen: $LOG" | calibre-smtp "$GMX_USER" "$ALERT_TO" \
  "The Times misslyckades tio gånger $(date '+%Y-%m-%d %H:%M')" \
  -r smtp.gmx.com --port 465 --encryption-method SSL \
  -u "$GMX_USER" -p "$GMX_PASS"

  return 1
}

log "=== startar scheduler; mål $(printf '%02d:%02d' "$TARGET_HOUR" "$TARGET_MINUTE") ==="

while :; do
  target=$(next_epoch)
  log "🛌 Sover till $(date -d "@$target" '+%Y-%m-%d %H:%M:%S')."
  sleep_until "$target"
  log "⏰ Vaknade $(date '+%Y-%m-%d %H:%M:%S'), startar körning."
  run_once || true
  # …och så räknar vi fram nästa körning i loopen
done
