#!/bin/bash
# Experimento (NO forma parte de ejecutar-pruebas.sh: dura minutos) del fallo de pipewire-jack 1.2.7 visto en la fase
# 08: cuando un puerto de salida pierde su ÚLTIMO enlace, sus búferes se liberan sin esperar al ciclo de audio en
# curso, y el cliente JACK que estaba escribiendo en ellos cae con SIGSEGV (sfizz: process -> Synth::renderBlock ->
# EffectBus::mixOutputsTo). Corregido en PipeWire 1.6 (commit f7fdafc2, «loop: add method to run a function with the
# lock»); la Pi tiene 1.2.7 (archive.raspberrypi.com). Silencioso: sfizz nunca se enlaza a la G1.
#   sin-ancla: un grabador se enlaza y desenlaza de las salidas de sfizz, que pasan de 1 a 0 enlaces -> se espera el
#              fallo (2026-10-20: SIGSEGV en el ciclo 140, a los 87 s). Con PipeWire >= 1.6 NO debería fallar.
#   con-ancla: igual, pero con el ancla de lib-pw.sh (iniciar_ancla) enlazada todo el tiempo -> no debe fallar
#              (2026-10-20: 319 ciclos en 200 s sin fallo).
# Comprobar antes que el piano no está en uso. Uso: experimento_carrera_enlaces.sh sin-ancla|con-ancla [SEGUNDOS]
set -u
MODO="${1:?Uso: $0 sin-ancla|con-ancla [SEGUNDOS]}"; DUR="${2:-180}"
case "$MODO" in sin-ancla|con-ancla) ;; *) echo "Modo desconocido: $MODO" >&2; exit 2 ;; esac
DIR="$(cd "$(dirname "$0")" && pwd)"
SFIZZ="${SFIZZ:-$HOME/piano/bin/sfizz_jack}"
RATE=44100
T="$(mktemp -d /tmp/carrera-enlaces.XXXX)"
U=piano-prueba-carrera
FIFO="$T/ordenes"
NODO_V=piano-grabacion-carrera
# shellcheck source=lib-pw.sh
source "$DIR/lib-pw.sh"
NOTAS=""; GRAB=""
fin() {
    [ -n "$NOTAS" ] && kill "$NOTAS" 2>/dev/null
    pkill -f "^aplaymidi -p 14:0 $T" 2>/dev/null
    [ -n "$GRAB" ] && kill -INT "$GRAB" 2>/dev/null
    systemctl --user stop "$U" 2>/dev/null
    detener_ancla
    systemctl --user reset-failed "$U" 2>/dev/null
    rm -rf "$T"
}
trap fin EXIT

python3 - "$T" "$DIR" <<'EOF'
import math, os, struct, sys, wave
d = sys.argv[1]
with wave.open(os.path.join(d, "seno.wav"), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 44100)))
                           for i in range(3 * 44100)))
open(os.path.join(d, "a.sfz"), "w").write("<region> sample=seno.wav lokey=0 hikey=127 pitch_keycenter=69 amp_veltrack=0\n")
sys.path.insert(0, sys.argv[2])
import generar_midis_prueba as g
p = g.Pista()
for k in range(240):                       # notas solapadas: sfizz siempre está renderizando voces
    p.nota(k * g.SEGUNDO // 8, 48 + (k % 24), 100, g.SEGUNDO)
g.escribir_smf(os.path.join(d, "notas.mid"), p)
EOF
mkfifo -m 600 "$FIFO"
systemctl --user stop "$U" 2>/dev/null; systemctl --user reset-failed "$U" 2>/dev/null
systemd-run --user --quiet --unit="$U" -p WorkingDirectory="$T" /bin/sh -c \
    "exec pw-jack stdbuf -oL $SFIZZ --client_name $U --num_voices 32 --sample_quality 1 '$T/a.sfz' <> '$FIFO'"
for _ in $(seq 60); do [ "$(puertos "$U" | grep -c '^out audio')" -ge 2 ] && break; sleep 0.5; done
sleep 1
P="$(puertos "$U")"
mapfile -t SAL < <(awk '$1=="out" && $2=="audio"' <<<"$P" | cut -d' ' -f3-)
MIDI_IN="$(awk '$1=="in" && $2=="midi"' <<<"$P" | head -1 | cut -d' ' -f3-)"
[ "${#SAL[@]}" -ge 2 ] && [ -n "$MIDI_IN" ] || { echo "ERROR: sfizz no publicó sus puertos" >&2; exit 1; }
pw-link "Midi-Bridge:Midi Through:(capture_0) Midi Through Port-0" "$MIDI_IN" 2>/dev/null
if [ "$MODO" = con-ancla ]; then
    iniciar_ancla piano-ancla-prueba-carrera "${SAL[0]}" "${SAL[1]}"
else
    for s in "${SAL[@]}"; do while read -r d; do [ -n "$d" ] && pw-link -d "$s" "$d"; done < <(destinos_de "$s"); done
fi
pw-record --target 0 -P "{ node.name = \"$NODO_V\" }" --rate "$RATE" --channels 2 --format f32 /dev/null &
GRAB=$!
for _ in $(seq 40); do [ "$(puertos "$NODO_V" | grep -c '^in audio')" -ge 2 ] && break; sleep 0.25; done
mapfile -t ENT < <(puertos "$NODO_V" | awk '$1=="in" && $2=="audio"' | cut -d' ' -f3-)
[ "${#ENT[@]}" -ge 2 ] || { echo "ERROR: el grabador no publicó sus entradas" >&2; exit 1; }
( while :; do aplaymidi -p 14:0 "$T/notas.mid" 2>/dev/null; done ) &
NOTAS=$!

DESDE="$(date '+%Y-%m-%d %H:%M:%S')"
inicio=$(date +%s); fin_t=$(( inicio + DUR )); n=0
while [ "$(date +%s)" -lt "$fin_t" ]; do
    systemctl --user is-active --quiet "$U" || break
    n=$((n + 1))
    pw-link "${SAL[0]}" "${ENT[0]}" 2>/dev/null; pw-link "${SAL[1]}" "${ENT[1]}" 2>/dev/null
    sleep 0.$((RANDOM % 3 + 1))
    pw-link -d "${SAL[0]}" "${ENT[0]}" 2>/dev/null; pw-link -d "${SAL[1]}" "${ENT[1]}" 2>/dev/null
    sleep 0.$((RANDOM % 3 + 1))
done
dur=$(( $(date +%s) - inicio ))
if systemctl --user is-active --quiet "$U"; then
    echo "$MODO: SIN FALLO tras $n ciclos de enlace en $dur s"
else
    echo "$MODO: FALLO de sfizz en el ciclo $n, a los $dur s:"
    journalctl --user-unit="$U" --since "$DESDE" --no-pager -o cat | grep -E "status=|signal" | tail -2
    exit 1
fi
