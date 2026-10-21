#!/bin/bash
# Prueba de integración EN LA RASPBERRY del piano en vivo (modo silencio: no suena nada por la G1).
#  1) arranque con -p: marca "listo", gobernador performance, PipeWire y reverb en los núcleos de audio,
#     cadena sfizz -> reverb, sin salida a la G1 (la reverb va solo a un ancla: grabador nulo)
#  2) instancia única
#  3) teclado simulado (FIFO con pausas reales): el enrutador lo conecta solo y hay audio en la reverb
#  3b) controles: volumen (G1), reverb (enrutador -> jalv), transposición y latencia (enrutador -> PipeWire)
#  3c) cambio de instrumento en caliente: confirmación de sfizz, ganancia, audio real, fallo de carga con
#      recuperación, recorrido rápido (solo carga el último) y preferencia guardada
#  4b) al volver a arrancar se restauran las preferencias guardadas
#  4) parada ordenada: todo limpio y gobernador restaurado
#  5) muerte brusca (kill -9): detener-audio.sh recupera unidades, gobernador y el ancla del modo silencio
#  6) ningún cliente (sfizz, reverb) cae con SIGSEGV en toda la prueba
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"   # los fragmentos de Python de la prueba importan los módulos de esta carpeta
RUNDIR="${XDG_RUNTIME_DIR:-/tmp}"
G=/sys/devices/system/cpu/cpufreq/policy0/scaling_governor
GOB_INICIAL="$(cat $G)"
PW="$(pidof -s pipewire)"
AFIN_PW_INICIAL="$(taskset -p -c "$PW" | awk -F': ' '{print $2}')"
# Núcleos de todos los hilos de un proceso, sin repetir (p. ej. "2,3"; "0-3|2,3" si difieren)
afinidad_hilos() { for t in /proc/"$1"/task/*; do taskset -p -c "${t##*/}" | awk -F': ' '{print $2}'; done | sort -u | paste -sd'|'; }
TMP="$(mktemp -d)"
export PIANO_PREFERENCIAS="$TMP/preferencias.json"     # no tocar las preferencias reales
# Catálogo de prueba: el real (instrumentos reales, enlazados) + uno roto (SFZ vacío) para probar los fallos.
mkdir -p "$TMP/inst/roto"
for d in "$HOME"/piano/instrumentos/*/; do ln -s "${d%/}" "$TMP/inst/$(basename "$d")"; done
: > "$TMP/inst/roto/roto.sfz"
python3 - "$DIR/instrumentos.json" "$TMP/catalogo.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
d["instrumentos"].append({"id": "roto", "nombre": "Roto (prueba)", "tipo": "cola", "sfz": "roto/roto.sfz",
                          "ganancia_db": 0, "autor": "prueba", "licencia": "-", "uso": "-", "fuente": "-"})
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
EOF
export PIANO_CATALOGO="$TMP/catalogo.json" PIANO_INSTRUMENTOS="$TMP/inst"
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
source "$DIR/lib-pw.sh"
DIR_LIB="$DIR"
fin() {
    kill "${PIANO:-}" "${TECLADO:-}" "${GRAB:-}" 2>/dev/null
    "$DIR/detener-audio.sh" >/dev/null 2>&1
    [ "$(cat $G)" = "$GOB_INICIAL" ] || echo "$GOB_INICIAL" | sudo -n tee $G >/dev/null
    taskset -a -p -c "$AFIN_PW_INICIAL" "$PW" >/dev/null 2>&1
    rm -rf "$TMP"
}
trap fin EXIT
esperar_listo() { for _ in $(seq 120); do [ -e "$RUNDIR/piano-vivo.listo" ] && return 0; sleep 0.5; done; return 1; }
# Estado del instrumento en el enrutador: "<estado> <actual> <cargando>" (ids, "-" si no hay)
est_inst() {
    python3 -c "import json; e = json.load(open('$RUNDIR/piano-enrutador.json'))['instrumento']
print(e['estado'], (e['actual'] or {}).get('id', '-'), (e['cargando'] or {}).get('id', '-'))" 2>/dev/null
}
esperar_inst() { for _ in $(seq 360); do [ "$(est_inst)" = "$1" ] && return 0; sleep 0.25; done; return 1; }
ganancia_de() { python3 -c "import json; print('%g' % next(i['ganancia_db'] for i in json.load(open('$PIANO_CATALOGO'))['instrumentos'] if i['id'] == '$1'))"; }
registro_sfizz() { journalctl --user-unit=piano-vivo --since "$1" --no-pager -o cat; }
# tocar_y_grabar WAV [TECLAS]: graba la salida de la reverb mientras un teclado simulado toca las teclas (códigos
# evdev, 1 s cada una; por defecto A y G = do4 y sol4)
tocar_y_grabar() {
    local teclas="${2:-30 34}"
    local nodo="piano-grabacion-test-$RANDOM" rin
    pw-record --target 0 -P "{ node.name = \"$nodo\" }" --rate 44100 --channels 2 --format f32 "$1" &
    GRAB=$!
    for _ in $(seq 40); do [ "$(puertos "$nodo" | grep -c '^in audio')" -ge 2 ] && break; sleep 0.25; done
    mapfile -t rin < <(puertos "$nodo" | awk '$1=="in" && $2=="audio"' | cut -d' ' -f3-)
    pw-link piano-vivo-fx:left_out "${rin[0]}" && pw-link piano-vivo-fx:right_out "${rin[1]}"
    rm -f "$TMP/teclas2"; mkfifo "$TMP/teclas2"
    python3 "$DIR/teclado_piano.py" --entrada-prueba "$TMP/teclas2" --interfaz linea --nombre-cliente "Teclado Prueba" \
            > "$TMP/teclado2.log" 2>&1 &
    TECLADO=$!
    python3 - "$TMP/teclas2" $teclas <<'EOF'
import sys, time
import teclado_piano as tp
with open(sys.argv[1], "wb", buffering=0) as f:
    time.sleep(3.0)                                  # conexión automática del teclado nuevo (sondeo de 1 s)
    for codigo in map(int, sys.argv[2:]):
        f.write(tp.empaquetar_evento(codigo, 1))
        time.sleep(1.0)
        f.write(tp.empaquetar_evento(codigo, 0))
        time.sleep(0.3)
    time.sleep(0.7)
    f.write(tp.empaquetar_evento(1, 1))
EOF
    wait "$TECLADO"; TECLADO=""
    kill -INT "$GRAB"; wait "$GRAB" 2>/dev/null; GRAB=""
}
unidades_vivo() { systemctl --user list-units 'piano-vivo*' --no-legend --plain | awk '{print $1}' | tr '\n' ' '; }

"$DIR/detener-audio.sh" >/dev/null

# 1) Arranque
INICIO_TEST="$(date '+%Y-%m-%d %H:%M:%S')"
"$DIR/piano-en-vivo.sh" -s -p > "$TMP/piano.log" 2>&1 &
PIANO=$!
esperar_listo && ok "1: el piano queda listo" || { fallo "1: no quedó listo"; cat "$TMP/piano.log"; exit 1; }
[ "$(cat $G)" = performance ] && ok "1: gobernador en performance durante la sesión" || fallo "1: gobernador $(cat $G)"
[ -f "$RUNDIR/piano-vivo.gobernador" ] && ok "1: marca de gobernador creada" || fallo "1: sin marca de gobernador"
[ "$(afinidad_hilos "$PW")" = "2,3" ] && ok "1: PipeWire (todos sus hilos) en los núcleos 2,3 durante la sesión" \
    || fallo "1: núcleos de PipeWire: $(afinidad_hilos "$PW") (antes: $AFIN_PW_INICIAL)"
[ "$(cut -d' ' -f1 "$RUNDIR/piano-vivo.afinidad-pipewire" 2>/dev/null)" = "$PW" ] && ok "1: marca de núcleos de PipeWire creada" \
    || fallo "1: sin marca de núcleos de PipeWire"
PFX="$(pgrep -f '^jalv -x -n piano-vivo-fx' | head -1)"
[ -n "$PFX" ] && [ "$(afinidad_hilos "$PFX")" = "2,3" ] && ok "1: reverb (jalv) en los núcleos 2,3" \
    || fallo "1: núcleos de jalv: $( [ -n "$PFX" ] && afinidad_hilos "$PFX")"
pgrep -af enrutador_midi.py | grep -q -- "--nodo-xruns piano-vivo-fx" && ok "1: el enrutador vigila también los cortes de la reverb" \
    || fallo "1: el enrutador no vigila la reverb"
destinos_de piano-vivo:output_1 | grep -q "^piano-vivo-fx:" && ok "1: sfizz -> reverb enlazado" || fallo "1: sfizz no enlazado a la reverb"
DFX="$(destinos_de piano-vivo-fx:left_out; destinos_de piano-vivo-fx:right_out)"
[ "$(grep -c '^piano-ancla-vivo:' <<<"$DFX")" -eq 2 ] && ! grep -qv '^piano-ancla-vivo:' <<<"$DFX" \
    && ok "1: modo silencio: la reverb va solo al ancla (grabador nulo), nunca a la G1 ni sin enlaces" \
    || fallo "1: destinos de la reverb en silencio: $(tr '\n' ' ' <<<"$DFX")"
pgrep -f '^pw-record .*piano-ancla-vivo' >/dev/null && ok "1: ancla del modo silencio en marcha" || fallo "1: sin ancla"
grep -q "Instrument loaded\|listo en" "$TMP/piano.log" && ok "1: Salamander cargado" || fallo "1: no consta la carga"
systemctl --user is-active --quiet piano-vivo-midi && ok "1: enrutador MIDI activo" || fallo "1: enrutador no activo"
SAL_MIDI="$(pw-link -o | grep -m1 -E '^Midi-Bridge:Piano Enrutador:\(capture_[0-9]+\) salida$')"
destinos_de "$SAL_MIDI" | grep -q "^piano-vivo:" && ok "1: enrutador -> sfizz enlazado" || fallo "1: enrutador no enlazado a sfizz"
grep -q "^router_ctl=" "$RUNDIR/piano-vivo.estado" && [ -f "$RUNDIR/piano-enrutador.json" ] \
    && ok "1: estado del enrutador publicado" || fallo "1: falta el estado del enrutador"
# Créditos de cada sonido, del catálogo a la interfaz (panel inferior izquierdo y menú F9): los publica el enrutador
CRED="$(python3 -c "import json; l = json.load(open('$RUNDIR/piano-enrutador.json'))['instrumento']['lista']
s = next(i for i in l if i['id'] == 'salamander'); r = next(i for i in l if i['id'] == 'rhodes')
print(s['autor'], '|', s['uso'], '|', s['restringido'], '|', r['uso'], '|', r['restringido'], '|', len(l),
      all(i.get('licencia') and i.get('fuente') for i in l))" 2>&1)"
# Se publican los sonidos INSTALADOS (el Softify es opcional: se descarga a mano), más el roto de la prueba
N_INSTALADOS="$(python3 -c "import json, os; c = json.load(open('$PIANO_CATALOGO', encoding='utf-8'))
print(sum(os.path.isfile(os.path.join('$PIANO_INSTRUMENTOS', i['sfz'])) for i in c['instrumentos']))")"
[ "$CRED" = "Alexander Holm | libre; citar al autor | False | solo uso no comercial | True | $N_INSTALADOS True" ] \
    && ok "1: el enrutador publica los créditos de cada sonido (autor, licencia, uso, restricción, fuente)" \
    || fallo "1: créditos publicados: $CRED"
esperar_inst "listo salamander -" && ok "1: instrumento inicial: salamander (preferencia por defecto), ajustes confirmados" \
    || fallo "1: estado del instrumento: $(est_inst)"
registro_sfizz "$INICIO_TEST" | grep -q "Sample quality (live): 1" && registro_sfizz "$INICIO_TEST" | grep -q "Volume set: 0 dB" \
    && ok "1: sfizz con interpolación lineal (--sample_quality 1) y ganancia 0 dB" || fallo "1: sin calidad 1 o sin set_volume"
P="$(pgrep -f '^\S*sfizz_jack --client_name piano-vivo' | head -1)"
[ -n "$P" ] && [ "$(taskset -pc "$P" | awk -F': ' '{print $2}')" = "2,3" ] && ok "1: sfizz fijado a los núcleos 2,3" \
    || fallo "1: afinidad de sfizz: $(taskset -pc "$P" 2>&1)"

# 2) Instancia única
"$DIR/piano-en-vivo.sh" -s > "$TMP/segundo.log" 2>&1; RC=$?
[ "$RC" -eq 3 ] && grep -q "ya está en marcha" "$TMP/segundo.log" && ok "2: una segunda instancia se rechaza (rc=3)" \
    || fallo "2: segunda instancia rc=$RC: $(cat "$TMP/segundo.log")"
kill -0 "$PIANO" 2>/dev/null && ok "2: la primera instancia sigue viva" || fallo "2: la primera instancia murió"

# 3) Teclado simulado con pausas reales + grabación de la salida de la reverb
pw-record --target 0 -P '{ node.name = "piano-grabacion-test" }' --rate 44100 --channels 2 --format f32 "$TMP/salida.wav" &
GRAB=$!
for _ in $(seq 40); do [ "$(puertos piano-grabacion-test | grep -c '^in audio')" -ge 2 ] && break; sleep 0.25; done
mapfile -t RIN < <(puertos piano-grabacion-test | awk '$1=="in" && $2=="audio"' | cut -d' ' -f3-)
pw-link piano-vivo-fx:left_out "${RIN[0]}" && pw-link piano-vivo-fx:right_out "${RIN[1]}" \
    && ok "3: grabador enlazado a la salida de la reverb" || fallo "3: no se pudo enlazar el grabador"
mkfifo "$TMP/teclas"
python3 "$DIR/teclado_piano.py" --entrada-prueba "$TMP/teclas" --interfaz linea --nombre-cliente "Teclado Prueba" \
        > "$TMP/teclado.log" 2>&1 &
TECLADO=$!
python3 - "$TMP/teclas" "$TMP/fuentes.log" <<'EOF'
import sys, time
import teclado_piano as tp
with open(sys.argv[1], "wb", buffering=0) as f:
    time.sleep(3.0)                                  # margen para la conexión automática (sondeo de 1 s)
    import json
    with open("/run/user/1000/piano-enrutador.json") as e:
        activas = [x["id"] for x in json.load(e)["fuentes"] if x["activa"] and x["conectada"]]
    with open(sys.argv[2], "w") as log:
        log.write("\n".join(activas))
    for codigo, valor, pausa in [(30, 1, 1.5), (30, 0, 0.5), (34, 1, 1.0), (34, 0, 1.5), (1, 1, 0)]:
        f.write(tp.empaquetar_evento(codigo, valor))
        time.sleep(pausa)
EOF
wait "$TECLADO"; RC=$?
kill -INT "$GRAB"; wait "$GRAB" 2>/dev/null; GRAB=""
[ "$RC" -eq 0 ] && ok "3: teclado simulado terminó bien" || { fallo "3: teclado rc=$RC"; cat "$TMP/teclado.log"; }
grep -q "Teclado Prueba:notas" "$TMP/fuentes.log" && ok "3: el enrutador conectó solo el teclado nuevo" \
    || { fallo "3: el enrutador no conectó el teclado"; cat "$TMP/fuentes.log"; }
NIVEL="$(python3 "$DIR/analizar_wav.py" "$TMP/salida.wav" 2>&1)"
PICO="$(sed -n 's/^canal 1: pico \([-+0-9.inf]*\) dBFS.*/\1/p' <<<"$NIVEL")"
awk -v p="$PICO" 'BEGIN{exit !(p > -50 && p < 0)}' && ok "3: hay sonido del piano en la salida (pico $PICO dBFS, sin recorte)" \
    || { fallo "3: nivel inesperado en la salida"; echo "$NIVEL"; }

