#!/bin/bash
# Piano en vivo: instrumento del catálogo (sfizz) + reverb de sala (mda Ambience) -> la tarjeta de sonido elegida
# (F10; fase 10: la de las preferencias si está conectada, si no otra USB, con aviso; ver salidas_audio.py).
# Las entradas MIDI (teclado de computador vía teclado_piano.py y teclados MIDI USB) pasan por el
# enrutador (enrutador_midi.py): selección de dispositivos en caliente, transposición, curva de fuerza,
# contador de cortes, preferencias y cambio de instrumento en caliente (órdenes a sfizz por su FIFO).
# Queda en primer plano hasta Ctrl+C / SIGTERM y al salir lo limpia todo.
# Cuando está listo para tocar crea $XDG_RUNTIME_DIR/piano-vivo.listo.
#
# Uso: piano-en-vivo.sh [-s] [-q QUANTUM] [-p]
#   -s          silencio: la reverb no se conecta a ninguna tarjeta, solo al ancla (pruebas)
#   -q QUANTUM  bloque de PipeWire (por defecto, el de las preferencias; si no hay, 512 = 11,6 ms)
#   -p          rendimiento durante la sesión (se restaura al salir): gobernador de CPU "performance" y el
#               proceso de PipeWire fijado a los núcleos de audio (NUCLEOS), lejos de la interfaz y del dibujo de
#               la consola (núcleos 0-1). PIANO_FIJAR_PIPEWIRE=0 desactiva lo segundo (comparaciones).
# Variables: INSTRUMENTO (id del catálogo; por defecto, el de las preferencias), NUCLEOS (2,3),
#            REVERB_MIX (por defecto, el de las preferencias), PIANO_PREFERENCIAS (~/.config/piano/preferencias.json),
#            PIANO_CATALOGO (instrumentos.json de esta carpeta), PIANO_INSTRUMENTOS (~/piano/instrumentos)
# Para la interfaz publica $XDG_RUNTIME_DIR/piano-vivo.estado (FIFOs de órdenes y estado del enrutador).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
RUNDIR="${XDG_RUNTIME_DIR:-/tmp}"
SFIZZ="${SFIZZ:-$HOME/piano/bin/sfizz_jack}"
NUCLEOS="${NUCLEOS:-2,3}"
PREFS="${PIANO_PREFERENCIAS:-$HOME/.config/piano/preferencias.json}"
CATALOGO="${PIANO_CATALOGO:-$DIR/instrumentos.json}"
BASE_INSTRUMENTOS="${PIANO_INSTRUMENTOS:-$HOME/piano/instrumentos}"
ENRUTADOR="$DIR/enrutador_midi.py"
pref() { python3 "$ENRUTADOR" --preferencias "$PREFS" --pref "$1"; }
# Reverb de sala ligera; output=0.35 -> -6 dB de margen (fórmula de mda: 10^(2*output-1)).
REVERB_URI="http://drobilla.net/plugins/mda/Ambience"
REVERB_MIX="${REVERB_MIX:-$(pref reverb)}"
RATE=44100
QUANTUM=""
SILENCIO=0
RENDIMIENTO=0
CLIENTE=piano-vivo
CLIENTE_FX=piano-vivo-fx
UNIDAD_MIDI=piano-vivo-midi
GOBERNADOR=/sys/devices/system/cpu/cpufreq/policy0/scaling_governor
MARCA_GOB="$RUNDIR/piano-vivo.gobernador"
MARCA_AFIN="$RUNDIR/piano-vivo.afinidad-pipewire"   # "<pid> <núcleos originales>" de PipeWire
LISTO="$RUNDIR/piano-vivo.listo"
ESTADO="$RUNDIR/piano-vivo.estado"
CTL_SFIZZ="$RUNDIR/piano-vivo.ctl"          # FIFO de órdenes de sfizz_jack (load_instrument, set_cc, set_volume)
CTL_REVERB="$RUNDIR/piano-vivo-fx.ctl"      # FIFO de órdenes de jalv (reverb), p. ej. "mix = 0.5"
CTL_MIDI="$RUNDIR/piano-enrutador.ctl"       # FIFO de órdenes del enrutador
ESTADO_MIDI="$RUNDIR/piano-enrutador.json"   # estado del enrutador (fuentes, notas, ajustes, cortes)
PROGRESO="$RUNDIR/piano-vivo.progreso"       # etapas de la carga, para la pantalla de inicio (pantalla_inicio.py)
progreso() { printf '%s\t%s\n' "$(date +%s.%N)" "$(IFS=$'\t'; echo "$*")" >> "$PROGRESO" 2>/dev/null || true; }

