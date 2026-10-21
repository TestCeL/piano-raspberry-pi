#!/bin/bash
# Prueba de integración EN LA RASPBERRY (modo silencio, no suena nada):
#  1) huérfanos tras perder el script (kill -9, equivalente a cortar SSH) -> detener-audio.sh los limpia
#  2) instancia única: lanzar una segunda reproducción detiene la primera; nunca hay 2 aplaymidi
#  3) al terminar no queda nada vivo y los ajustes temporales de PipeWire quedan revertidos
#  4) la grabación f32 (-r) produce un WAV analizable
#  5) -x: un corte de SSH simulado termina el script y lo limpia todo
#  6) con tarjeta (sin -s) contra una SALIDA VIRTUAL de PipeWire (descarta el audio: tampoco suena nada): la cadena va
#     solo a la tarjeta elegida y, al terminar, la tarjeta queda suspendida (WirePlumber 0.4.13 cae si se desenchufa
#     en los 5 s que él espera para suspenderla)
# Uso: bash test_escuchar_midi_integracion.sh   (requiere el plugin mda-lv2; los MIDI los genera la prueba)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PIANO_URI=http://drobilla.net/plugins/mda/Piano
export JALV_ARGS="-c polyphony=1"
TMP="$(mktemp -d)"
# MIDI de prueba generados aquí (01-escala-dinamicas dura 50 s: sigue sonando mientras se prueban los huérfanos y la
# instancia única). El generador está junto a este script (instalado) o en tools/midi (repositorio).
MIDI="$TMP/midi"
GEN="$DIR/generar_midis_prueba.py"; [ -f "$GEN" ] || GEN="$DIR/../midi/generar_midis_prueba.py"
python3 "$GEN" "$MIDI" >/dev/null || { echo "FALLO - no se pudieron generar los MIDI de prueba"; exit 1; }
LARGO="$MIDI/01-escala-dinamicas.mid"
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
n_aplay() { pgrep -fc '^aplaymidi -p 14:0 ' || true; }
esperar_aplay() { for _ in $(seq 120); do [ "$(n_aplay)" -ge 1 ] && return 0; sleep 0.5; done; return 1; }
limpio() {
    [ "$(n_aplay)" -eq 0 ] && ! pgrep -f '^(jalv -x -n piano-prueba|\S*sfizz_jack --client_name piano-prueba)' >/dev/null \
        && [ -z "$(systemctl --user list-units 'piano-prueba*' --no-legend --plain)" ] \
        && pw-metadata -n settings 0 2>/dev/null | grep -q "clock.force-rate' value:'0'"
}
V=piano-prueba-escucha    # salida virtual de la sección 6
dato_v() {   # dato_v id|state: de la salida virtual (vacío si no existe)
    pw-dump | python3 -c "import json, sys
for o in json.load(sys.stdin):
    if o.get('type') == 'PipeWire:Interface:Node' and ((o.get('info') or {}).get('props') or {}).get('node.name') == sys.argv[1]:
        print(o['id'] if sys.argv[2] == 'id' else o['info'].get('state'))" "$V" "$1"
}
quitar_v() {   # borrarla sin hacer caer a WirePlumber 0.4.13: solo ya suspendida (o si no se suspende en 8 s)
    local i
    for _ in $(seq 32); do [ -z "$(dato_v id)" ] || [ "$(dato_v state)" = suspended ] && break; sleep 0.25; done
    i="$(dato_v id)"; [ -z "$i" ] || pw-cli destroy "$i" >/dev/null 2>&1
}
trap '"$DIR/detener-audio.sh" >/dev/null 2>&1; quitar_v; rm -rf "$TMP"' EXIT

"$DIR/detener-audio.sh" >/dev/null

# 1) Huérfanos
"$DIR/escuchar-midi.sh" -s "$LARGO" > "$TMP/a.log" 2>&1 &
A=$!
esperar_aplay && ok "1: la reproducción arranca" || fallo "1: la reproducción no arrancó"
kill -9 "$A"; sleep 1
[ "$(n_aplay)" -ge 1 ] && ok "1: tras kill -9 queda aplaymidi huérfano (situación a corregir)" \
                       || fallo "1: no se reprodujo la situación de huérfano"