# 3b) Controles de la interfaz contra el piano real: reverb (FIFO de jalv) y volumen de la G1 (wpctl)
[ -f "$RUNDIR/piano-vivo.estado" ] && grep -q "^reverb_ctl=" "$RUNDIR/piano-vivo.estado" \
    && ok "3b: estado publicado ($(tr '\n' ' ' < "$RUNDIR/piano-vivo.estado"))" || fallo "3b: sin archivo de estado"
VOL_ANTES="$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print $2}')"
DESDE="$(date '+%Y-%m-%d %H:%M:%S')"
RES="$(python3 - "$RUNDIR/piano-vivo.estado" <<'EOF'
import sys
import teclado_piano as tp
c = tp.Controles.desde_estado(sys.argv[1])
v0, r0 = c.volumen, c.reverb
c.aplicar(("reverb", +1)); c.aplicar(("reverb", +1))
c.aplicar(("volumen", -1))
c.aplicar(("router", "transponer +1"))
c.aplicar(("router", "latencia siguiente"))
import time; time.sleep(0.6)
with open(c.ctl_reverb, "w") as f:
    f.write("controls\n")                 # jalv vuelca sus controles al journal
print(f"{v0} {c.volumen} {r0} {c.reverb}")
EOF
)"
read -r V0 V1 R0 R1 <<<"$RES"
sleep 1
VREAL="$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print $2}')"
awk -v a="$V0" -v b="$V1" -v r="$VREAL" 'BEGIN{exit !(b < a - 0.04 && b > a - 0.06 && r - b < 0.005 && b - r < 0.005)}' \
    && ok "3b: el volumen de la G1 bajó un paso ($V0 -> $V1; real $VREAL)" || fallo "3b: volumen $V0 -> $V1 (real $VREAL)"
