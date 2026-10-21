#!/bin/bash
# Prueba de integración EN LA RASPBERRY de la salida de audio (fase 10) con DOS SALIDAS VIRTUALES de PipeWire
# (null sinks: descartan el audio; silencio absoluto). Las tarjetas reales quedan fuera (PIANO_SOLO_SALIDAS).
#  1) la tarjeta preferida no está: el piano arranca con otra y lo avisa
#  2) la reverb queda enlazada al ancla y a la tarjeta; el volumen de la primera vez se limita al 40 %
#  3) cambio en caliente (orden «salida», como F10): la nueva enlazada, la anterior soltada y suspendida enseguida,
#     el ancla intacta, la elección guardada en las preferencias
#  4) el volumen de cada tarjeta se recuerda
#  5) desconectar la tarjeta en uso no tumba nada (sfizz y la reverb siguen vivos, la reverb sigue en el ancla) y se
#     avisa; al reconectarla se vuelve a enlazar sola con su volumen recordado
#  5b) enlaces perdidos (tarjeta, ancla, MIDI): el piano los rehace solo
#  5c) WirePlumber se reinicia con el piano abierto (como tras una caída): el piano sigue y lo rehace todo
#  6) al cerrar, nada queda (ni el ancla), la tarjeta se suspende ya y no hubo ninguna caída (SIGSEGV), tampoco de
#     WirePlumber: la versión 0.4.13 cae si se borra una salida en los 5 s que espera para suspenderla
# Uso: bash test_salidas_integracion.sh    (se niega si el piano está en uso: ejecutar-pruebas.sh lo comprueba)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
RUNDIR="${XDG_RUNTIME_DIR:-/tmp}"
TMP="$(mktemp -d)"
A=piano-prueba-salida-a
B=piano-prueba-salida-b
export PIANO_SOLO_SALIDAS="$A,$B" PIANO_SALIDA="piano-prueba-salida-no-existe"
export PIANO_PREFERENCIAS="$TMP/preferencias.json" INSTRUMENTO=rhodes
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
source "$DIR/lib-pw.sh"
FX_L=piano-vivo-fx:left_out; FX_R=piano-vivo-fx:right_out

dato_nodo() {   # dato_nodo NOMBRE id|state: del nodo con ese node.name (vacío si no existe)
    pw-dump | python3 -c "import json, sys
for o in json.load(sys.stdin):
    if o.get('type') == 'PipeWire:Interface:Node' and ((o.get('info') or {}).get('props') or {}).get('node.name') == sys.argv[1]:
        print(o['id'] if sys.argv[2] == 'id' else o['info'].get('state'))" "$1" "$2"
}
id_de() { dato_nodo "$1" id; }
estado_nodo() { dato_nodo "$1" state; }   # running, idle, suspended...
crear() {   # salida virtual estéreo que persiste aunque termine pw-cli (object.linger)
    pw-cli create-node adapter "{ factory.name=support.null-audio-sink node.name=$1 node.description=\"$2\"
        media.class=Audio/Sink audio.position=[ FL FR ] object.linger=true }" >/dev/null
    for _ in $(seq 40); do [ -n "$(id_de "$1")" ] && pw-link -i | grep -q "^$1:playback_FR" && return 0; sleep 0.25; done
    return 1
}
destruir() { local i; i="$(id_de "$1")"; [ -z "$i" ] || pw-cli destroy "$i" >/dev/null 2>&1; }
estado() {   # estado() EXPRESIÓN_PYTHON sobre e = estado["salida"]
    python3 -c "import json, sys; e = json.load(open('$RUNDIR/piano-enrutador.json'))['salida']; print($1)" 2>/dev/null
}
esperar() {  # esperar CONDICIÓN_BASH [segundos]
    local n; for n in $(seq $(( ${2:-10} * 4 ))); do eval "$1" && return 0; sleep 0.25; done; return 1
}
ms() { echo $(( $(date +%s%N) / 1000000 )); }
esperar_ms() {  # esperar_ms CONDICIÓN_BASH MILISEGUNDOS: plazo de reloj (en esperar, cada vuelta suma lo que tarde)
    local hasta=$(( $(ms) + $2 ))
    while :; do eval "$1" && return 0; [ "$(ms)" -ge "$hasta" ] && return 1; sleep 0.1; done
}
volumen() { wpctl get-volume "$(id_de "$1")" 2>/dev/null | awk '{print $2}'; }
enlazados() { destinos_de "$FX_L"; destinos_de "$FX_R"; }
orden() { escribir_ctl "$RUNDIR/piano-enrutador.ctl" "$1"; }
escribir_ctl() { timeout 3 bash -c 'printf "%s\n" "$2" > "$1"' _ "$1" "$2"; }
pref() { python3 -c "import json; p = json.load(open('$PIANO_PREFERENCIAS')); print($1)" 2>/dev/null; }
registro_enrutador() { journalctl --user-unit=piano-vivo-midi --since "$INICIO" --no-pager -o cat 2>/dev/null; }
salida_midi() { pw-link -o | grep -m1 -E '^Midi-Bridge:Piano Enrutador:\(capture_[0-9]+\) salida$'; }

