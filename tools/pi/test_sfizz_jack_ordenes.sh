#!/bin/bash
# Prueba de integración EN LA RASPBERRY de las órdenes del sfizz_jack parcheado (parche 0002), con un
# instrumento mínimo generado (seno) y en silencio: la salida solo va a grabadores, nunca a la G1.
#  0) las salidas quedan enlazadas solo a un ancla (grabador nulo, lib-pw.sh): los grabadores de cada nota van y
#     vienen sin dejarlas nunca sin enlaces (pipewire-jack 1.2.7 haría caer a sfizz con SIGSEGV)
# Si sfizz termina en mitad de la prueba, se informa (con la causa del registro) y se aborta: escribir en el FIFO
# sin lector bloquearía para siempre, así que cada orden tiene un tiempo límite.
#  1) --sample_quality 1 se aplica (lo informa al arrancar)
#  2) set_volume cambia el nivel real y SE CONSERVA tras load_instrument (ruta con espacios)
#  3) set_cc cambia la síntesis (la región exige CC20 >= 64: con CC20 = 0 no suena)
#  4) órdenes erróneas se rechazan sin afectar al proceso
#  5) una carga fallida deja el sintetizador recuperable con otra carga
#  6) quit termina el proceso
#  7) SIGTERM (parada de la unidad) termina enseguida aunque la entrada sea un FIFO que nunca ve EOF
#     (antes sfizz esperaba para siempre a su hilo de órdenes y systemd lo mataba a los 90 s)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
SFIZZ="${SFIZZ:-$HOME/piano/bin/sfizz_jack}"
TMP="$(mktemp -d)"
CLIENTE=piano-prueba-sfizz
FIFO="$TMP/ordenes.ctl"
MIDI_ORIGEN='Midi-Bridge:Midi Through:(capture_0) Midi Through Port-0'
RATE=44100
QUANTUM=512
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
UNIDADES=()
source "$DIR/lib-pw.sh"
fin() {
    [ -n "${REC:-}" ] && kill -INT "$REC" 2>/dev/null
    systemctl --user stop "$CLIENTE" 2>/dev/null
    detener_ancla   # después de sfizz (ver redirigir en lib-pw.sh)
    pw-metadata -n settings 0 clock.force-quantum 0 >/dev/null 2>&1
    pw-metadata -n settings 0 clock.force-rate 0 >/dev/null 2>&1
    rm -rf "$TMP"
}
trap fin EXIT

"$DIR/detener-audio.sh" --solo-pruebas >/dev/null