[ "$R0" = "0.35" ] && [ "$R1" = "0.45" ] && ok "3b: reverb 0.35 -> 0.45 en la interfaz" || fallo "3b: reverb $R0 -> $R1"
journalctl --user-unit=piano-vivo-fx --since "$DESDE" --no-pager -o cat | grep -q "mix = 0.450000" \
    && ok "3b: el enrutador pasó la reverb a jalv (mix = 0.450000)" || { fallo "3b: jalv no muestra el cambio de reverb"; journalctl --user-unit=piano-vivo-fx --since "$DESDE" --no-pager -o cat | tail -8; }
python3 -c "import json,sys; e=json.load(open('$RUNDIR/piano-enrutador.json')); sys.exit(0 if e['transposicion']==1 and e['latencia']==1024 else 1)" \
    && ok "3b: transposición +1 y latencia 1024 en el enrutador" || fallo "3b: el enrutador no aplicó transposición/latencia"
META="$(pw-metadata -n settings 0)"; grep -q "clock.force-quantum' value:'1024'" <<<"$META" && ok "3b: PipeWire usa ya el bloque de 1024 (en caliente)" \
    || fallo "3b: PipeWire no cambió la latencia: $(pw-metadata -n settings 0 | grep force-quantum)"
python3 -c "import json,sys; p=json.load(open('$PIANO_PREFERENCIAS')); sys.exit(0 if (p['reverb'],p['transposicion'],p['latencia'])==(0.45,1,1024) else 1)" \
    && ok "3b: preferencias guardadas (reverb 0.45, transposición +1, latencia 1024)" || fallo "3b: preferencias no guardadas: $(cat "$PIANO_PREFERENCIAS")"
