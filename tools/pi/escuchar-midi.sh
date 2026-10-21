#!/bin/bash
# Prueba de escucha / capacidad: reproduce archivos MIDI a través del piano LV2 (jalv + PipeWire-JACK)
# —opcionalmente seguido de un efecto LV2 (p. ej. reverb)— hacia la tarjeta de sonido elegida (salidas_audio.py,
# fase 10), y mide por archivo
# la carga DSP (B/Q) y los xruns de cada nodo con pw-top. Opcionalmente graba la salida en float 32
# y mide sus niveles (pico/RMS en dBFS, muestras >= 0 dBFS) para detectar saturación.
# Los ajustes de PipeWire (frecuencia y quantum forzados) son TEMPORALES y se revierten al salir.
# Solo puede haber una instancia: si hay otra reproducción viva, se detiene antes de empezar.
#
# Uso: escuchar-midi.sh [-s] [-q QUANTUM] [-r DIR_WAV] archivo.mid [archivo2.mid ...]
#   -s          modo silencio: se procesa en tiempo real pero la cadena NO se conecta a ninguna tarjeta
#   -q QUANTUM  tamaño de bloque de PipeWire (por defecto 256 = 5,8 ms a 44,1 kHz)
#   -r DIR      graba la salida final de la cadena (f32) en DIR/<pieza>.wav y la analiza
#   -x          termina (y limpia) cuando se cierra la entrada estándar: útil por SSH, donde cortar
#               la conexión no envía ninguna señal. Uso: sleep 86400 | ssh pi 'escuchar-midi.sh -x ...'
# Variables:
#   PIANO_URI, JALV_ARGS     plugin de piano y opciones de jalv (p. ej. "-c polyphony=1")
#   PIANO_CMD                en lugar de jalv, un cliente JACK propio; {CLIENTE} se sustituye por el
#                            nombre de cliente. P. ej. "sfizz_jack --client_name {CLIENTE} archivo.sfz"
#   PIANO_LISTO              texto (regex) que PIANO_CMD imprime al estar listo (p. ej. "Instrument loaded")
#   EFECTO_URI, EFECTO_ARGS  efecto estéreo opcional tras el piano (p. ej. mda Ambience)
set -euo pipefail

URI="${PIANO_URI:-https://socalabs.com/piano/}"
JALV_ARGS="${JALV_ARGS:-}"
PIANO_CMD="${PIANO_CMD:-}"
PIANO_LISTO="${PIANO_LISTO:-}"
EFECTO_URI="${EFECTO_URI:-}"
EFECTO_ARGS="${EFECTO_ARGS:-}"
RATE=44100
QUANTUM=256
SILENCIO=0
GRABAR_DIR=""
VIGILAR_STDIN=0
CLIENTE=piano-prueba
CLIENTE_FX=piano-prueba-fx
GRABADOR=piano-grabacion
MIDI_ORIGEN='Midi-Bridge:Midi Through:(capture_0) Midi Through Port-0'
MIDI_SEQ=14:0                     # ALSA seq: Midi Through Port-0
COLA_S=4                          # segundos de resonancia tras cada archivo
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${LOG_DIR:-$HOME/piano/logs}"
RUNDIR="${XDG_RUNTIME_DIR:-/tmp}"