while getopts "sq:p" opt; do
    case $opt in
        s) SILENCIO=1 ;;
        q) QUANTUM=$OPTARG ;;
        p) RENDIMIENTO=1 ;;
        *) exit 2 ;;
    esac
done
[ -n "$QUANTUM" ] || QUANTUM="$(pref latencia)"
[[ "$QUANTUM" =~ ^[0-9]+$ ]] && [ "$QUANTUM" -ge 32 ] && [ "$QUANTUM" -le 2048 ] \
    || { echo "quantum inválido: $QUANTUM (32..2048)" >&2; exit 2; }
[[ "$REVERB_MIX" =~ ^[01](\.[0-9]+)?$ ]] || { echo "reverb inválida: $REVERB_MIX" >&2; exit 2; }
REVERB_ARGS="-c mix=$REVERB_MIX -c size=0.6 -c hf_damp=0.6 -c output=0.35"
# Instrumento inicial: el pedido (o el de las preferencias) si está descargado; si no, el primero disponible.
ELECCION="$(python3 "$DIR/catalogo_instrumentos.py" --catalogo "$CATALOGO" --base "$BASE_INSTRUMENTOS" \
            elegir "${INSTRUMENTO:-$(pref instrumento)}")" || { echo "ERROR: no hay instrumentos disponibles" >&2; exit 1; }
IFS=$'\t' read -r INST_ID SFZ VOCES <<<"$ELECCION"
[ -r "$SFZ" ] || { echo "ERROR: no se encuentra el instrumento $SFZ" >&2; exit 1; }
[ -x "$SFIZZ" ] || { echo "ERROR: no se encuentra sfizz_jack en $SFIZZ" >&2; exit 1; }

exec 8>"$RUNDIR/piano-vivo.lock"
flock -n 8 || { echo "El piano ya está en marcha (otra instancia de piano-en-vivo.sh)." >&2; exit 3; }

UNIDADES=()
GOB_ORIGINAL=""
AFIN_ORIGINAL=""
PW_PID=""
# shellcheck source=lib-pw.sh
source "$DIR/lib-pw.sh"

salida_activa() {   # node.name de la tarjeta en uso según el enrutador (F10 puede haberla cambiado); si no, la inicial
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["salida"]["activa"]["nombre"])' "$ESTADO_MIDI" \
        2>/dev/null || echo "${SINK:-}"
}

limpiar() {
    local activa
    rm -f "$LISTO" "$ESTADO" "$CTL_REVERB"
    activa="$(salida_activa)"   # antes de parar el enrutador: al salir borra su estado
    # El enrutador primero: al salir envía "pánico" (no deja notas colgadas) y borra su estado.
    for u in $(printf '%s\n' "${UNIDADES[@]}" | tac); do systemctl --user stop "$u" 2>/dev/null || true; done
    detener_ancla   # después de los clientes: mientras suenan, sus salidas no deben quedar sin enlaces
    # La tarjeta queda libre: se suspende ya. WirePlumber 0.4.13 lo hace a los 5 s y cae (SIGSEGV) si en ese rato
    # desaparece (se desenchufa al cerrar el piano). Ver suspender_si_libre en salidas_audio.py.
    [ -z "$activa" ] || echo "== Salida al cerrar: $(python3 "$DIR/salidas_audio.py" suspender "$activa" 2>/dev/null || true)"
    rm -f "$CTL_MIDI" "$ESTADO_MIDI" "$CTL_SFIZZ" "$PROGRESO"
    pw-metadata -n settings 0 clock.force-quantum 0 >/dev/null 2>&1 || true
    pw-metadata -n settings 0 clock.force-rate 0 >/dev/null 2>&1 || true
    if [ -n "$GOB_ORIGINAL" ]; then
        echo "$GOB_ORIGINAL" | sudo -n tee "$GOBERNADOR" >/dev/null 2>&1 || true
        rm -f "$MARCA_GOB"
        echo "== Gobernador de CPU restaurado: $(cat "$GOBERNADOR")"
    fi
    if [ -n "$AFIN_ORIGINAL" ]; then
        taskset -a -p -c "$AFIN_ORIGINAL" "$PW_PID" >/dev/null 2>&1 || true
        rm -f "$MARCA_AFIN"
        echo "== PipeWire restaurado a los núcleos $AFIN_ORIGINAL"
    fi
    echo "== Piano detenido"
}
trap limpiar EXIT
trap 'exit 0' INT TERM HUP

