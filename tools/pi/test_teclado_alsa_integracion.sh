#!/bin/bash
# Prueba de integración EN LA RASPBERRY: teclado_piano.py -> secuenciador ALSA -> aseqdump / PipeWire.
# No suena nada (no hay sintetizador conectado). Usa eventos de teclado simulados (no captura el teclado).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"   # los fragmentos de Python de la prueba importan los módulos de esta carpeta
TMP="$(mktemp -d)"
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
trap 'kill "${DUMP:-}" "${PROG:-}" 2>/dev/null; rm -rf "$TMP"' EXIT

# Eventos: A (do4) pulsar/soltar, pedal, W (do#4) pulsar, ESC (debe apagar do#4 y levantar el pedal).
python3 - "$TMP/eventos.bin" <<'EOF'
import sys
import teclado_piano as tp
ev = [(30, 1), (30, 2), (30, 0), (57, 1), (17, 1), (1, 1)]
open(sys.argv[1], "wb").write(b"".join(tp.empaquetar_evento(c, v) for c, v in ev))
EOF

python3 "$DIR/teclado_piano.py" --entrada-prueba "$TMP/eventos.bin" --interfaz linea \
        --pausa-inicial 5 --nombre-cliente "Teclado Prueba" > "$TMP/prog.log" 2>&1 &
PROG=$!
for _ in $(seq 20); do aconnect -i | grep -q "Teclado Prueba" && break; sleep 0.1; done
aconnect -i | grep -q "Teclado Prueba" && ok "el cliente ALSA 'Teclado Prueba' existe" || fallo "no apareció el cliente ALSA"
sleep 0.5
pw-link -o | grep -q "Midi-Bridge:Teclado Prueba" && ok "PipeWire expone el puerto (Midi-Bridge:Teclado Prueba…)" \
                                                  || fallo "PipeWire no expone el puerto"
aseqdump -p "Teclado Prueba:0" > "$TMP/dump.log" 2>&1 &
DUMP=$!
wait "$PROG"; RC=$?
sleep 0.3
kill "$DUMP" 2>/dev/null; wait "$DUMP" 2>/dev/null
[ "$RC" -eq 0 ] && ok "teclado_piano.py terminó bien (ESC)" || { fallo "rc=$RC"; cat "$TMP/prog.log"; }
grep -q "Salir (ESC)" "$TMP/prog.log" && ok "informa la salida por ESC" || fallo "no informó la salida"

# Secuencia esperada en aseqdump (canal 0):
PATRON="(Note on|Note off|Control change) +[0-9]+, (note [0-9]+(, velocity [0-9]+)?|controller [0-9]+, value [0-9]+)"
OBT="$(grep -hoE "$PATRON" "$TMP/dump.log" | sed -E 's/ +/ /g')"
ESP="Note on 0, note 60, velocity 80
Note off 0, note 60
Control change 0, controller 64, value 127
Note on 0, note 61, velocity 80
Note off 0, note 61
Control change 0, controller 64, value 0"
# aseqdump puede mostrar "Note off ..., velocity 0": se normaliza quitando la velocidad de los note off
OBT="$(sed -E 's/(Note off 0, note [0-9]+), velocity [0-9]+/\1/' <<<"$OBT")"
if [ "$OBT" == "$ESP" ]; then
    ok "secuencia MIDI exacta: on/off do4, pedal abajo, on do#4, ESC -> off do#4 y pedal arriba"
else
    fallo "secuencia MIDI distinta"; echo "--- esperado:"; echo "$ESP"; echo "--- obtenido:"; echo "$OBT"; echo "--- dump:"; cat "$TMP/dump.log"
fi
grep -q "note 60, velocity 80" "$TMP/dump.log" && [ "$(grep -c 'note 60, velocity 80' "$TMP/dump.log")" -eq 1 ] \
    && ok "la repetición automática no generó notas extra" || fallo "repetición automática duplicó notas"
aconnect -i | grep -q "Teclado Prueba" && fallo "el cliente ALSA sigue vivo" || ok "el cliente ALSA se cerró al salir"

# F12 (fase 11): pide confirmar; A no suena mientras pregunta; S confirma -> código 10 (piano-teclado.sh apaga la Pi)
python3 - "$TMP/apagar.bin" <<'EOF'
import sys
import teclado_piano as tp
ev = [(30, 1), (tp.KEY_F12, 1), (17, 1), (tp.KEY_S, 1)]
open(sys.argv[1], "wb").write(b"".join(tp.empaquetar_evento(c, v) for c, v in ev))
EOF
python3 "$DIR/teclado_piano.py" --entrada-prueba "$TMP/apagar.bin" --interfaz linea --sin-controles \
        --nombre-cliente "Teclado Prueba" > "$TMP/apagar.log" 2>&1; RC=$?
[ "$RC" -eq 10 ] && grep -q "Apagar (F12)" "$TMP/apagar.log" && ok "F12 + S: termina con el código 10 (apagar)" \
    || { fallo "F12 + S: rc=$RC"; cat "$TMP/apagar.log"; }

echo
if [ "$FALLOS" -eq 0 ]; then echo "TODAS LAS PRUEBAS PASAN"; else echo "$FALLOS PRUEBA(S) FALLAN"; exit 1; fi
