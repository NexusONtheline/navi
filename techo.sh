#!/usr/bin/env bash
# Modo techo: barras de audio (cava) en pantalla completa en el proyector HDMI.
#
#   ./techo.sh musica   lo que suena en los parlantes
#   ./techo.sh voz      el micrófono
#   ./techo.sh apagar   cierra la ventana del techo
#
# Usa su propia config de cava (no toca ~/.config/cava/config).
# Para otra salida que no empiece por HDMI: TECHO_SALIDA=DP-1 ./techo.sh musica
# Códigos de salida: 0 bien, 1 error, 2 no hay proyector, 3 falta Sway o un programa,
# 4 no hay micrófono.
set -u

CARPETA="${XDG_RUNTIME_DIR:-/tmp}/navi"
PID="$CARPETA/techo.pid"
CONF="$CARPETA/techo-cava.conf"
CLASE="navi-techo"
mkdir -p "$CARPETA"

# ¿La ventana del techo sigue abierta? (comprobamos que el PID sea de verdad nuestro)
encendido() {
    [[ -f $PID ]] && grep -qa -- "$CLASE" "/proc/$(cat "$PID")/cmdline" 2>/dev/null
}

apagar() {
    if encendido; then
        kill "$(cat "$PID")"
        rm -f "$PID"
        echo "Techo apagado."
    else
        rm -f "$PID"
        echo "El techo ya estaba apagado."
    fi
}

modo="${1:-musica}"
case "$modo" in
    apagar | apaga | off) apagar; exit 0 ;;
    musica | música) modo=musica ;;
    voz | microfono | micrófono) modo=voz ;;
    *) echo "Uso: $0 musica | voz | apagar" >&2; exit 1 ;;
esac

if [[ -z ${SWAYSOCK:-} ]] || ! command -v swaymsg >/dev/null; then
    echo "El modo techo solo funciona en Sway por ahora."; exit 3
fi
for programa in cava alacritty pactl jq; do
    command -v "$programa" >/dev/null || { echo "Me falta $programa para el modo techo."; exit 3; }
done

# 1. El proyector: la primera salida HDMI que vea Sway, sin asumir su nombre
salidas="$(swaymsg -t get_outputs -r)"
salida="${TECHO_SALIDA:-$(jq -r '[.[] | select(.name | test("^HDMI"))][0].name // empty' <<<"$salidas")}"
if [[ -z $salida ]] || ! jq -e --arg s "$salida" 'any(.[]; .name == $s)' <<<"$salidas" >/dev/null; then
    echo "No veo el proyector conectado. Revisa el cable HDMI y que esté encendido."
    exit 2
fi

# 2. Resolución baja: 800x600, si no 1024x768, si no la más pequeña que ofrezca
modos="$(jq -r --arg s "$salida" '.[] | select(.name == $s) | .modes[] | "\(.width)x\(.height)"' <<<"$salidas" | sort -u)"
elegido=""
for preferido in 800x600 1024x768; do
    if grep -qx "$preferido" <<<"$modos"; then elegido="$preferido"; break; fi
done
if [[ -z $elegido && -n $modos ]]; then
    elegido="$(awk -Fx '{print $1 * $2, $0}' <<<"$modos" | sort -n | head -1 | cut -d' ' -f2)"
fi
if [[ -n $elegido ]]; then
    swaymsg output "$salida" enable mode "$elegido" >/dev/null
else
    swaymsg output "$salida" enable >/dev/null
fi

# 3. De dónde escucha cava
if [[ $modo == musica ]]; then
    fuente="$(pactl get-default-sink).monitor"
else
    fuente="$(pactl get-default-source)"
    if [[ -z $fuente || $fuente == *.monitor ]]; then  # eso no es un micrófono de verdad
        fuente="$(pactl list short sources | awk '$2 !~ /\.monitor$/ {print $2; exit}')"
    fi
    if [[ -z $fuente ]]; then echo "No encuentro ningún micrófono."; exit 4; fi
fi

# 4. Config propia de cava, con el degradado Lain (oscuro abajo, claro en los picos)
cat >"$CONF" <<EOF
[general]
framerate = 30
bar_width = 2
bar_spacing = 1

[input]
method = pulse
source = $fuente

[output]
method = noncurses

[color]
gradient = 1
gradient_count = 3
gradient_color_1 = '#1a0033'
gradient_color_2 = '#7b2cbf'
gradient_color_3 = '#e0aaff'
EOF

# 5. La ventana: si ya había una, se cambia por la nueva
encendido && apagar >/dev/null
antes="$(swaymsg -t get_tree -r | jq -r '.. | objects | select(.focused == true and .type != "workspace") | .id' | head -1)"
pantalla_antes="$(swaymsg -t get_workspaces -r | jq -r '.[] | select(.focused) | .output')"
setsid alacritty --class "$CLASE" --title "NAVI techo" \
    -o 'window.decorations="None"' -o 'window.padding={x=0, y=0}' \
    -o 'colors.primary.background="#000000"' -o 'font.size=10' \
    -e cava -p "$CONF" </dev/null >/dev/null 2>&1 &
echo $! >"$PID"

for _ in $(seq 50); do  # hasta 5 s a que aparezca
    if swaymsg -t get_tree -r | jq -e --arg c "$CLASE" 'any(..; objects | .app_id? == $c)' >/dev/null; then
        swaymsg "[app_id=\"^$CLASE\$\"] move container to output \"$salida\", focus, fullscreen enable" >/dev/null
        # Devolver el foco a donde estabas, para no escribir en el techo sin querer
        [[ -n $pantalla_antes && $pantalla_antes != "$salida" ]] && swaymsg focus output "$pantalla_antes" >/dev/null
        [[ -n $antes ]] && swaymsg "[con_id=$antes] focus" >/dev/null
        if [[ $modo == musica ]]; then
            echo "Techo encendido con la música en $salida${elegido:+ ($elegido)}."
        else
            echo "Techo encendido con tu voz en $salida${elegido:+ ($elegido)}."
        fi
        exit 0
    fi
    encendido || break
    sleep 0.1
done
apagar >/dev/null
echo "No pude abrir la ventana del techo."
exit 1