wpctl set-volume @DEFAULT_AUDIO_SINK@ "$VOL_ANTES"
[ "$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print $2}')" = "$VOL_ANTES" ] && ok "3b: volumen restaurado ($VOL_ANTES)" \
    || fallo "3b: no se pudo restaurar el volumen"

# 3c) Cambio de instrumento en caliente
DESDE="$(date '+%Y-%m-%d %H:%M:%S')"; T0=$(date +%s)
echo "instrumento wurlitzer" > "$RUNDIR/piano-enrutador.ctl"
esperar_inst "listo wurlitzer -" && ok "3c: cambio a Wurlitzer confirmado por sfizz en $(( $(date +%s) - T0 )) s" \
    || { fallo "3c: el cambio no terminó: $(est_inst)"; registro_sfizz "$DESDE" | tail -8; }
G_W="$(ganancia_de wurlitzer)"
registro_sfizz "$DESDE" | grep -q "Instrument loaded: $TMP/inst/epianos/Wurlitzer EP200/Wurlitzer EP200.sfz" \
    && registro_sfizz "$DESDE" | grep -q "Volume set: $G_W dB" \
    && ok "3c: sfizz cargó el SFZ (ruta con espacios) y aplicó su ganancia ($G_W dB)" \
    || { fallo "3c: no consta la carga o la ganancia"; registro_sfizz "$DESDE" | tail -8; }