"$DIR/detener-audio.sh" > "$TMP/d.log" 2>&1 && limpio && ok "1: detener-audio.sh deja todo limpio" \
                       || { fallo "1: quedaron restos tras detener-audio.sh"; cat "$TMP/d.log"; }

# 2) Instancia única
"$DIR/escuchar-midi.sh" -s "$LARGO" > "$TMP/b.log" 2>&1 &
B=$!
esperar_aplay || fallo "2: la primera reproducción no arrancó"
( max=0; for _ in $(seq 240); do n=$(n_aplay); [ "$n" -gt "$max" ] && max=$n; sleep 0.25; done; echo "$max" > "$TMP/max" ) &
VIGIA=$!
"$DIR/escuchar-midi.sh" -s -r "$TMP/wav" "$MIDI/02-acordes-pedal.mid" > "$TMP/c.log" 2>&1
C_RC=$?
sleep 1
kill -0 "$B" 2>/dev/null && fallo "2: la primera instancia sigue viva" || ok "2: la segunda instancia detuvo la primera"
grep -q "Hay otra reproducción en curso" "$TMP/c.log" && ok "2: la segunda instancia lo informa" \
                                                      || fallo "2: no informó la reproducción previa"
[ "$C_RC" -eq 0 ] && ok "2: la segunda instancia termina bien (rc=0)" || { fallo "2: rc=$C_RC"; tail -20 "$TMP/c.log"; }
wait "$VIGIA"
[ "$(cat "$TMP/max")" -le 1 ] && ok "2: nunca hubo más de un aplaymidi (máx=$(cat "$TMP/max"))" \
                             || fallo "2: hubo $(cat "$TMP/max") aplaymidi simultáneos"

# 3) Estado final
limpio && ok "3: no queda nada vivo y PipeWire está revertido" || fallo "3: quedaron procesos o ajustes"
[ ! -e "${XDG_RUNTIME_DIR:-/tmp}/escuchar-midi.pid" ] && ok "3: sin archivo PID residual" || fallo "3: PID residual"

# 4) Grabación y niveles
W="$TMP/wav/02-acordes-pedal.wav"
if [ -s "$W" ] && python3 "$DIR/analizar_wav.py" "$W" > "$TMP/n.log" 2>&1; then
    ok "4: WAV grabado y analizado: $(sed -n 2p "$TMP/n.log")"
    grep -q "nivel: canal 1: pico" "$TMP/c.log" && ok "4: el script informa el nivel" || fallo "4: el script no informó el nivel"
    dur=$(sed -n 's/^duración \([0-9.]*\) s.*/\1/p' "$TMP/n.log")
    awk -v d="$dur" 'BEGIN{exit !(d >= 20)}' && ok "4: duración razonable ($dur s)" || fallo "4: duración sospechosa ($dur s)"
    pico=$(sed -n 's/^canal 1: pico \([-+0-9.inf]*\) dBFS.*/\1/p' "$TMP/n.log")
    awk -v p="$pico" 'BEGIN{exit !(p > -60)}' && ok "4: hay señal en la grabación (pico $pico dBFS)" || fallo "4: grabación en silencio (pico $pico dBFS)"
else
    fallo "4: no se generó o no se pudo analizar el WAV"; cat "$TMP/n.log" 2>/dev/null
fi