retirar_salidas() {
    local s i hay=""
    # WirePlumber guarda el volumen de estas salidas por su nombre (restore-stream) y lo reaplica al activarlas:
    # se dejan al 100 % (y se le da tiempo a guardarlo) para que la próxima ejecución empiece igual que esta.
    for s in "$A" "$B"; do i="$(id_de "$s")"; [ -z "$i" ] || { wpctl set-volume "$i" 1.0; hay=1; }; done
    [ -z "$hay" ] || sleep 1.5
    # Borrar una salida que aún no esté suspendida haría caer a WirePlumber 0.4.13 (ver suspender_si_libre en
    # salidas_audio.py): se espera a que lo esté.
    for s in "$A" "$B"; do
        esperar '[ -z "$(id_de "$s")" ] || [ "$(estado_nodo "$s")" = suspended ]' 8
        destruir "$s"
    done
}
fin() {
    [ -n "${PIANO:-}" ] && kill "$PIANO" 2>/dev/null && wait "$PIANO" 2>/dev/null
    "$DIR/detener-audio.sh" >/dev/null 2>&1
    retirar_salidas
    rm -rf "$TMP"
}
trap fin EXIT
"$DIR/detener-audio.sh" >/dev/null 2>&1
destruir "$A"; destruir "$B"
crear "$A" "Salida de prueba A" && crear "$B" "Salida de prueba B" && ok "0: dos salidas virtuales creadas" \
    || { fallo "0: no se pudieron crear las salidas virtuales"; exit 1; }
# WirePlumber recuerda el volumen de cada salida por su nombre (también de estas, entre ejecuciones de la prueba) y
# lo restaura un instante DESPUÉS de crearla: fijar_volumen insiste hasta que el valor se mantiene. Para probar el
# tope de la primera vez, las dos empiezan al 100 % y sin volumen recordado por el piano.
fijar_volumen() {
    local n
    for n in $(seq 10); do
        wpctl set-volume "$(id_de "$1")" "$2"; sleep 0.7
        [ "$(volumen "$1")" = "$(printf '%.2f' "$2")" ] && return 0
    done
    return 1
}
fijar_volumen "$A" 1.0 && fijar_volumen "$B" 1.0 && ok "0: las dos al 100 % (sin el volumen que recordaba WirePlumber)" \
    || fallo "0: no se pudo fijar el 100 %: A $(volumen "$A"), B $(volumen "$B")"
INICIO="$(date '+%Y-%m-%d %H:%M:%S')"

# 1) Arranque sin la preferida
"$DIR/piano-en-vivo.sh" > "$TMP/piano.log" 2>&1 &
PIANO=$!
esperar '[ -e "$RUNDIR/piano-vivo.listo" ] && [ -s "$RUNDIR/piano-enrutador.json" ]' 90 \
    && ok "1: el piano queda listo" || { fallo "1: no quedó listo"; tail -15 "$TMP/piano.log"; exit 1; }
grep -q "AVISO: la salida elegida no está conectada" "$TMP/piano.log" \
    && ok "1: la preferida no está: lo avisa al arrancar" || fallo "1: sin aviso de la preferida"
esperar '[ "$(estado "e[\"activa\"][\"nombre\"]")" = "$A" ]' 5 && ok "1: usa la primera disponible ($A)" \
    || fallo "1: salida activa: $(estado "e['activa']")"
[ "$(estado "'no está conectada' in (e['aviso'] or '')")" = True ] && ok "1: la interfaz recibe el aviso" \
    || fallo "1: aviso publicado: $(estado "e['aviso']")"