python3 -c "import json,sys; sys.exit(0 if json.load(open('$PIANO_PREFERENCIAS'))['instrumento'] == 'wurlitzer' else 1)" \
    && ok "3c: preferencia guardada (wurlitzer)" || fallo "3c: preferencia: $(cat "$PIANO_PREFERENCIAS")"
tocar_y_grabar "$TMP/wurlitzer.wav"
NIVEL="$(python3 "$DIR/analizar_wav.py" "$TMP/wurlitzer.wav" 2>&1)"
PICO="$(sed -n 's/^canal 1: pico \([-+0-9.inf]*\) dBFS.*/\1/p' <<<"$NIVEL")"
awk -v p="$PICO" 'BEGIN{exit !(p > -50 && p < -3)}' && ok "3c: suena el Wurlitzer tras el cambio (pico $PICO dBFS, con margen)" \
    || { fallo "3c: nivel inesperado tras el cambio"; echo "$NIVEL"; }

DESDE="$(date '+%Y-%m-%d %H:%M:%S')"
echo "instrumento roto" > "$RUNDIR/piano-enrutador.ctl"
esperar_inst "error wurlitzer -" && ok "3c: un instrumento que no carga se informa y se vuelve al anterior (Wurlitzer)" \
    || { fallo "3c: tras el fallo: $(est_inst)"; registro_sfizz "$DESDE" | tail -8; }