# Las reproducciones de prueba y este piano comparten la tarjeta de sonido y la CPU: no deben convivir.
"$DIR/detener-audio.sh" --solo-pruebas >/dev/null || true

# Salida de audio (fase 10): la elegida (preferencias o PIANO_SALIDA) si está conectada; si no, otra (USB primero)
# con aviso. Frecuencia de la sesión: 44,1 kHz si la tarjeta la admite; si no, 48 kHz. En silencio, ninguna.
SINK=""; AVISO_SALIDA=""
if [ "$SILENCIO" = 0 ]; then
    ELEGIDA="$(python3 "$DIR/salidas_audio.py" elegir --preferencias "$PREFS")" \
        || { echo "ERROR: no hay ninguna salida de audio: conecta una tarjeta de sonido" >&2; exit 1; }
    IFS=$'\t' read -r SINK RATE AVISO_SALIDA <<<"$ELEGIDA"
    echo "== Salida de audio: $SINK ($RATE Hz)${AVISO_SALIDA:+. AVISO: $AVISO_SALIDA}"
fi
progreso salida "$SINK" "$RATE"

if [ "$RENDIMIENTO" = 1 ]; then
    GOB_ORIGINAL="$(cat "$GOBERNADOR")"
    # Marca para detener-audio.sh: si este script muriera sin limpiar (kill -9), allí se restaura.
    [ -f "$MARCA_GOB" ] && GOB_ORIGINAL="$(cat "$MARCA_GOB")" || echo "$GOB_ORIGINAL" > "$MARCA_GOB"
    echo performance | sudo -n tee "$GOBERNADOR" >/dev/null \
        || { echo "ERROR: no se pudo poner el gobernador en performance" >&2; GOB_ORIGINAL=""; exit 1; }
    echo "== Gobernador de CPU: performance (antes: $GOB_ORIGINAL; se restaura al salir)"
    # El dibujo de la consola HDMI (letra grande, sin aceleración) lo hace el núcleo del sistema en los núcleos de
    # la interfaz; con PipeWire allí, el reloj de audio llegaba tarde (cortes del grafo). Marca para detener-audio.sh.
    PW_PID="$(pidof -s pipewire || true)"
    if [ -n "$PW_PID" ] && [ "${PIANO_FIJAR_PIPEWIRE:-1}" = 1 ]; then
        if [ -f "$MARCA_AFIN" ] && [ "$(cut -d' ' -f1 "$MARCA_AFIN")" = "$PW_PID" ]; then
            AFIN_ORIGINAL="$(cut -d' ' -f2 "$MARCA_AFIN")"
        else
            AFIN_ORIGINAL="$(taskset -p -c "$PW_PID" | awk -F': ' '{print $2}')"
            echo "$PW_PID $AFIN_ORIGINAL" > "$MARCA_AFIN"
        fi
        taskset -a -p -c "$NUCLEOS" "$PW_PID" >/dev/null \
            || { echo "ERROR: no se pudo fijar PipeWire a los núcleos $NUCLEOS" >&2; AFIN_ORIGINAL=""; exit 1; }
        echo "== PipeWire fijado a los núcleos $NUCLEOS (antes: $AFIN_ORIGINAL; se restaura al salir)"
    fi
fi

echo "== PipeWire: ${RATE} Hz, quantum ${QUANTUM} ($(awk -v q="$QUANTUM" -v r="$RATE" 'BEGIN{printf "%.1f", 1000*q/r}') ms)"
pw-metadata -n settings 0 clock.force-rate "$RATE" >/dev/null
pw-metadata -n settings 0 clock.force-quantum "$QUANTUM" >/dev/null