while getopts "sq:r:x" opt; do
    case $opt in
        s) SILENCIO=1 ;;
        q) QUANTUM=$OPTARG ;;
        r) GRABAR_DIR=$OPTARG ;;
        x) VIGILAR_STDIN=1 ;;
        *) exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[ $# -ge 1 ] || { echo "uso: $0 [-s] [-x] [-q QUANTUM] [-r DIR_WAV] archivo.mid ..." >&2; exit 2; }
[[ "$QUANTUM" =~ ^[0-9]+$ ]] && [ "$QUANTUM" -ge 32 ] && [ "$QUANTUM" -le 2048 ] \
    || { echo "quantum inválido: $QUANTUM (32..2048)" >&2; exit 2; }
for f in "$@"; do [ -r "$f" ] || { echo "no se puede leer: $f" >&2; exit 2; }; done
[ -z "$GRABAR_DIR" ] || mkdir -p "$GRABAR_DIR"

# --- Instancia única: detener cualquier reproducción anterior (incluidos procesos huérfanos).
exec 9>"$RUNDIR/escuchar-midi.lock"
if ! flock -n 9; then
    echo "== Hay otra reproducción en curso: se detiene antes de empezar"
fi
"$DIR/detener-audio.sh" >/dev/null || { echo "ERROR: no se pudo detener la reproducción anterior" >&2; exit 1; }
flock -w 10 9 || { echo "ERROR: no se pudo obtener el bloqueo de reproducción" >&2; exit 1; }
echo $$ > "$RUNDIR/escuchar-midi.pid"

mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
PWTOP_PID=""
APLAY_PID=""
REC_PID=""
VIGIA_PID=""
UNIDADES=()

# shellcheck source=lib-pw.sh
source "$DIR/lib-pw.sh"


limpiar() {
    if [ -n "$VIGIA_PID" ]; then pkill -P "$VIGIA_PID" 2>/dev/null; kill "$VIGIA_PID" 2>/dev/null; fi || true
    [ -n "$APLAY_PID" ] && kill "$APLAY_PID" 2>/dev/null || true
    [ -n "$REC_PID" ] && kill -INT "$REC_PID" 2>/dev/null || true
    [ -n "$PWTOP_PID" ] && kill "$PWTOP_PID" 2>/dev/null || true
    for u in "${UNIDADES[@]}"; do systemctl --user stop "$u" 2>/dev/null || true; done
    detener_ancla   # después de los clientes: mientras suenan, sus salidas no deben quedar sin enlaces
    # La tarjeta queda libre: se suspende ya (WirePlumber 0.4.13 cae si se desenchufa en los 5 s que él espera).
    [ -z "${SINK:-}" ] || echo "== Salida al terminar: $(python3 "$DIR/salidas_audio.py" suspender "$SINK" 2>/dev/null || true)" || true
    pw-metadata -n settings 0 clock.force-quantum 0 >/dev/null || true
    pw-metadata -n settings 0 clock.force-rate 0 >/dev/null || true
    rm -f "$RUNDIR/escuchar-midi.pid"
}
trap limpiar EXIT
trap 'exit 130' INT TERM HUP

# Vigilante de la sesión: al llegar EOF por stdin (SSH cerrado) se termina el script y se limpia.
# - Se duplica stdin explícitamente porque bash redirige a /dev/null la entrada de los trabajos en segundo plano.
# - Al cortarse SSH, stdout/stderr también quedan rotos: el vigilante mata PRIMERO y registra en archivo,
#   y el script ignora SIGPIPE para que ninguna escritura interrumpa la limpieza.
if [ "$VIGILAR_STDIN" = 1 ]; then
    trap '' PIPE
    VIGIA_LOG="$LOG_DIR/escuchar-midi-vigia.log"
    exec 3<&0
    ( cat <&3 >/dev/null 2>&1
      kill -TERM $$ 2>/dev/null
      echo "$(date '+%F %T') entrada cerrada (sesión terminada): reproducción $$ detenida" >> "$VIGIA_LOG" 2>/dev/null
    ) </dev/null >/dev/null 2>&1 &
    VIGIA_PID=$!
    exec 3<&-
fi


# iniciar_grabacion WAV: graba en f32 la salida final de la cadena (sin enlaces automáticos)
N_GRABACION=0
iniciar_grabacion() {
    # Nombre de nodo único por grabación: el nodo de la pieza anterior puede seguir cerrándose y,
    # con el mismo nombre, pw-link podría elegir el equivocado.
    N_GRABACION=$((N_GRABACION + 1))
    local nodo="$GRABADOR-$$-$N_GRABACION"
    pw-record --target 0 -P "{ node.name = \"$nodo\" }" --rate "$RATE" --channels 2 --format f32 "$1" &
    REC_PID=$!
    local g=""
    for _ in $(seq 80); do
        g="$(puertos "$nodo" || true)"
        [ "$(grep -c '^in audio' <<<"$g")" -ge 2 ] && break
        sleep 0.25
    done
    mapfile -t REC_IN < <(awk '$1=="in" && $2=="audio"' <<<"$g" | cut -d' ' -f3-)
    [ "${#REC_IN[@]}" -ge 2 ] || { echo "ERROR: pw-record ($nodo) no publicó sus entradas en 20 s" >&2; exit 1; }
    enlazar "${FINALES[0]}" "${REC_IN[0]}"
    enlazar "${FINALES[1]:-${FINALES[0]}}" "${REC_IN[1]}"
}

detener_grabacion() {
    [ -n "$REC_PID" ] || return 0
    kill -INT "$REC_PID" 2>/dev/null || true     # SIGINT: pw-record cierra la cabecera WAV
    wait "$REC_PID" 2>/dev/null || true
    REC_PID=""
}

# Tarjeta (fase 10): la elegida en las preferencias del piano si está; si no, otra (USB primero). En silencio, ninguna.
SINK=""
if [ "$SILENCIO" = 0 ]; then
    ELEGIDA="$(python3 "$DIR/salidas_audio.py" elegir)" || { echo "ERROR: no hay ninguna salida de audio" >&2; exit 1; }
    IFS=$'\t' read -r SINK RATE _ <<<"$ELEGIDA"
fi

echo "== Ajuste temporal de PipeWire: ${RATE} Hz, quantum ${QUANTUM} ($(awk -v q="$QUANTUM" -v r="$RATE" 'BEGIN{printf "%.1f", 1000*q/r}') ms)"
pw-metadata -n settings 0 clock.force-rate "$RATE" >/dev/null
pw-metadata -n settings 0 clock.force-quantum "$QUANTUM" >/dev/null

if [ -n "$PIANO_CMD" ]; then
    iniciar_cliente "$CLIENTE" "${PIANO_CMD//\{CLIENTE\}/$CLIENTE}" '^in midi' "$PIANO_LISTO"
else
    iniciar_cliente "$CLIENTE" "jalv -x -n $CLIENTE $JALV_ARGS '$URI'" '^in midi'
fi
MIDI_IN="$(awk '$1=="in" && $2=="midi"' <<<"$P" | head -1 | cut -d' ' -f3-)"
mapfile -t SALIDAS < <(awk '$1=="out" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
echo "   MIDI in : $MIDI_IN"
echo "   Audio   : ${SALIDAS[*]}"

NODOS=("$CLIENTE")
FINALES=("${SALIDAS[@]}")          # salidas que van (o irían) a la tarjeta
if [ -n "$EFECTO_URI" ]; then
    iniciar_cliente "$CLIENTE_FX" "jalv -x -n $CLIENTE_FX $EFECTO_ARGS '$EFECTO_URI'" '^in audio'
    mapfile -t FX_IN < <(awk '$1=="in" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
    mapfile -t FX_OUT < <(awk '$1=="out" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
    echo "   Efecto  : ${FX_IN[*]} -> ${FX_OUT[*]}"
    NODOS+=("$CLIENTE_FX")
fi

enlazar "$MIDI_ORIGEN" "$MIDI_IN"
sleep 1   # margen para enlaces automáticos de WirePlumber
# Conectar antes de cortar: ninguna salida queda sin destino con el cliente sonando (ver redirigir en lib-pw.sh).
if [ -n "$EFECTO_URI" ]; then
    redirigir_par "${SALIDAS[0]}" "${SALIDAS[1]:-}" "${FX_IN[0]}" "${FX_IN[1]:-}"
    FINALES=("${FX_OUT[@]}")
fi
if [ "$SILENCIO" = 1 ]; then
    # Solo a un grabador nulo (ancla): las grabaciones de cada pieza se enlazan y desenlazan sin dejarla sin enlaces.
    iniciar_ancla "piano-ancla-prueba-$$" "${FINALES[0]}" "${FINALES[1]:-}"
    echo "   Modo silencio: la cadena no está conectada a ninguna tarjeta (verificado; solo va a un grabador nulo)"
else
    enlazar "${FINALES[0]}" "$SINK:playback_FL"
    enlazar "${FINALES[1]:-${FINALES[0]}}" "$SINK:playback_FR"
fi

FALLOS=0
for f in "$@"; do
    nombre="$(basename "$f" .mid)"
    log="$LOG_DIR/pwtop-$STAMP-$nombre.log"
    echo "== ▶ $nombre"
    [ -z "$GRABAR_DIR" ] || iniciar_grabacion "$GRABAR_DIR/$nombre.wav"
    pw-top -b > "$log" 2>&1 &
    PWTOP_PID=$!
    inicio=$(date +%s)
    aplaymidi -p "$MIDI_SEQ" "$f" &
    APLAY_PID=$!
    wait "$APLAY_PID"
    APLAY_PID=""
    sleep "$COLA_S"
    kill "$PWTOP_PID" 2>/dev/null || true
    wait "$PWTOP_PID" 2>/dev/null || true
    PWTOP_PID=""
    detener_grabacion
    for u in "${UNIDADES[@]}"; do
        systemctl --user is-active --quiet "$u" || { echo "ERROR: jalv ($u) se detuvo durante $nombre" >&2; exit 1; }
    done
    echo "   $(( $(date +%s) - inicio )) s"
    for n in "${NODOS[@]}"; do
        r="$(resumir_pwtop "$n" "$log")"
        if [ "$r" = "SIN_DATOS" ]; then
            echo "   ERROR: pw-top no registró actividad de $n (¿nodo sin planificar?)" >&2
            FALLOS=$((FALLOS + 1))
        else
            printf "   %-16s %s\n" "$n" "$r"
        fi
    done
    if [ -n "$GRABAR_DIR" ]; then
        python3 "$DIR/analizar_wav.py" "$GRABAR_DIR/$nombre.wav" | sed 's/^/   nivel: /'
    fi
done
echo "   registros: $LOG_DIR/pwtop-$STAMP-*.log"
[ "$FALLOS" -eq 0 ]
