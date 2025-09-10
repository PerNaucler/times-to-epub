#!/usr/bin/env bash

GREEN="\e[32m"; RESET="\e[0m"; CHECK="${GREEN}✔${RESET}"
say(){ echo -e "${CHECK} $*"; sleep 1; }

say "Steg 1: Växlar till användare pelle_user för setup..."
su - pelle_user << 'EOF'
echo -e "\e[32m✔\e[0m Steg 2: Kollar om virtuell miljö redan finns..."
sleep 1
if [ ! -d "$HOME/pellepyth" ]; then
  echo -e "\e[32m✔\e[0m Skapar virtuell miljö..."
  sleep 1
  python3 -m venv "$HOME/pellepyth"
else
  echo -e "\e[32m✔\e[0m Virtuell miljö finns redan – hoppar över skapande."
fi

echo -e "\e[32m✔\e[0m Steg 3: Aktiverar virtuell miljö..."
sleep 1
source "$HOME/pellepyth/bin/activate"

echo -e "\e[32m✔\e[0m Steg 4: Uppdaterar setuptools..."
sleep 1
pip install -U setuptools

echo -e "\e[32m✔\e[0m Steg 5: Installerar Python-paket..."
sleep 1
pip install selenium undetected-chromedriver beautifulsoup4 readability-lxml requests-html tqdm
EOF

say "Steg 6: Installerar Calibre med apt-get (som root)..."
apt-get update -y
sleep 1
apt-get install -y calibre

say "Steg 7: Lägger till auto-aktivering av venv i pelle_users .bashrc..."
sudo -u pelle_user bash -lc 'grep -q "pellepyth/bin/activate" ~/.bashrc || \
  printf "\n# Auto-activate pellepyth\n[ -f ~/pellepyth/bin/activate ] && source ~/pellepyth/bin/activate\n" >> ~/.bashrc'


# Säkerställ att login-shells laddar .bashrc (om .bash_profile finns/saknas)
sudo -u pelle_user bash -lc 'if [ ! -f ~/.bash_profile ] || ! grep -q "\.bashrc" ~/.bash_profile; then \
  printf "\n# Load .bashrc for login shells\nif [ -f ~/.bashrc ]; then . ~/.bashrc; fi\n" >> ~/.bash_profile; fi'


# --------- Nedanstående Steg 8 ersätter följande rader: ---------------
# ~/venvs/times/bin/python -m pip install --upgrade pip
# ~/venvs/times/bin/python -m pip install python-dotenv
# --- Bootstrap/uppdatera Python-venv 'times' ---
say "Steg 8: Säkerställa paketet som tillhandahåller dotenv..."

set -euo pipefail

VENV="$HOME/venvs/times"

# Skapa venv om den saknas
if [ ! -x "$VENV/bin/python" ]; then
  echo "➕ Skapar venv: $VENV"
  mkdir -p "$HOME/venvs"
  python3 -m venv "$VENV"
fi

echo "⬆️  Uppgraderar pip/setuptools/wheel i venv…"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel

echo "📦 Installerar/uppdaterar python-dotenv…"
"$VENV/bin/python" -m pip install --upgrade python-dotenv


# --------- Nedanstående Steg 9 ersätter följande rad: -----------------
# sudo apt install chromium-browser chromium-chromedriver --------------
say "Steg 9: Installerar Chromium + Chromedriver..."
export DEBIAN_FRONTEND=noninteractive

# Försök med Ubuntus paketnamn först (kan vara transition till snap på vissa versioner)
if apt-get install -y chromium-browser chromium-chromedriver >/dev/null 2>&1; then
  say "Installerade chromium-browser + chromium-chromedriver."
else
  say "Försöker med alternativa paketnamn (chromium + chromium-driver)..."
  apt-get update -y >/dev/null
  apt-get install -y chromium chromium-driver || {
    echo -e "\e[31m✖\e[0m Misslyckades installera Chromium/driver via apt."
    exit 1
  }
fi

# Verifiera installationen
if command -v chromium-browser >/dev/null 2>&1; then BROWSER="chromium-browser"
elif command -v chromium >/dev/null 2>&1; then BROWSER="chromium"
else BROWSER=""; fi

if command -v chromedriver >/dev/null 2>&1; then DRIVER="$(command -v chromedriver)"; else DRIVER=""; fi

[ -n "$BROWSER" ] && say "Chromium hittades: $(command -v "$BROWSER")" \
                  || echo -e "\e[31m✖\e[0m Hittar inte Chromium i PATH."
[ -n "$DRIVER" ]  && say "Chromedriver hittades: $DRIVER" \
                  || echo -e "\e[31m✖\e[0m Hittar inte chromedriver i PATH."

# -------------- Nedanstående steg 10 ersätter följande rader: ----------
# export TIMES_USER="per.naucler@gmail.com" ----------------------------
# export TIMES_PASS="*********" ----------------------------------------

say "Steg 10: Säkerställer att .env autoladdas..."

# Säkerställ korrekta rättigheter på .env (så vi inte läcker lösenord)
sudo -u pelle_user bash -lc '
  if [ -f ~/.env ]; then chmod 600 ~/.env; fi
'

# Lägg in auto-laddning av .env i .bashrc om det saknas
sudo -u pelle_user bash -lc '
  grep -q "Auto-load .env" ~/.bashrc || cat >> ~/.bashrc <<'"'"'DOTENV'"'"'
# Auto-load .env (exportera alla variabler)
if [ -f "$HOME/.env" ]; then
  set -a
  . "$HOME/.env"
  set +a
fi
DOTENV
'

# Se till att login-shells läser .bashrc
sudo -u pelle_user bash -lc '
  [ -f ~/.bash_profile ] && grep -q "\.bashrc" ~/.bash_profile || \
    printf "\n# Load .bashrc for login shells\n[ -f ~/.bashrc ] && . ~/.bashrc\n" >> ~/.bash_profile
'

say "Steg 11: Växlar till pelle_user för interaktiv session (venv aktiveras automatiskt)..."
exec sudo -iu pelle_user