# Entrada estándar de sfizz: un FIFO (órdenes del enrutador para cambiar de instrumento). Interpolación lineal
# (--sample_quality 1, parche 0002) para todos los instrumentos: es la que evita los cortes en la Pi 3.
rm -f "$CTL_SFIZZ"; mkfifo -m 600 "$CTL_SFIZZ"
progreso sonido "$INST_ID"
iniciar_cliente "$CLIENTE" "taskset -c $NUCLEOS $SFIZZ --client_name $CLIENTE --num_voices $VOCES --preload_size 8192 --sample_quality 1 '$SFZ'" \
    '^in midi' "Instrument loaded" "$CTL_SFIZZ"
MIDI_IN="$(awk '$1=="in" && $2=="midi"' <<<"$P" | head -1 | cut -d' ' -f3-)"
mapfile -t SALIDAS < <(awk '$1=="out" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
rm -f "$CTL_REVERB"; mkfifo -m 600 "$CTL_REVERB"
progreso reverb
iniciar_cliente "$CLIENTE_FX" "taskset -c $NUCLEOS jalv -x -n $CLIENTE_FX $REVERB_ARGS '$REVERB_URI'" '^in audio' "" "$CTL_REVERB"
mapfile -t FX_IN < <(awk '$1=="in" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
mapfile -t FX_OUT < <(awk '$1=="out" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)

sleep 1   # margen para enlaces automáticos de WirePlumber
# Conectar antes de cortar: ninguna salida queda sin destino con el cliente sonando (ver redirigir en lib-pw.sh).
redirigir_par "${SALIDAS[0]}" "${SALIDAS[1]:-}" "${FX_IN[0]}" "${FX_IN[1]:-}"
# La reverb queda SIEMPRE enlazada al ancla (fase 10): aunque se desconecte la tarjeta o se cambie de tarjeta, sus
# salidas nunca se quedan sin enlaces (pipewire-jack 1.2.7 haría caer a jalv). Con sonido, además, a la tarjeta.
iniciar_ancla piano-ancla-vivo "${FX_OUT[0]}" "${FX_OUT[1]:-}"
if [ "$SILENCIO" = 0 ]; then
    mapfile -t SINK_IN < <(pw-link -i | grep -F "$SINK:playback_" \
                           | awk '/_FL$/ {print 0, $0; next} /_FR$/ {print 1, $0; next} {print 2, $0}' | sort -n | cut -d' ' -f2-)
    [ "${#SINK_IN[@]}" -ge 1 ] || { echo "ERROR: la salida $SINK no tiene puertos de reproducción" >&2; exit 1; }
    enlazar "${FX_OUT[0]}" "${SINK_IN[0]}"
    enlazar "${FX_OUT[1]:-${FX_OUT[0]}}" "${SINK_IN[1]:-${SINK_IN[0]}}"
fi
# El enrutador cambia de tarjeta en caliente (F10), recuerda el volumen de cada una y sigue sus desconexiones.
ARGS_SALIDA=()
[ -z "$SINK" ] || ARGS_SALIDA=(--salida "$SINK" --salida-desde "${FX_OUT[0]}" --salida-desde "${FX_OUT[1]:-${FX_OUT[0]}}"
                               --salida-tasa "$RATE" --salida-aviso "$AVISO_SALIDA")
ENTORNO_PRUEBAS=()   # systemd-run no hereda el entorno: las variables de las pruebas se pasan explícitamente
[ -z "${PIANO_SOLO_SALIDAS:-}" ] || ENTORNO_PRUEBAS=(--setenv=PIANO_SOLO_SALIDAS="$PIANO_SOLO_SALIDAS")

# Enrutador MIDI: única entrada del sintetizador
echo "== Iniciando enrutador MIDI"
progreso enrutador
rm -f "$CTL_MIDI" "$ESTADO_MIDI"
systemctl --user stop "$UNIDAD_MIDI" 2>/dev/null || true
systemctl --user reset-failed "$UNIDAD_MIDI" 2>/dev/null || true
# El enrutador aplica los ajustes del instrumento (voces, controles, ganancia) y los cambios en caliente; lee las
# confirmaciones de sfizz en su registro (desde ahora: nada anterior a esta sesión).
systemd-run --user --quiet --unit="$UNIDAD_MIDI" --collect "${ENTORNO_PRUEBAS[@]}" \
    taskset -c 0,1 python3 -u "$ENRUTADOR" --ordenes "$CTL_MIDI" --estado "$ESTADO_MIDI" --ctl-reverb "$CTL_REVERB" \
    --nodo-xruns "$CLIENTE" --nodo-xruns "$CLIENTE_FX" ${SINK:+--nodo-xruns "$SINK"} --preferencias "$PREFS" \
    "${ARGS_SALIDA[@]}" \
    --ctl-sintetizador "$CTL_SFIZZ" --instrumento-inicial "$INST_ID" \
    --catalogo "$CATALOGO" --base-instrumentos "$BASE_INSTRUMENTOS" \
    --salida-sintetizador "journalctl --user-unit=$CLIENTE -f -o cat --since @$(date +%s)" \
    --registro-pipewire "journalctl --user-unit=pipewire -f -o short-unix --since @$(date +%s)"
UNIDADES+=("$UNIDAD_MIDI")
PATRON_SALIDA_MIDI='^Midi-Bridge:Piano Enrutador:\(capture_[0-9]+\) salida$'
SALIDA_MIDI=""
for _ in $(seq 60); do
    SALIDA_MIDI="$(pw-link -o | grep -m1 -E "$PATRON_SALIDA_MIDI" || true)"
    [ -n "$SALIDA_MIDI" ] && break
    systemctl --user is-active --quiet "$UNIDAD_MIDI" || { echo "ERROR: el enrutador MIDI terminó al arrancar" >&2; journalctl --user-unit="$UNIDAD_MIDI" --no-pager -o cat | tail -15 >&2; exit 1; }
    sleep 0.5
done
[ -n "$SALIDA_MIDI" ] || { echo "ERROR: el enrutador MIDI no apareció en PipeWire en 30 s" >&2; exit 1; }
enlazar "$SALIDA_MIDI" "$MIDI_IN"
echo "   $SALIDA_MIDI -> $MIDI_IN"

printf 'reverb_ctl=%s\nreverb_mix=%s\nrouter_ctl=%s\nrouter_estado=%s\n' \
    "$CTL_REVERB" "$REVERB_MIX" "$CTL_MIDI" "$ESTADO_MIDI" > "$ESTADO"
touch "$LISTO"
progreso listo
echo "== Piano listo: $INST_ID ($SFZ, $VOCES voces, núcleos $NUCLEOS)$([ "$SILENCIO" = 1 ] && echo ' [SILENCIO]')"

# Cada segundo, con una sola lectura de `pw-link -l`: el enlace MIDI (enrutador -> sfizz) y los de la reverb al ancla.
# Si WirePlumber se reinicia (p. ej. tras caer), PipeWire deshace los enlaces de los nodos que él configura (el ancla)
# y recrea el puente MIDI: su puerto falta unos instantes y puede volver con otro número. Se rehacen sin cerrar el
# piano; un intento fallido se repite en la vuelta siguiente. (Los de la tarjeta los rehace el enrutador.)
vigilar_enlaces() {
    local l o i
    l="$(pw-link -l 2>/dev/null || true)"
    if ! grep -qxF "$MIDI_IN" <<<"$(destinos_de "$SALIDA_MIDI" "$l")"; then
        o="$(pw-link -o 2>/dev/null || true)"
        o="$(grep -m1 -E "$PATRON_SALIDA_MIDI" <<<"$o" || true)"
        if [ -n "$o" ] && { pw-link "$o" "$MIDI_IN" 2>/dev/null || grep -qxF "$MIDI_IN" <<<"$(destinos_de "$o")"; }; then
            SALIDA_MIDI="$o"
            echo "== Enlace MIDI restablecido: $o -> $MIDI_IN"
        fi
    fi
    for i in 0 1; do
        o="${FX_OUT[$i]:-${FX_OUT[0]}}"
        grep -qxF "${ANCLA_ENTRADAS[$i]}" <<<"$(destinos_de "$o" "$l")" && continue
        if pw-link "$o" "${ANCLA_ENTRADAS[$i]}" 2>/dev/null; then echo "== Enlace al ancla restablecido: $o"; fi
    done
    return 0
}

while true; do
    for u in "${UNIDADES[@]}"; do
        systemctl --user is-active --quiet "$u" || { echo "ERROR: $u se detuvo" >&2; exit 1; }
    done
    [ -z "$ANCLA_PID" ] || kill -0 "$ANCLA_PID" 2>/dev/null || { echo "ERROR: el ancla terminó" >&2; exit 1; }
    vigilar_enlaces
    sleep 1 8>&- &      # sin heredar el bloqueo: si no, un rearranque inmediato lo encontraría tomado
    wait $!
done