grep -q "salida-tasa 44100\|(44100 Hz)" "$TMP/piano.log" && ok "1: a 44,1 kHz (la salida virtual la admite)" \
    || fallo "1: frecuencia: $(grep -m1 'Salida de audio' "$TMP/piano.log")"

# 2) Enlaces y volumen de la primera vez
E="$(enlazados)"
[ "$(grep -c "^piano-ancla-vivo:" <<<"$E")" -eq 2 ] && [ "$(grep -c "^$A:playback_F[LR]$" <<<"$E")" -eq 2 ] \
    && ok "2: la reverb va al ancla y a la tarjeta" || fallo "2: destinos de la reverb: $(tr '\n' ' ' <<<"$E")"
esperar '[ "$(volumen "$A")" = 0.40 ]' 5 && ok "2: primera vez: volumen limitado al 40 % (era 100 %)" \
    || fallo "2: volumen de $A: $(volumen "$A")"
esperar '[ "$(pref "p[\"volumen_salidas\"].get(\"$A\")")" = 0.4 ]' 3 && ok "2: y se recuerda" \
    || fallo "2: volumen recordado: $(pref "p.get('volumen_salidas')")"

# 3) Cambio en caliente
wpctl set-volume "$(id_de "$A")" 0.33
orden "salida $B"
esperar '[ "$(estado "e[\"activa\"][\"nombre\"] + \" \" + e[\"estado\"]")" = "$B lista" ]' 8 \
    && ok "3: cambia a $B en caliente" || fallo "3: estado: $(estado "e['estado'], e['activa']['nombre'], e['error']")"
T_CAMBIO=$(date +%s)
# WirePlumber la suspendería a los 5 s (y cae si en ese rato se desenchufa): el piano lo hace enseguida.
esperar_ms '[ "$(estado_nodo "$A")" = suspended ]' 2000 && registro_enrutador | grep -qF "SALIDA $A: suspendida (quedó libre)" \
    && ok "3: la anterior se suspende enseguida (en menos de 2 s; WirePlumber esperaría 5)" \
    || fallo "3: $A: $(estado_nodo "$A"); registro: $(registro_enrutador | grep -F "SALIDA $A" | tail -2 | tr '\n' ' ')"
# Lo natural tras cambiar con F10: desenchufar la anterior, aquí antes de 3 s. Dentro de los 5 s, WirePlumber 0.4.13
# caería si no estuviera suspendida. Se espera hasta pasado ese plazo y se vuelve a «enchufar».
destruir "$A"
while [ $(( $(date +%s) - T_CAMBIO )) -lt 7 ]; do sleep 0.5; done
N_WP=$(journalctl _UID="$(id -u)" --since "$INICIO" --no-pager -o cat | grep -c '^wireplumber\.service: Main process exited, code=.*status=11/SEGV')
[ "$N_WP" -eq 0 ] && ok "3: desenchufar la anterior justo después del cambio no hace caer a WirePlumber" \
    || fallo "3: WirePlumber cayó al desenchufar la anterior ($N_WP)"
crear "$A" "Salida de prueba A" || fallo "3: no se pudo volver a crear $A"
E="$(enlazados)"
[ "$(grep -c "^$B:playback_F[LR]$" <<<"$E")" -eq 2 ] && ! grep -q "^$A:" <<<"$E" \
    && [ "$(grep -c "^piano-ancla-vivo:" <<<"$E")" -eq 2 ] \
    && ok "3: la nueva enlazada, la anterior soltada, el ancla intacta" || fallo "3: destinos: $(tr '\n' ' ' <<<"$E")"
esperar '[ "$(pref "p[\"salida\"]")" = "$B" ]' 3 && ok "3: la elección se guarda en las preferencias" \
    || fallo "3: preferencia: $(pref "p.get('salida')")"