registro_sfizz "$DESDE" | grep -q "Could not load the instrument file: $TMP/inst/roto/roto.sfz" \
    && ok "3c: sfizz informó el fallo de carga" || fallo "3c: sfizz no informó el fallo"
python3 -c "import json,sys; e=json.load(open('$RUNDIR/piano-enrutador.json'))['instrumento']; sys.exit(0 if 'Roto' in (e['error'] or '') else 1)" \
    && ok "3c: el error queda en el estado para la interfaz" || fallo "3c: sin texto de error"
python3 -c "import json,sys; sys.exit(0 if json.load(open('$PIANO_PREFERENCIAS'))['instrumento'] == 'wurlitzer' else 1)" \
    && ok "3c: la preferencia no cambia por un fallo" || fallo "3c: preferencia cambiada tras el fallo"

DESDE="$(date '+%Y-%m-%d %H:%M:%S')"
for _ in 1 2; do echo "instrumento siguiente" > "$RUNDIR/piano-enrutador.ctl"; sleep 0.2; done
esperar_inst "listo pianet -" && ok "3c: dos pulsaciones rápidas de F7 llevan al Pianet" || fallo "3c: recorrido rápido: $(est_inst)"
N="$(registro_sfizz "$DESDE" | grep -c "Instrument loaded:")"
[ "$N" -eq 1 ] && ok "3c: solo se cargó el último elegido (1 carga)" || fallo "3c: $N cargas en el recorrido rápido"
systemctl --user is-active --quiet piano-vivo && ok "3c: sfizz sigue vivo tras los cambios" || fallo "3c: sfizz terminó"

# Transposición propia del instrumento (fase 08): las muestras del Hammond están una octava por debajo de su
# tecla; con «transposicion: 12» del catálogo, el La4 tocado (tecla H) debe sonar a ~440 Hz, no a 220.
echo "instrumento ya hammond-drawbar" > "$RUNDIR/piano-enrutador.ctl"
esperar_inst "listo hammond-drawbar -" && ok "3c: carga inmediata desde el menú (instrumento ya) del Hammond" \
    || fallo "3c: el Hammond no cargó: $(est_inst)"
