#!/bin/bash
# Detiene de inmediato el audio del proyecto y verifica que no quede nada:
#  - reproducciones de prueba de escuchar-midi.sh (script, aplaymidi, pw-record/pw-top, unidades piano-prueba*,
#    y sus anclas piano-ancla-prueba*, siempre después de las unidades)
#  - el piano en vivo (unidades piano-vivo-cadena / piano-vivo / piano-vivo-fx y el ancla piano-ancla-vivo del modo
#    silencio), salvo con --solo-pruebas
#  - ajustes temporales de PipeWire y, si quedó cambiado por un piano interrumpido, el gobernador de CPU
# Uso: detener-audio.sh [--solo-pruebas]        (código 0 si todo quedó detenido)
set -uo pipefail

SOLO_PRUEBAS=0
[ "${1:-}" = "--solo-pruebas" ] && SOLO_PRUEBAS=1
RUNDIR="${XDG_RUNTIME_DIR:-/tmp}"
PIDF="$RUNDIR/escuchar-midi.pid"
MARCA_GOB="$RUNDIR/piano-vivo.gobernador"
MARCA_AFIN="$RUNDIR/piano-vivo.afinidad-pipewire"
GOBERNADOR=/sys/devices/system/cpu/cpufreq/policy0/scaling_governor

if [ -f "$PIDF" ]; then
    pid="$(cat "$PIDF" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
        kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDF"
fi

# Patrones anclados al inicio de la línea de órdenes: no coinciden con shells que solo los mencionan.
pkill -f '^aplaymidi -p 14:0 ' 2>/dev/null || true
pkill -f '^pw-top -b$' 2>/dev/null || true
pkill -f '^pw-record .*piano-grabacion' 2>/dev/null || true

parar_unidades() {
    for u in $(systemctl --user list-units "$1" --all --no-legend --plain 2>/dev/null | awk '{print $1}'); do
        systemctl --user stop "$u" 2>/dev/null || true
    done
}
parar_unidades 'piano-prueba*'
# Anclas (grabadores nulos de lib-pw.sh) de scripts que no pudieron limpiar: DESPUÉS de sus clientes (ver redirigir).
pkill -f '^pw-record .*piano-ancla-prueba' 2>/dev/null || true
if [ "$SOLO_PRUEBAS" = 0 ]; then
    parar_unidades 'piano-vivo-cadena*'     # su limpieza detiene sfizz/reverb y restaura el gobernador
    # piano-en-vivo.sh lanzado a mano (fuera de la unidad): SIGTERM para que haga su propia limpieza
    for pid in $(pgrep -f '^/bin/bash \S*piano-en-vivo\.sh'); do
        kill -TERM "$pid" 2>/dev/null
        for _ in $(seq 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    done
    parar_unidades 'piano-vivo*'
    pkill -f '^pw-record .*piano-ancla-vivo' 2>/dev/null || true
fi

pw-metadata -n settings 0 clock.force-quantum 0 >/dev/null 2>&1 || true
pw-metadata -n settings 0 clock.force-rate 0 >/dev/null 2>&1 || true

# Gobernador cambiado por un piano que no pudo limpiar (p. ej. kill -9): se restaura si ya no hay piano.
if [ -f "$MARCA_GOB" ] && ! systemctl --user is-active --quiet piano-vivo-cadena; then
    orig="$(cat "$MARCA_GOB")"
    [ -n "$orig" ] && echo "$orig" | sudo -n tee "$GOBERNADOR" >/dev/null 2>&1
    rm -f "$MARCA_GOB"
fi
# Igual con los núcleos de PipeWire (solo si sigue siendo el mismo proceso: si PipeWire se reinició, ya está bien).
if [ -f "$MARCA_AFIN" ] && ! systemctl --user is-active --quiet piano-vivo-cadena; then
    read -r pid orig < "$MARCA_AFIN"
    if [ -n "${pid:-}" ] && [ -n "${orig:-}" ] && [ "$(cat "/proc/$pid/comm" 2>/dev/null)" = pipewire ]; then
        taskset -a -p -c "$orig" "$pid" >/dev/null 2>&1
    fi
    rm -f "$MARCA_AFIN"
fi

sleep 0.3
patron='^(aplaymidi -p 14:0 |jalv -x -n piano-prueba|\S*sfizz_jack --client_name piano-prueba|pw-record .*piano-ancla-prueba'
[ "$SOLO_PRUEBAS" = 0 ] && patron="$patron|jalv -x -n piano-vivo|\S*sfizz_jack --client_name piano-vivo|/bin/bash \S*piano-en-vivo\.sh|pw-record .*piano-ancla-vivo"
restos="$(pgrep -af "$patron)" || true)"
if [ -n "$restos" ]; then
    echo "ERROR: siguen procesos de audio:" >&2
    echo "$restos" >&2
    exit 1
fi
if [ "$SOLO_PRUEBAS" = 1 ]; then
    echo "Audio de prueba detenido."
else
    echo "Audio detenido (sin pruebas ni piano en vivo)."
fi