[ "$(pref "p[\"volumen_salidas\"].get(\"$A\")")" = 0.33 ] && ok "3: al dejarla, se recuerda el volumen de $A (0,33)" \
    || fallo "3: volumen recordado de $A: $(pref "p['volumen_salidas']")"
esperar '[ "$(volumen "$B")" = 0.40 ]' 3 && ok "3: $B, primera vez: 40 %" || fallo "3: volumen de $B: $(volumen "$B")"

# 4) Volumen recordado de la tarjeta activa (se lee cada 5 s)
wpctl set-volume "$(id_de "$B")" 0.55
esperar '[ "$(pref "p[\"volumen_salidas\"].get(\"$B\")")" = 0.55 ]' 8 && ok "4: el volumen de la tarjeta activa se recuerda" \
    || fallo "4: volumen recordado de $B: $(pref "p['volumen_salidas']")"

# 5) Desconexión y reconexión. Justo antes de desconectar, otro volumen (0,70): WirePlumber lo recuerda, el piano no
#    (lo lee cada 5 s). Al reconectar, WirePlumber pondría 0,70: si queda 0,55, lo restauró el piano.
wpctl set-volume "$(id_de "$B")" 0.70
destruir "$B"
RECORDADO_B="$(pref "p[\"volumen_salidas\"].get(\"$B\")")"
esperar '[ "$(estado "e[\"estado\"]")" = desconectada ]' 6 && ok "5: desconectada: lo detecta y lo publica" \
    || fallo "5: estado tras desconectar: $(estado "e['estado']")"
sleep 1
systemctl --user is-active --quiet piano-vivo && systemctl --user is-active --quiet piano-vivo-fx \
    && ok "5: sfizz y la reverb siguen vivos" || fallo "5: se cayó un cliente"
[ "$(enlazados | grep -c "^piano-ancla-vivo:")" -eq 2 ] && ok "5: la reverb sigue enlazada al ancla (nunca sin enlaces)" \
    || fallo "5: destinos: $(enlazados | tr '\n' ' ')"
crear "$B" "Salida de prueba B" || fallo "5: no se pudo volver a crear $B"
esperar '[ "$(estado "e[\"estado\"]")" = lista ] && [ "$(enlazados | grep -c "^$B:playback_F[LR]$")" -eq 2 ]' 8 \
    && ok "5: al reconectarla se vuelve a enlazar sola" || fallo "5: tras reconectar: $(estado "e['estado']") $(enlazados | tr '\n' ' ')"
if [ "$RECORDADO_B" = 0.55 ]; then
    esperar '[ "$(volumen "$B")" = 0.55 ]' 4 \
        && ok "5: con el volumen que recuerda el piano (0,55; WirePlumber habría puesto 0,70)" \
        || fallo "5: volumen tras reconectar: $(volumen "$B") (el piano recordaba 0,55)"
else   # la lectura de cada 5 s coincidió con el cambio a 0,70: el piano también recuerda 0,70 (no se distingue)
    esperar '[ "$(volumen "$B")" = "$RECORDADO_B" ]' 4 && ok "5: con su volumen recordado ($RECORDADO_B)" \
        || fallo "5: volumen tras reconectar: $(volumen "$B") (recordado $RECORDADO_B)"
fi

# 5b) Enlaces perdidos. Se quitan de uno en uno, de modo que la reverb nunca se quede sin ningún enlace
#     (pipewire-jack 1.2.7 la haría caer): primero los de la tarjeta (queda el ancla), luego uno del ancla.
dos_a_b() { [ "$(enlazados | grep -c "^$B:playback_F[LR]$")" -eq 2 ]; }
pw-link -d "$FX_L" "$B:playback_FL"; pw-link -d "$FX_R" "$B:playback_FR"
esperar 'dos_a_b' 5 && registro_enrutador | grep -qF "SALIDA $B: la reverb perdió sus enlaces; se vuelven a enlazar" \
    && ok "5b: la reverb pierde los enlaces a la tarjeta: el piano los rehace" || fallo "5b: destinos: $(enlazados | tr '\n' ' ')"
esperar '[ "$(estado "e[\"estado\"]")" = lista ]' 3 && ok "5b: y la salida vuelve a quedar lista" \
    || fallo "5b: estado $(estado "e['estado'], e['error']")"
pw-link -d "$FX_L" piano-ancla-vivo:input_FL
esperar '[ "$(enlazados | grep -c "^piano-ancla-vivo:")" -eq 2 ]' 4 && grep -q "== Enlace al ancla restablecido" "$TMP/piano.log" \
    && ok "5b: la reverb pierde un enlace al ancla: el piano lo rehace" || fallo "5b: destinos: $(enlazados | tr '\n' ' ')"
SAL_MIDI="$(salida_midi)"
pw-link -d "$SAL_MIDI" piano-vivo:input
esperar 'destinos_de "$SAL_MIDI" | grep -qx "piano-vivo:input"' 4 && grep -q "== Enlace MIDI restablecido" "$TMP/piano.log" \
    && ok "5b: se pierde el enlace MIDI (enrutador -> sfizz): el piano lo rehace" || fallo "5b: MIDI: $(destinos_de "$SAL_MIDI")"

# 5c) WirePlumber se reinicia (como cuando cae y systemd lo levanta): PipeWire deshace los enlaces de los nodos que
#     él configura (la tarjeta y el ancla) y recrea el puente MIDI. El piano no debe cerrarse y debe rehacerlo todo.
systemctl --user restart wireplumber
esperar 'wpctl status >/dev/null 2>&1' 10 || fallo "5c: WirePlumber no volvió"
esperar 'dos_a_b && [ "$(enlazados | grep -c "^piano-ancla-vivo:")" -eq 2 ]' 10 \
    && ok "5c: WirePlumber reiniciado: la reverb vuelve a la tarjeta y al ancla" || fallo "5c: destinos: $(enlazados | tr '\n' ' ')"
esperar 'SAL_MIDI="$(salida_midi)"; [ -n "$SAL_MIDI" ] && destinos_de "$SAL_MIDI" | grep -qx "piano-vivo:input"' 10 \
    && ok "5c: y el enlace MIDI al puente nuevo" || fallo "5c: MIDI: $(salida_midi) -> $(destinos_de "$(salida_midi)")"
esperar '[ "$(estado "e[\"activa\"][\"nombre\"] + \" \" + e[\"estado\"]")" = "$B lista" ]' 5 \
    && kill -0 "$PIANO" 2>/dev/null && systemctl --user is-active --quiet piano-vivo && systemctl --user is-active --quiet piano-vivo-fx \
    && ok "5c: el piano sigue abierto, con sfizz y la reverb vivos y la salida lista" \
    || fallo "5c: piano $(kill -0 "$PIANO" 2>/dev/null && echo vivo || echo CERRADO), salida $(estado "e['estado']"); $(tail -3 "$TMP/piano.log" | tr '\n' ' ')"

# 6) Cierre
kill -TERM "$PIANO"; wait "$PIANO" 2>/dev/null; PIANO=""; CIERRE=$(date +%s)
pgrep -f '^pw-record .*piano-ancla-vivo' >/dev/null && fallo "6: quedó el ancla" || ok "6: al cerrar no queda el ancla"
esperar_ms '[ "$(estado_nodo "$B")" = suspended ]' 1000 && grep -qF "== Salida al cerrar: $B: suspendida" "$TMP/piano.log" \
    && ok "6: al cerrar, la tarjeta queda suspendida (WirePlumber esperaría 5 s)" \
    || fallo "6: $B: $(estado_nodo "$B"); $(grep -F "Salida al cerrar" "$TMP/piano.log")"
retirar_salidas
# Si WirePlumber fuera a caer por las salidas borradas, sería hasta 5 s después de que quedaran libres: se espera.
while [ $(( $(date +%s) - CIERRE )) -lt 7 ]; do sleep 0.5; done
REG="$(journalctl _UID="$(id -u)" --since "$INICIO" --no-pager -o cat)"
N_SEGV=$(grep -c '^piano-vivo\(-fx\)\?\.service: Main process exited, code=.*status=11/SEGV' <<<"$REG")
N_CONEXION=$(journalctl --user-unit=piano-vivo-fx --since "$INICIO" --no-pager -o cat | grep -c 'Failed to connect to audio system')
[ "$N_SEGV" -le "$N_CONEXION" ] && ok "6: ninguna caída (SIGSEGV) en toda la prueba" || fallo "6: caídas: $N_SEGV"
N_WP=$(grep -c '^wireplumber\.service: Main process exited, code=.*status=11/SEGV' <<<"$REG")
[ "$N_WP" -eq 0 ] && ok "6: WirePlumber no cayó en toda la prueba (tampoco al retirar las salidas)" \
    || fallo "6: WirePlumber cayó $N_WP vez/veces"

echo
[ "$FALLOS" -eq 0 ] && echo "TODAS LAS PRUEBAS PASAN" || { echo "$FALLOS FALLO(S)"; exit 1; }
