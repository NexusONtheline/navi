#!/usr/bin/env bash
# Instalador de NAVI para Linux Mint / Ubuntu / Debian y Arch / LainOS.
# Uso: ./instalar.sh   (pide tu contraseña para instalar programas del sistema)
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
RAIZ="$PWD"

paso() { printf '\n\033[1;35m▸ %s\033[0m\n' "$*"; }
nota() { printf '  %s\n' "$*"; }
si() { local r; read -r -p "  $1 [S/n] " r; [[ -z "$r" || "$r" =~ ^[sSyY] ]]; }

printf '\033[1;35m'
cat <<'EOF'
   _  _____ _   _ ___
  | \| | _ \ \ / /_ _|   Instalador de NAVI
  | .` |   /\ V / | |    En la actualidad. En este momento.
  |_|\_|_|_\ \_/ |___|
EOF
printf '\033[0m'

# ---------------------------------------------------------------- 1. Programas
paso "1/7 Programas del sistema"
if command -v apt-get >/dev/null; then
    deseados=(python3 python3-venv python3-pip git curl unzip espeak-ng mpv mpv-mpris
              playerctl ffmpeg pulseaudio-utils pipewire-bin bluez libnotify-bin
              xclip wmctrl gnome-screenshot alsa-utils)
    nota "Detecté apt (Linux Mint / Ubuntu / Debian)."
    sudo apt-get update -qq
    paquetes=()
    for p in "${deseados[@]}"; do  # algunos no existen en versiones viejas: los saltamos
        if apt-cache show "$p" >/dev/null 2>&1; then paquetes+=("$p"); fi
    done
    sudo apt-get install -y "${paquetes[@]}"
elif command -v pacman >/dev/null; then
    nota "Detecté pacman (Arch / LainOS)."
    sudo pacman -S --needed --noconfirm python git curl unzip espeak-ng mpv mpv-mpris \
        playerctl ffmpeg libpulse pipewire bluez-utils libnotify wl-clipboard grim \
        xclip wmctrl alsa-utils deno
else
    nota "No reconozco tu gestor de paquetes. Instala a mano: python3 (3.10+), venv,"
    nota "git, curl, unzip, espeak-ng, mpv, playerctl, ffmpeg y un portapapeles (xclip o wl-clipboard)."
fi

if ! command -v deno >/dev/null && [[ ! -x "$HOME/.deno/bin/deno" ]]; then
    nota "Deno hace falta para que la música de YouTube funcione (resuelve sus acertijos anti-bots)."
    if si "¿Instalar Deno desde deno.land?"; then
        curl -fsSL https://deno.land/install.sh | sh -s -- -y --no-modify-path
    fi
fi

# ---------------------------------------------------------------- 2. Python
paso "2/7 Entorno de Python"
python3 - <<'EOF' || { echo "NAVI necesita Python 3.10 o más nuevo."; exit 1; }
import sys
sys.exit(sys.version_info < (3, 10))
EOF
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
nota "Instalando librerías (puede tardar unos minutos)..."
.venv/bin/pip install -q -r requirements.txt

# ---------------------------------------------------------------- 3. Configuración
paso "3/7 Configuración (.env)"
if [[ -f .env ]]; then
    nota "Ya tienes un .env: lo dejo como está."
else
    cp .env.example .env
    chmod 600 .env
    nota "Necesitas una API key GRATIS de Gemini: https://aistudio.google.com/apikey"
    read -r -s -p "  Pégala aquí (no se verá mientras escribes) y pulsa Enter: " clave; echo
    read -r -p "  ¿Cómo quieres que NAVI te llame? " nombre
    read -r -p "  ¿En qué ciudad vives? (para el clima, ej: Quito, Ecuador) " ciudad
    python3 - "$clave" "$nombre" "$ciudad" <<'EOF'
import sys
from pathlib import Path
clave, nombre, ciudad = sys.argv[1:4]
env = Path(".env")
texto = env.read_text()
texto = texto.replace("GEMINI_API_KEY=pega-aqui-tu-api-key", f"GEMINI_API_KEY={clave.strip()}")
texto = texto.replace("NAVI_USUARIO=\n", f"NAVI_USUARIO={nombre.strip()}\n")
texto = texto.replace("NAVI_CIUDAD=\n", f"NAVI_CIUDAD={ciudad.strip()}\n")
env.write_text(texto)
EOF
    nota "Guardado en .env (solo tú puedes leerlo y nunca se sube a GitHub)."
fi

# ---------------------------------------------------------------- 4. Modelos
paso "4/7 Voz y oídos de NAVI (unos 650 MB, solo la primera vez)"
mkdir -p voces modelos
if [[ ! -f voces/es_ES-sharvard-medium.onnx ]]; then
    nota "Descargando la voz..."
    .venv/bin/python -m piper.download_voices --download-dir voces es_ES-sharvard-medium
fi
if [[ ! -d modelos/vosk-model-small-es-0.42 ]]; then
    nota "Descargando el detector de «NAVI, actívate»..."
    curl -fsSL -o modelos/vosk-es.zip https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
    unzip -q modelos/vosk-es.zip -d modelos && rm modelos/vosk-es.zip
fi
nota "Descargando el oído (Whisper)..."
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='modelos')" 2>/dev/null

# ---------------------------------------------------------------- 5. Comando y menú
paso "5/7 Comando «navi» y acceso en el menú"
chmod +x navi.sh
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
ln -sf "$RAIZ/navi.sh" "$HOME/.local/bin/navi"
cat > "$HOME/.local/share/applications/navi.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NAVI
Comment=Tu asistente estilo Serial Experiments Lain
Exec=$RAIZ/navi.sh
Terminal=true
Icon=utilities-terminal
Categories=Utility;
EOF
nota "Escribe «navi» en una terminal, o búscala en el menú de aplicaciones."
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) nota "(Si la terminal no encuentra «navi», cierra sesión y vuelve a entrar.)" ;;
esac

# ---------------------------------------------------------------- 6. Atajo y arranque
paso "6/7 Arranque automático"
if [[ -n "${SWAYSOCK:-}" ]]; then
    nota "Usas Sway: agrega esto a ~/.config/sway/config si aún no lo tienes:"
    nota "  bindsym \$mod+n exec alacritty --class navi --title NAVI -e $RAIZ/navi.sh"
    nota "  for_window [app_id=\"^navi\$\"] floating enable, resize set 900 560, move position center"
    nota "  exec $RAIZ/navi.sh --despertar"
    nota "  exec $RAIZ/navi.sh --saludo"
else
    mkdir -p "$HOME/.config/autostart"
    if si "¿Activar «NAVI, actívate»? (el micrófono escucha SOLO esa frase, sin internet)"; then
        cat > "$HOME/.config/autostart/navi-vigilante.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NAVI (vigilante)
Comment=Escucha «NAVI, actívate»
Exec=$RAIZ/navi.sh --despertar
X-GNOME-Autostart-Delay=5
EOF
        setsid "$RAIZ/navi.sh" --despertar >/dev/null 2>&1 < /dev/null &
    fi
    if si "¿Quieres que NAVI te salude al encender el PC (clima y recordatorios)?"; then
        cat > "$HOME/.config/autostart/navi-saludo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NAVI (saludo)
Comment=NAVI te saluda al iniciar sesión
Exec=$RAIZ/navi.sh --saludo
X-GNOME-Autostart-Delay=10
EOF
    fi
    # Atajo Super+N en Cinnamon (Linux Mint)
    if gsettings list-schemas 2>/dev/null | grep -qx org.cinnamon.desktop.keybindings; then
        if si "¿Crear el atajo Super+N para abrir NAVI?"; then
            python3 - "$RAIZ" <<'EOF'
import ast, subprocess, sys
raiz = sys.argv[1]
esquema = "org.cinnamon.desktop.keybindings"
lista = ast.literal_eval(subprocess.run(["gsettings", "get", esquema, "custom-list"],
                                        capture_output=True, text=True).stdout.strip().removeprefix("@as "))
nombre = next(f"custom{i}" for i in range(100) if f"custom{i}" not in lista)
ruta = f"org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/{nombre}/"
for clave, valor in (("name", "'NAVI'"), ("command", f"'{raiz}/navi.sh --abrir'"), ("binding", "['<Super>n']")):
    subprocess.run(["gsettings", "set", ruta, clave, valor], check=True)
subprocess.run(["gsettings", "set", esquema, "custom-list", str(lista + [nombre])], check=True)
EOF
            nota "Listo: Super+N abre NAVI."
        fi
    fi
fi

# ---------------------------------------------------------------- 7. Fin
paso "7/7 ¡Listo!"
nota "Abre NAVI escribiendo «navi» en una terminal."
nota "Dentro: escribe, o pulsa Enter vacío para hablarle."
nota "Si el micrófono no te oye, revisa que no esté silenciado en la configuración de sonido."
echo
