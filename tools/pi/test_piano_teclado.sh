#!/bin/bash
# Pruebas de piano-teclado.sh (fase 11) con systemd, motor, interfaz y sudo FALSOS: no arranca el piano real, no
# suena nada y NUNCA apaga la Pi (sudo falso). Cubre: arranque y paso de opciones, espera a la tarjeta al encender
# (con el progreso para la pantalla de inicio), F12 -> cierra el piano y apaga, errores, y la pantalla de inicio en
# una pseudoterminal (script).
# Uso: bash test_piano_teclado.sh
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
comprobar() { if eval "$2"; then ok "$1"; else fallo "$1"; fi; }
mkdir -p "$T/shim" "$T/run"
export XDG_RUNTIME_DIR="$T/run" SHIM_LOG="$T/log" SHIM_ESTADO="$T/estado-unidad" PIANO_PREFERENCIAS="$T/prefs.json"
echo '{"salida": "alsa_output.usb-Prueba_Tarjeta-00.analog-stereo"}' > "$PIANO_PREFERENCIAS"

# systemctl --user: estado de la unidad en un archivo; las órdenes se registran
cat > "$T/shim/systemctl" <<'EOF'
#!/bin/bash
[ "$1" = --user ] && shift
case "$1" in
    is-active) [ "$(cat "$SHIM_ESTADO" 2>/dev/null)" = activa ] ;;
    stop) echo "stop $2" >> "$SHIM_LOG"; echo parada > "$SHIM_ESTADO" ;;
    *) exit 0 ;;
esac
EOF
# systemd-run: motor falso que publica su progreso (como piano-en-vivo.sh) y queda listo (o falla: SHIM_MOTOR_FALLA)
cat > "$T/shim/systemd-run" <<'EOF'
#!/bin/bash
args=(); for a in "$@"; do case "$a" in --user|--quiet|--collect|--unit=*) ;; *) args+=("$a") ;; esac; done
echo "motor ${args[*]}" >> "$SHIM_LOG"
if [ -n "${SHIM_MOTOR_FALLA:-}" ]; then echo parada > "$SHIM_ESTADO"; exit 0; fi
echo activa > "$SHIM_ESTADO"
( P="$XDG_RUNTIME_DIR/piano-vivo.progreso"
  sleep 0.3; printf '%s\tsalida\talsa_output.usb-Prueba_Tarjeta-00.analog-stereo\t44100\n' "$(date +%s.%N)" >> "$P"
  sleep 0.2; printf '%s\tsonido\tosiris\n' "$(date +%s.%N)" >> "$P"
  sleep 0.3; printf '%s\tlisto\n' "$(date +%s.%N)" >> "$P"; touch "$XDG_RUNTIME_DIR/piano-vivo.listo" ) &
EOF
printf '#!/bin/bash\necho "journal: el motor falló (simulado)"\n' > "$T/shim/journalctl"
cat > "$T/shim/sudo" <<'EOF'
#!/bin/bash
echo "sudo $*" >> "$SHIM_LOG"
[ -z "${SHIM_SIN_SUDO:-}" ] || exit 1
exit 0
EOF
cat > "$T/shim/pw-dump" <<'EOF'
#!/bin/bash
echo '[{"id": 99, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink",
  "node.name": "alsa_output.usb-Prueba_Tarjeta-00.analog-stereo", "node.description": "Tarjeta de Prueba Analog Stereo",
  "api.alsa.path": "front:99"}, "params": {}}}]'
EOF
# Interfaz falsa: registra que se abrió y termina con SHIM_RC_UI (10 = F12 confirmado)
printf '#!/bin/bash\necho "interfaz" >> "$SHIM_LOG"\nexit "${SHIM_RC_UI:-0}"\n' > "$T/shim/interfaz"
chmod +x "$T/shim/"*
export PATH="$T/shim:$PATH" PIANO_INTERFAZ="$T/shim/interfaz"
PT="$DIR/piano-teclado.sh"
correr() { : > "$SHIM_LOG"; rm -f "$SHIM_ESTADO"; SALIDA="$("$@" 2>&1 < /dev/null)"; RC=$?; }

# 1) Arranque normal (sin terminal: «Cargando el piano...», sin pantalla de inicio)
correr bash "$PT" -p -q 256
comprobar "1: arranca el motor con las opciones, abre la interfaz y termina bien" \
    '[ "$RC" -eq 0 ] && grep -qx "motor $DIR/piano-en-vivo.sh -p -q 256" "$SHIM_LOG" && grep -qx interfaz "$SHIM_LOG" || { echo "$SALIDA"; cat "$SHIM_LOG"; false; }'
comprobar "1: sin terminal, el texto de siempre" 'grep -q "Cargando el piano.* listo." <<<"$SALIDA"'
comprobar "1: al salir con ESC, el piano se cierra (y no se apaga nada)" \
    '[ "$(tail -1 "$SHIM_LOG")" = "stop piano-vivo-cadena" ] && ! grep -q poweroff "$SHIM_LOG"'
comprobar "1: el motor publica su progreso para la pantalla de inicio" \
    'cut -f2 "$XDG_RUNTIME_DIR/piano-vivo.progreso" | grep -qx inicio && cut -f2 "$XDG_RUNTIME_DIR/piano-vivo.progreso" | grep -qx listo'

