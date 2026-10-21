#!/bin/bash
# Ejecuta una orden vigilando la temperatura y el bajo voltaje de la Pi; la aborta si pasa 75 °C o hay bajo voltaje.
# Uso: con_vigilancia.sh ORDEN...    (al final informa la temperatura máxima)
"$@" &
P=$!
MAX=0
while kill -0 "$P" 2>/dev/null; do
    t=$(( $(cat /sys/class/thermal/thermal_zone0/temp) / 1000 ))
    [ "$t" -gt "$MAX" ] && MAX=$t
    th=$(( $(vcgencmd get_throttled | cut -d= -f2) ))
    if [ "$t" -ge 75 ] || [ $(( th & 0x1 )) -ne 0 ]; then
        echo "VIGILANCIA: se aborta (temperatura $t °C, throttled $(printf '0x%x' $th))" >&2
        pkill -TERM -P "$P"; kill -TERM "$P"; sleep 2; ~/piano/tools/detener-audio.sh >/dev/null
        exit 99
    fi
    sleep 2
done
wait "$P"; rc=$?
echo "VIGILANCIA: temperatura máxima $MAX °C, throttled $(vcgencmd get_throttled | cut -d= -f2)"
exit $rc
