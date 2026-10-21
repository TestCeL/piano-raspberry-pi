#!/bin/bash
# Lanza el piano en vivo y la interfaz para tocarlo con el teclado de computador conectado a la Pi.
# Pensado para ejecutarse en la consola de la Raspberry (monitor HDMI); también funciona por SSH.
# Mientras carga, en una terminal, muestra la pantalla de inicio (pantalla_inicio.py, fase 11) con el progreso que
# publican este script y piano-en-vivo.sh; sin terminal (o con PIANO_SIN_PANTALLA_INICIO=1), «Cargando el piano...».
# ESC en la interfaz cierra todo; F12 (confirmando) cierra el piano y apaga la Raspberry Pi.
#
# Uso: piano-teclado.sh [--esperar-tarjeta SEGUNDOS] [-p] [-q QUANTUM]   (-p y -q se pasan a piano-en-vivo.sh)
#   --esperar-tarjeta S  antes de arrancar, espera hasta S s a la tarjeta preferida (al encender: arranque automático)
# Variables (pruebas): PIANO_INTERFAZ (orden de la interfaz), PIANO_SIN_PANTALLA_INICIO
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
RUNDIR="${XDG_RUNTIME_DIR:-/tmp}"
UNIDAD=piano-vivo-cadena
LISTO="$RUNDIR/piano-vivo.listo"
PROGRESO="$RUNDIR/piano-vivo.progreso"
PREFS="${PIANO_PREFERENCIAS:-$HOME/.config/piano/preferencias.json}"
CODIGO_APAGAR=10           # lo devuelve la interfaz cuando se confirma F12 (teclado_piano.py)

ESPERA_TARJETA=""
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --esperar-tarjeta) ESPERA_TARJETA="${2:?--esperar-tarjeta necesita los segundos}"; shift 2 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

# progreso ETAPA [DETALLE...]: una línea para la pantalla de inicio (formato en pantalla_inicio.py)
progreso() { printf '%s\t%s\n' "$(date +%s.%N)" "$(IFS=$'\t'; echo "$*")" >> "$PROGRESO" 2>/dev/null || true; }
PANTALLA_PID=""
cerrar_pantalla() {
    [ -n "$PANTALLA_PID" ] || return 0
    kill -TERM "$PANTALLA_PID" 2>/dev/null || true
    wait "$PANTALLA_PID" 2>/dev/null || true
    PANTALLA_PID=""
}
parar() { cerrar_pantalla; systemctl --user stop "$UNIDAD" 2>/dev/null || true; }

if systemctl --user is-active --quiet "$UNIDAD"; then
    echo "El piano ya estaba en marcha: se reinicia."
    parar
fi
systemctl --user reset-failed "$UNIDAD" 2>/dev/null || true
rm -f "$LISTO" "$PROGRESO"
trap parar EXIT

# Pantalla de inicio: solo en una terminal de verdad. Su entrada es la terminal (en segundo plano, bash le daría
# /dev/null) y descarta lo tecleado mientras carga.
if [ -t 0 ] && [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ "${PIANO_SIN_PANTALLA_INICIO:-0}" != 1 ]; then
    taskset -c 0,1 python3 "$DIR/pantalla_inicio.py" --progreso "$PROGRESO" --listo "$LISTO" < /dev/tty &
    PANTALLA_PID=$!
fi
texto() { [ -n "$PANTALLA_PID" ] || printf '%s' "$1"; }   # mensajes sueltos, solo sin pantalla de inicio

# Al encender, la tarjeta aparece unos segundos después de iniciar la sesión: se espera (si no llega, el piano usa
# otra y lo avisa).
if [ -n "$ESPERA_TARJETA" ]; then
    progreso tarjeta esperando
    if res="$(python3 "$DIR/salidas_audio.py" esperar --preferencias "$PREFS" --segundos "$ESPERA_TARJETA" 2>&1)"; then
        progreso tarjeta lista "$(sed -n 's/^ *lista: //p' <<<"$res")"
    else
        progreso tarjeta no "$ESPERA_TARJETA"
    fi
    texto "$res"$'\n'
fi

progreso inicio
systemd-run --user --quiet --unit="$UNIDAD" --collect "$DIR/piano-en-vivo.sh" "${ARGS[@]}"
texto "Cargando el piano"
for _ in $(seq 120); do
    [ -e "$LISTO" ] && break
    systemctl --user is-active --quiet "$UNIDAD" || {
        cerrar_pantalla
        echo; echo "ERROR: el piano no pudo arrancar:" >&2
        journalctl --user-unit="$UNIDAD" --no-pager -o cat | tail -15 >&2
        exit 1
    }
    texto "."
    sleep 0.5
done
[ -e "$LISTO" ] || { cerrar_pantalla; echo; echo "ERROR: el piano no terminó de cargar en 60 s" >&2; exit 1; }
if [ -n "$PANTALLA_PID" ]; then
    # La pantalla de inicio ve el piano listo, muestra el 100 % un instante y termina sola
    for _ in $(seq 30); do kill -0 "$PANTALLA_PID" 2>/dev/null || break; sleep 0.1; done
    cerrar_pantalla
else
    echo " listo."
fi

# Núcleos 0-1: la interfaz no compite con sfizz (fijado a 2-3).
# El título muestra el instrumento que suena (lo publica el enrutador); --titulo es el de reserva y además
# identifica la interfaz real para las comprobaciones de «piano en uso» (ejecutar-pruebas.sh, medir_instrumentos.py).
set +e
if [ -n "${PIANO_INTERFAZ:-}" ]; then
    $PIANO_INTERFAZ
else
    taskset -c 0,1 python3 "$DIR/teclado_piano.py" --titulo "Piano - Raspberry Pi"
fi
rc=$?
set -e
if [ "$rc" -eq "$CODIGO_APAGAR" ]; then
    # F12 confirmado: primero se cierra el piano (suelta y suspende la tarjeta, restaura el gobernador) y luego se apaga
    trap - EXIT
    parar
    echo "Apagando la Raspberry Pi... desenchúfala cuando se apague la luz verde."
    sudo -n systemctl poweroff \
        || { echo "ERROR: no se pudo apagar (hace falta sudo sin contraseña). Apágala con: sudo poweroff" >&2; exit 1; }
    exit 0
fi
exit "$rc"