# Instrumento mínimo: seno de 440 Hz (−6 dBFS, 1,5 s); la región solo suena con CC20 >= 64 (por defecto 127).
python3 - "$TMP" <<'EOF'
import math, os, struct, sys, wave
d = sys.argv[1]
with wave.open(os.path.join(d, "seno.wav"), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(b"".join(struct.pack("<h", int(16384 * math.sin(2 * math.pi * 440 * i / 44100)))
                           for i in range(int(1.5 * 44100))))
sfz = "<control> set_cc20=127\n<region> sample=seno.wav lokey=0 hikey=127 pitch_keycenter=69 locc20=64 amp_veltrack=0\n"
open(os.path.join(d, "a.sfz"), "w").write(sfz)
os.makedirs(os.path.join(d, "con espacios"))
open(os.path.join(d, "con espacios", "b b.sfz"), "w").write(sfz.replace("seno.wav", "../seno.wav"))
EOF
DIR_TOOLS="$DIR" python3 - "$TMP/nota.mid" <<'EOF'
import os, sys
sys.path.insert(0, os.environ["DIR_TOOLS"])
import generar_midis_prueba as g
p = g.Pista()
p.nota(0, 69, 100, g.NEGRA * 2)          # 1 s
g.escribir_smf(sys.argv[1], p)
EOF
[ -s "$TMP/a.sfz" ] && [ -s "$TMP/nota.mid" ] || { echo "no se pudo generar el material de prueba"; exit 1; }

mkfifo -m 600 "$FIFO"
pw-metadata -n settings 0 clock.force-rate "$RATE" >/dev/null
pw-metadata -n settings 0 clock.force-quantum "$QUANTUM" >/dev/null
DESDE="$(date '+%Y-%m-%d %H:%M:%S')"
( iniciar_cliente "$CLIENTE" "$SFIZZ --client_name $CLIENTE --num_voices 8 --sample_quality 1 '$TMP/a.sfz'" \
      '^in midi' "Instrument loaded" "$FIFO" ) > "$TMP/inicio.log" 2>&1 \
    || { fallo "0: sfizz_jack no arrancó"; cat "$TMP/inicio.log"; exit 1; }
P="$(puertos "$CLIENTE")"
MIDI_IN="$(awk '$1=="in" && $2=="midi"' <<<"$P" | head -1 | cut -d' ' -f3-)"
mapfile -t SALIDAS < <(awk '$1=="out" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
sleep 1
ANCLA=piano-ancla-prueba-sfizz
iniciar_ancla "$ANCLA" "${SALIDAS[0]}" "${SALIDAS[1]:-}"
aisladas=1
for s in "${SALIDAS[@]}"; do
    d="$(destinos_de "$s")"
    { [ -n "$d" ] && ! grep -qv "^$ANCLA:" <<<"$d"; } || aisladas=0
done
[ "$aisladas" = 1 ] && ok "0: salidas enlazadas solo al ancla (silencio, nunca sin enlaces)" \
    || { fallo "0: no se pudo aislar: $(for s in "${SALIDAS[@]}"; do destinos_de "$s"; done | tr '\n' ' ')"; exit 1; }
enlazar "$MIDI_ORIGEN" "$MIDI_IN"
destinos_de "$MIDI_ORIGEN" | grep -qxF "$MIDI_IN" && ok "0: Midi Through -> sfizz enlazado" || { fallo "0: sin enlace MIDI"; exit 1; }

# Diagnóstico (a stderr) para cuando una nota que debe sonar no suena: enlaces del nodo y su estado en PipeWire
estado_enlaces() {
    {
        echo "      MIDI: $MIDI_ORIGEN -> $(destinos_de "$MIDI_ORIGEN" | tr '\n' ' ')"
        for s in "${SALIDAS[@]}"; do echo "      $s -> $(destinos_de "$s" | tr '\n' ' ')"; done
        pw-dump > "$TMP/grafo.json"
        python3 - "$CLIENTE" "$TMP/grafo.json" <<'EOF'
import json, sys
objetos = json.load(open(sys.argv[2]))
nombre = {o["id"]: o["info"]["props"].get("node.name", "") for o in objetos
          if o.get("type") == "PipeWire:Interface:Node" and o.get("info")}
for o in objetos:
    if o.get("type") != "PipeWire:Interface:Link" or not o.get("info"):
        continue
    i = o["info"]
    a, b = nombre.get(i.get("output-node-id"), "?"), nombre.get(i.get("input-node-id"), "?")
    if sys.argv[1] in (a, b):
        print("      enlace %s -> %s: %s %s" % (a, b, i.get("state"), i.get("error") or ""))
EOF
    } >&2
}

registro() { journalctl --user-unit="$CLIENTE" --since "$DESDE" --no-pager -o cat 2>/dev/null; }
sigue_vivo() {   # si sfizz terminó (p. ej. SIGSEGV), lo informa con la causa y aborta: el resto no tendría sentido
    systemctl --user is-active --quiet "$CLIENTE" && return 0
    fallo "sfizz terminó en mitad de la prueba: $(journalctl --user-unit="$CLIENTE" --since "$DESDE" --no-pager -o cat \
        | grep -E 'status=|signal' | tail -1)"
    echo "$FALLOS FALLO(S)"
    exit 1
}
esperar() {   # esperar REGEX [segundos]: espera una línea nueva del registro que cumpla REGEX
    local n
    for n in $(seq $(( ${2:-10} * 4 ))); do registro | grep -qE "$1" && return 0; sleep 0.25; done
    return 1
}
orden() {   # sin lector (sfizz caído), abrir el FIFO bloquearía para siempre: se limita a 3 s
    timeout 3 bash -c 'printf "%s\n" "$1" > "$2"' _ "$1" "$FIFO" && return 0
    sigue_vivo
    fallo "la orden no llegó a sfizz en 3 s: $1"
}
cuenta() { registro | grep -cE "$1"; }
grabar_nota() {   # grabar_nota ARCHIVO.wav -> pico dBFS (máximo de los canales) en stdout; avisos a stderr
    local nodo="piano-grabacion-sfizz-$RANDOM" g n
    pw-record --target 0 -P "{ node.name = \"$nodo\" }" --rate "$RATE" --channels 2 --format f32 "$1" &
    REC=$!
    for n in $(seq 40); do g="$(puertos "$nodo")"; [ "$(grep -c '^in audio' <<<"$g")" -ge 2 ] && break; sleep 0.25; done
    mapfile -t RIN < <(awk '$1=="in" && $2=="audio"' <<<"$g" | cut -d' ' -f3-)
    { pw-link "${SALIDAS[0]}" "${RIN[0]}" && pw-link "${SALIDAS[1]:-${SALIDAS[0]}}" "${RIN[1]}"; } \
        || echo "      AVISO: no se pudo enlazar el grabador $nodo (entradas: ${RIN[*]:-ninguna})" >&2
    sleep 0.3
    aplaymidi -p 14:0 "$TMP/nota.mid"
    sleep 0.8
    kill -INT "$REC"; wait "$REC" 2>/dev/null; REC=""
    python3 "$DIR/analizar_wav.py" "$1"         | awk '/^canal/ { v = ($4 == "-inf") ? -999 : $4 + 0; if (!h || v > m) { m = v; h = 1 } }
               END { print (h ? m : -999) }'
}

# 1) Calidad
registro | grep -q "Sample quality (live): 1" && ok "1: calidad de interpolación en vivo = 1" \
    || fallo "1: no informa 'Sample quality (live): 1'"

# 2) Volumen y conservación tras cargar
orden "set_volume 0"
esperar "Volume set: 0 dB" && ok "2: set_volume 0 confirmado" || fallo "2: sin confirmación de set_volume 0"
P0="$(grabar_nota "$TMP/v0.wav")"; sigue_vivo
awk -v a="$P0" 'BEGIN { exit !(a > -80) }' && ok "2: la nota de referencia (0 dB) suena (pico $P0 dBFS)" \
    || { fallo "2: la nota de referencia (0 dB) no suena (pico $P0 dBFS): ¿no llegó el MIDI o no grabó?"; estado_enlaces; }
orden "set_volume -12"
esperar "Volume set: -12 dB" && ok "2: set_volume -12 confirmado" || fallo "2: sin confirmación de set_volume -12"
orden "load_instrument \"$TMP/con espacios/b b.sfz\""
esperar "Instrument loaded: $TMP/con espacios/b b.sfz" && ok "2: load_instrument con espacios en la ruta" \
    || fallo "2: no cargó la ruta con espacios"
P1="$(grabar_nota "$TMP/v1.wav")"; sigue_vivo
awk -v a="$P0" -v b="$P1" 'BEGIN { d = a - b; exit !(a > -30 && d > 11.5 && d < 12.5) }' \
    && ok "2: el volumen (-12 dB) se conserva tras cargar otro instrumento (pico $P0 -> $P1 dBFS)" \
    || fallo "2: niveles inesperados: pico a 0 dB = $P0, tras -12 dB y carga = $P1"

# 3) set_cc
orden "set_cc 20 0"
esperar "CC set: 20 = 0" && ok "3: set_cc 20 0 confirmado" || fallo "3: sin confirmación de set_cc"
P2="$(grabar_nota "$TMP/v2.wav")"; sigue_vivo
awk -v c="$P2" 'BEGIN { exit !(c < -80) }' && ok "3: con CC20 = 0 la región no suena (pico $P2 dBFS)" \
    || fallo "3: con CC20 = 0 sigue sonando (pico $P2 dBFS)"

# 4) Órdenes erróneas
antes="$(cuenta "ERROR: Can't set CC!")"
orden "set_cc 200 1"; orden "set_cc 20"; orden "set_cc x y"
esperar "ERROR: Can't set CC!" && sleep 0.5
[ "$(( $(cuenta "ERROR: Can't set CC!") - antes ))" -eq 3 ] && ok "4: set_cc fuera de rango / incompleto / no numérico se rechaza" \
    || fallo "4: rechazos de set_cc: $(( $(cuenta "ERROR: Can't set CC!") - antes )) de 3"
orden "set_volume abc"
esperar "ERROR: Can't set volume!" && ok "4: set_volume no numérico se rechaza" || fallo "4: set_volume abc no se rechazó"
systemctl --user is-active --quiet "$CLIENTE" && ok "4: el proceso sigue vivo tras los errores" || fallo "4: el proceso terminó"

# 5) Carga fallida y recuperación
orden "load_instrument \"$TMP/no-existe.sfz\""
esperar "Could not load the instrument file: $TMP/no-existe.sfz" && ok "5: la carga de un archivo inexistente se informa" \
    || fallo "5: no informa la carga fallida"
orden "load_instrument \"$TMP/a.sfz\""
esperar "Instrument loaded: $TMP/a.sfz" || true
P3="$(grabar_nota "$TMP/v3.wav")"; sigue_vivo
awk -v a="$P1" -v b="$P3" 'BEGIN { d = a - b; exit !(b > -80 && d < 0.5 && d > -0.5) }' \
    && ok "5: tras recargar vuelve a sonar, con el mismo volumen (CC20 restaurado por el instrumento; pico $P3 dBFS)" \
    || fallo "5: tras recargar: pico $P3 dBFS (esperado ≈ $P1)"

# 6) quit
orden "quit"
for _ in $(seq 20); do systemctl --user is-active --quiet "$CLIENTE" || break; sleep 0.25; done
systemctl --user is-active --quiet "$CLIENTE" && fallo "6: quit no terminó el proceso" || ok "6: quit termina el proceso"

# 7) Parada con SIGTERM
DESDE="$(date '+%Y-%m-%d %H:%M:%S')"
( iniciar_cliente "$CLIENTE" "$SFIZZ --client_name $CLIENTE --num_voices 8 --sample_quality 1 '$TMP/a.sfz'"       '^in midi' "Instrument loaded" "$FIFO" ) > "$TMP/inicio2.log" 2>&1 || fallo "7: no volvió a arrancar"
T0=$(date +%s.%N)
systemctl --user stop "$CLIENTE"
T=$(awk -v a="$T0" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
awk -v t="$T" 'BEGIN{exit !(t < 5)}' && ok "7: SIGTERM con la entrada en un FIFO: termina en $T s"     || fallo "7: la parada tardó $T s (¿espera al hilo de órdenes?)"
registro | grep -q "Closing..." && ok "7: cierre ordenado (cliente JACK cerrado)" || fallo "7: no consta el cierre"
journalctl --user-unit="$CLIENTE" --since "$DESDE" --no-pager | grep -q "SIGKILL" && fallo "7: systemd tuvo que usar SIGKILL"     || ok "7: sin SIGKILL"

[ "$FALLOS" -eq 0 ] && echo "TODO OK" || { echo "$FALLOS FALLO(S)"; exit 1; }