tocar_y_grabar "$TMP/hammond.wav" 35
F_LA4="$(python3 - "$TMP/hammond.wav" <<'EOF'
import sys
import analizar_wav as a
sr, _, c = a.leer_wav(sys.argv[1])
umbral = 10 ** (-40 / 20)
inicio = next((k for k in range(len(c[0])) if abs(c[0][k]) > umbral), None)
f = None if inicio is None else a.frecuencia_fundamental(c, sr, inicio / sr + 0.3, inicio / sr + 0.9, fmin=100)
print(f"{f:.1f}" if f else "nada")
EOF
)"
# La transposición del usuario sigue activa (3b la dejó en +1): la frecuencia esperada la tiene en cuenta.
T_USUARIO="$(python3 -c "import json; print(json.load(open('$RUNDIR/piano-enrutador.json'))['transposicion'])")"
F_ESPERADA="$(awk -v t="$T_USUARIO" 'BEGIN{printf "%.1f", 440 * 2 ^ (t / 12)}')"
awk -v f="$F_LA4" -v e="$F_ESPERADA" 'BEGIN{exit !(f + 0 > e * 0.97 && f + 0 < e * 1.03)}' \
    && ok "3c: el La4 del Hammond suena a $F_LA4 Hz (esperado $F_ESPERADA con transposición $T_USUARIO: octava corregida)" \
    || fallo "3c: el La4 del Hammond suena a $F_LA4 Hz (esperado $F_ESPERADA con transposición $T_USUARIO)"

# 4) Parada ordenada (rápida: al pulsar ESC la consola no debe quedar bloqueada)
T0=$(date +%s)
kill -TERM "$PIANO"; wait "$PIANO" 2>/dev/null; PIANO=""
T=$(( $(date +%s) - T0 ))
[ "$T" -lt 15 ] && ok "4: la parada termina en $T s" || fallo "4: la parada tardó $T s (¿sfizz no termina con SIGTERM?)"
sleep 0.5
[ ! -e "$RUNDIR/piano-vivo.listo" ] && ok "4: marca de listo eliminada" || fallo "4: quedó la marca de listo"
[ -z "$(unidades_vivo)" ] && ok "4: sin unidades piano-vivo" || fallo "4: quedan unidades: $(unidades_vivo)"
[ "$(cat $G)" = "$GOB_INICIAL" ] && ok "4: gobernador restaurado ($GOB_INICIAL)" || fallo "4: gobernador $(cat $G)"
[ "$(afinidad_hilos "$PW")" = "$AFIN_PW_INICIAL" ] && [ ! -e "$RUNDIR/piano-vivo.afinidad-pipewire" ] \
    && ok "4: PipeWire vuelve a sus núcleos ($AFIN_PW_INICIAL) y se borra la marca" \
    || fallo "4: núcleos de PipeWire tras parar: $(afinidad_hilos "$PW")"
[ ! -f "$RUNDIR/piano-vivo.gobernador" ] && ok "4: marca de gobernador eliminada" || fallo "4: quedó la marca de gobernador"
[ ! -e "$RUNDIR/piano-vivo.estado" ] && [ ! -e "$RUNDIR/piano-vivo-fx.ctl" ] && ok "4: estado y FIFO de la reverb eliminados" \
    || fallo "4: quedó el estado o el FIFO de la reverb"
[ ! -e "$RUNDIR/piano-enrutador.json" ] && [ ! -e "$RUNDIR/piano-enrutador.ctl" ] && ok "4: estado y FIFO del enrutador eliminados" \
    || fallo "4: quedaron archivos del enrutador"
[ ! -e "$RUNDIR/piano-vivo.ctl" ] && ok "4: FIFO de sfizz eliminado" || fallo "4: quedó el FIFO de sfizz"
META="$(pw-metadata -n settings 0)"; grep -q "clock.force-quantum' value:'0'" <<<"$META" && ok "4: latencia de PipeWire restaurada" \
    || fallo "4: PipeWire sigue forzado: $(pw-metadata -n settings 0 | grep force-quantum)"
grep -q "Piano detenido" "$TMP/piano.log" && ok "4: lo informa" || fallo "4: no informó la parada"
pgrep -f '^pw-record .*piano-ancla-vivo' >/dev/null && fallo "4: quedó el ancla del modo silencio" \
    || ok "4: ancla del modo silencio detenida"
# 4b) Al volver a arrancar se restauran las preferencias guardadas (reverb 0.45 y latencia 1024)
"$DIR/piano-en-vivo.sh" -s > "$TMP/piano3.log" 2>&1 &
PIANO=$!
esperar_listo || fallo "4b: no quedó listo"
grep -q "quantum 1024" "$TMP/piano3.log" && grep -q "mix=0.45" "$TMP/piano3.log" \
    && ok "4b: arranca con la latencia y la reverb guardadas" || { fallo "4b: no restauró preferencias"; head -5 "$TMP/piano3.log"; }