# 5) -x: corte de SSH simulado = se cierran A LA VEZ la entrada (EOF) y la salida (lector muerto -> SIGPIPE)
VIGIA_LOG="$HOME/piano/logs/escuchar-midi-vigia.log"
antes=$( { wc -l < "$VIGIA_LOG"; } 2>/dev/null || echo 0)
mkfifo "$TMP/in" "$TMP/out"
sleep 600 > "$TMP/in" &
ESCRITOR=$!
cat "$TMP/out" > "$TMP/x.log" &
LECTOR=$!
"$DIR/escuchar-midi.sh" -s -x "$LARGO" < "$TMP/in" > "$TMP/out" 2>&1 &
X=$!
esperar_aplay && ok "5: reproducción con -x arrancada" || fallo "5: no arrancó con -x"
kill "$ESCRITOR" "$LECTOR"
for _ in $(seq 60); do kill -0 "$X" 2>/dev/null || break; sleep 0.25; done
kill -0 "$X" 2>/dev/null && fallo "5: el script sigue vivo tras el corte" || ok "5: el script terminó tras el corte (entrada y salida cerradas)"
sleep 0.5
despues=$( { wc -l < "$VIGIA_LOG"; } 2>/dev/null || echo 0)
[ "$despues" -gt "$antes" ] && ok "5: el vigilante lo registró en $VIGIA_LOG" || fallo "5: el vigilante no dejó registro"
limpio && ok "5: no queda nada sonando ni ajustes temporales" || fallo "5: quedaron restos tras el corte"
pgrep -P "$X" >/dev/null 2>&1 && fallo "5: quedaron procesos hijos del script" || ok "5: sin procesos residuales del script"

# 6) Con tarjeta, contra la salida virtual (PIANO_SOLO_SALIDAS: ninguna tarjeta real es candidata)
INICIO6="$(date '+%Y-%m-%d %H:%M:%S')"
quitar_v
pw-cli create-node adapter "{ factory.name=support.null-audio-sink node.name=$V node.description=\"$V\"
    media.class=Audio/Sink audio.position=[ FL FR ] object.linger=true }" >/dev/null
for _ in $(seq 40); do pw-link -i | grep -q "^$V:playback_FR" && break; sleep 0.25; done
PIANO_SOLO_SALIDAS="$V" PIANO_SALIDA="$V" "$DIR/escuchar-midi.sh" "$MIDI/05-afinacion.mid" > "$TMP/v.log" 2>&1 &
EV=$!
if esperar_aplay; then
    DEST="$(pw-link -l | awk '/^[^ \t]/ { o = $0; next } /\|->/ && o ~ /^piano-prueba:/ { sub(/^[ \t]*\|->[ \t]*/, ""); print }')"
    [ -n "$DEST" ] && ! grep -qv "^$V:" <<<"$DEST" && ok "6: con tarjeta, la cadena va solo a la elegida ($V)" \
        || fallo "6: destinos de la cadena: $(tr '\n' ' ' <<<"$DEST")"
else
    fallo "6: la reproducción con tarjeta no arrancó"; tail -10 "$TMP/v.log"
fi
wait "$EV"; EV_RC=$?
FIN6=$(date +%s)
[ "$EV_RC" -eq 0 ] && ok "6: termina bien (rc=0)" || { fallo "6: rc=$EV_RC"; tail -10 "$TMP/v.log"; }
[ "$(dato_v state)" = suspended ] && grep -qF "== Salida al terminar: $V: suspendida" "$TMP/v.log" \
    && ok "6: al terminar, la tarjeta queda suspendida (WirePlumber esperaría 5 s)" \
    || fallo "6: $V: $(dato_v state); $(grep -F 'Salida al terminar' "$TMP/v.log")"
i="$(dato_v id)"; [ -z "$i" ] || pw-cli destroy "$i" >/dev/null 2>&1      # «desenchufarla» enseguida
while [ $(( $(date +%s) - FIN6 )) -lt 7 ]; do sleep 0.5; done
N_WP=$(journalctl _UID="$(id -u)" --since "$INICIO6" --no-pager -o cat | grep -c '^wireplumber\.service: Main process exited, code=.*status=11/SEGV')
[ "$N_WP" -eq 0 ] && ok "6: desenchufarla nada más terminar no hace caer a WirePlumber" || fallo "6: WirePlumber cayó ($N_WP)"
limpio && ok "6: no queda nada sonando ni ajustes temporales" || fallo "6: quedaron restos"

echo
if [ "$FALLOS" -eq 0 ]; then echo "TODAS LAS PRUEBAS PASAN"; else echo "$FALLOS PRUEBA(S) FALLAN"; exit 1; fi