# 2) Al encender: espera a la tarjeta antes de arrancar el motor
correr bash "$PT" --esperar-tarjeta 5 -p
P="$XDG_RUNTIME_DIR/piano-vivo.progreso"
comprobar "2: espera a la tarjeta y lo publica (esperando, lista con su nombre) antes de «inicio»" \
    '[ "$RC" -eq 0 ] && [ "$(cut -f2- "$P" | head -3 | tr "\t\n" " |")" = "tarjeta esperando|tarjeta lista Tarjeta de Prueba|inicio|" ] || { cat "$P"; false; }'
comprobar "2: --esperar-tarjeta no se pasa al motor" 'grep -qx "motor $DIR/piano-en-vivo.sh -p" "$SHIM_LOG"'
comprobar "2: sin terminal, muestra la espera como texto" 'grep -q "lista: Tarjeta de Prueba" <<<"$SALIDA"'
correr bash "$PT" --esperar-tarjeta
comprobar "2: --esperar-tarjeta sin segundos: error" '[ "$RC" -ne 0 ] && ! grep -q "^motor" "$SHIM_LOG"'

# 3) F12 confirmado: cierra el piano y DESPUÉS apaga
correr env SHIM_RC_UI=10 bash "$PT" -p
comprobar "3: F12: cierra el piano y luego apaga con sudo" \
    '[ "$RC" -eq 0 ] && [ "$(grep -n "stop piano-vivo-cadena" "$SHIM_LOG" | head -1 | cut -d: -f1)" -lt "$(grep -n "sudo -n systemctl poweroff" "$SHIM_LOG" | cut -d: -f1)" ] || { cat "$SHIM_LOG"; false; }'
comprobar "3: y lo dice (desenchufar con la luz verde apagada)" 'grep -q "Apagando la Raspberry Pi" <<<"$SALIDA" && grep -q "luz verde" <<<"$SALIDA"'
correr env SHIM_RC_UI=10 SHIM_SIN_SUDO=1 bash "$PT"
comprobar "3: sin sudo: error que dice cómo apagarla (código 1)" '[ "$RC" -eq 1 ] && grep -q "sudo poweroff" <<<"$SALIDA"'

# 4) Errores
correr env SHIM_MOTOR_FALLA=1 bash "$PT"
comprobar "4: si el motor no arranca: error con su registro, sin abrir la interfaz" \
    '[ "$RC" -eq 1 ] && grep -q "no pudo arrancar" <<<"$SALIDA" && grep -q "falló (simulado)" <<<"$SALIDA" && ! grep -qx interfaz "$SHIM_LOG"'
correr env SHIM_RC_UI=1 bash "$PT"
comprobar "4: si la interfaz falla: su código, sin apagar" '[ "$RC" -eq 1 ] && ! grep -q poweroff "$SHIM_LOG"'
echo activa > "$SHIM_ESTADO"; : > "$SHIM_LOG"
SALIDA="$(bash "$PT" 2>&1 < /dev/null)"; RC=$?
comprobar "4: si ya estaba en marcha, lo reinicia" '[ "$RC" -eq 0 ] && grep -q "se reinicia" <<<"$SALIDA" && [ "$(head -1 "$SHIM_LOG")" = "stop piano-vivo-cadena" ]'

# 5) Con terminal (pseudoterminal de «script»): la pantalla de inicio se ve y después se abre la interfaz
if command -v script >/dev/null && [ "$(uname)" = Linux ]; then
    : > "$SHIM_LOG"; rm -f "$SHIM_ESTADO"
    # Del tamaño del monitor (1080p con Terminus 16x32: 120x33); «script» crea su terminal de 80x24
    TERM=xterm script -qec "stty rows 33 cols 120; bash '$PT'" "$T/pty.log" > /dev/null 2>&1 < /dev/null; RC=$?
    comprobar "5: en una terminal, la pantalla de inicio (estilo DOS) se dibuja" \
        'grep -q "R A S P B E R R Y" "$T/pty.log" && grep -q "Listo para tocar" "$T/pty.log" || { tail -c 600 "$T/pty.log"; false; }'
    comprobar "5: y deja paso a la interfaz" '[ "$RC" -eq 0 ] && grep -qx interfaz "$SHIM_LOG" && ! grep -q "Cargando el piano" "$T/pty.log"'
    comprobar "5: la pantalla de inicio no queda viva" '! pgrep -f "pantalla_inicio.py --progreso $XDG_RUNTIME_DIR" >/dev/null'
    PIANO_SIN_PANTALLA_INICIO=1 TERM=xterm script -qec "bash '$PT'" "$T/pty2.log" > /dev/null 2>&1 < /dev/null
    comprobar "5: con PIANO_SIN_PANTALLA_INICIO=1, el texto de siempre" \
        'grep -q "Cargando el piano" "$T/pty2.log" && ! grep -q "R A S P B E R R Y" "$T/pty2.log"'
else
    echo "(omitido 5: sin «script» o fuera de Linux)"
fi

echo
[ "$FALLOS" -eq 0 ] && echo "TODAS LAS PRUEBAS PASAN" || { echo "$FALLOS FALLO(S)"; exit 1; }