grep -q "Piano listo: hammond-drawbar" "$TMP/piano3.log" && esperar_inst "listo hammond-drawbar -" \
    && ok "4b: arranca con el último instrumento elegido (Hammond)" || { fallo "4b: instrumento al arrancar: $(est_inst)"; tail -3 "$TMP/piano3.log"; }
kill -TERM "$PIANO"; wait "$PIANO" 2>/dev/null; PIANO=""

# 5) Muerte brusca
"$DIR/piano-en-vivo.sh" -s -p > "$TMP/piano2.log" 2>&1 &
PIANO=$!
esperar_listo || { fallo "5: no quedó listo"; cat "$TMP/piano2.log"; }
kill -9 "$PIANO"; wait "$PIANO" 2>/dev/null; PIANO=""
[ "$(cat $G)" = performance ] && [ -n "$(unidades_vivo)" ] && ok "5: tras kill -9 quedan unidades y performance (situación a recuperar)" \
    || fallo "5: no se reprodujo el estado tras kill -9"
[ "$(afinidad_hilos "$PW")" = "2,3" ] && ok "5: y PipeWire sigue en 2,3 (situación a recuperar)" || fallo "5: PipeWire: $(afinidad_hilos "$PW")"
pgrep -f '^pw-record .*piano-ancla-vivo' >/dev/null && ok "5: y el ancla queda huérfana (situación a recuperar)" \
    || fallo "5: el ancla no sigue tras kill -9"
"$DIR/detener-audio.sh" > "$TMP/d.log" 2>&1 && ok "5: detener-audio.sh termina bien" || { fallo "5: detener-audio falló"; cat "$TMP/d.log"; }
[ -z "$(unidades_vivo)" ] && ok "5: unidades recuperadas" || fallo "5: quedan unidades: $(unidades_vivo)"
pgrep -f '^pw-record .*piano-ancla-vivo' >/dev/null && fallo "5: detener-audio.sh no detuvo el ancla" \
    || ok "5: detener-audio.sh detiene el ancla (después de las unidades)"
[ "$(cat $G)" = "$GOB_INICIAL" ] && ok "5: gobernador recuperado ($GOB_INICIAL)" || fallo "5: gobernador $(cat $G)"
[ "$(afinidad_hilos "$PW")" = "$AFIN_PW_INICIAL" ] && [ ! -e "$RUNDIR/piano-vivo.afinidad-pipewire" ] \
    && ok "5: detener-audio.sh devuelve PipeWire a sus núcleos ($AFIN_PW_INICIAL)" \
    || fallo "5: núcleos de PipeWire tras recuperar: $(afinidad_hilos "$PW")"
rm -f "$RUNDIR/piano-vivo.listo"

# 6) Ningún cliente cayó en toda la prueba (p. ej. SIGSEGV de pipewire-jack al quedarse una salida sin enlaces).
# No cuentan los arranques fallidos de jalv («Failed to connect to audio system»: termina con SIGSEGV y se reintenta).
REG="$(journalctl _UID="$(id -u)" --since "$INICIO_TEST" --no-pager -o cat)"   # mensajes del gestor de servicios del usuario
N_SFIZZ=$(grep -c '^piano-vivo\.service: Main process exited, code=.*status=11/SEGV' <<<"$REG")
N_FX=$(grep -c '^piano-vivo-fx\.service: Main process exited, code=.*status=11/SEGV' <<<"$REG")
N_FX_CONEXION=$(journalctl --user-unit=piano-vivo-fx --since "$INICIO_TEST" --no-pager -o cat | grep -c 'Failed to connect to audio system')
[ "$N_SFIZZ" -eq 0 ] && [ "$N_FX" -le "$N_FX_CONEXION" ] \
    && ok "6: ni sfizz ni la reverb cayeron durante la prueba (arranques de jalv reintentados: $N_FX_CONEXION)" \
    || fallo "6: caídas con SIGSEGV: sfizz $N_SFIZZ, reverb $N_FX (de ellas, arranques fallidos: $N_FX_CONEXION)"

echo
if [ "$FALLOS" -eq 0 ]; then echo "TODAS LAS PRUEBAS PASAN"; else echo "$FALLOS PRUEBA(S) FALLAN"; exit 1; fi
