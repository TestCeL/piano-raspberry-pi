#!/bin/bash
# Pruebas de lib-pw.sh con datos sintéticos (sin PipeWire). Uso: bash test_lib_pw.sh
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib-pw.sh
source "$DIR/lib-pw.sh"

FALLOS=0
afirmar() {  # afirmar DESCRIPCION ESPERADO OBTENIDO
    if [ "$2" == "$3" ]; then echo "ok   - $1"; else echo "FALLO - $1"; echo "      esperado: [$2]"; echo "      obtenido: [$3]"; FALLOS=$((FALLOS + 1)); fi
}

# --- destinos_de con una salida simulada de `pw-link -l`
pw-link() {
    [ "$1" = "-l" ] || return 1
    cat <<'EOF'
Midi-Bridge:Midi Through:(capture_0) Midi Through Port-0
  |-> piano:in
piano:audio_out_1
  |-> alsa_output.usb-G1:playback_FL
  |-> otro:in_1
piano:audio_out_2
  |-> alsa_output.usb-G1:playback_FR
alsa_output.usb-G1:playback_FL
  |<- piano:audio_out_1
EOF
}
afirmar "dos destinos de audio_out_1" $'alsa_output.usb-G1:playback_FL\notro:in_1' "$(destinos_de piano:audio_out_1)"
afirmar "un destino de audio_out_2" "alsa_output.usb-G1:playback_FR" "$(destinos_de piano:audio_out_2)"
afirmar "puerto con espacios y paréntesis" "piano:in" "$(destinos_de 'Midi-Bridge:Midi Through:(capture_0) Midi Through Port-0')"
afirmar "los enlaces de entrada (|<-) no cuentan" "" "$(destinos_de alsa_output.usb-G1:playback_FL)"
afirmar "puerto inexistente" "" "$(destinos_de no:existe)"
LECTURA="$(pw-link -l)"
unset -f pw-link
pw-link() { echo "NO DEBE LLAMARSE" >&2; return 1; }
afirmar "con una lectura ya hecha: no vuelve a llamar a pw-link" $'alsa_output.usb-G1:playback_FL\notro:in_1' \
    "$(destinos_de piano:audio_out_1 "$LECTURA" 2>&1)"
afirmar "con una lectura ya hecha: puerto con espacios y paréntesis" "piano:in" \
    "$(destinos_de 'Midi-Bridge:Midi Through:(capture_0) Midi Through Port-0' "$LECTURA" 2>&1)"
afirmar "con una lectura vacía (pw-link falló): ningún destino" "" "$(destinos_de piano:audio_out_1 "" 2>&1)"
unset -f pw-link

# --- resumir_pwtop con un registro simulado de `pw-top -b`
TMP="$(mktemp)"
cat > "$TMP" <<'EOF'
S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME
R   34    256  44100   0.1us   0.2us  0.01  0.02    3    S16LE 2 44100 alsa_output.usb-G1
R   80      0      0   1.0ms   1.5ms  0.17  0.26    5   F32LE 2 44100  + piano
S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME
R   80      0      0   1.0ms   3.4ms  0.17  0.59    5   F32LE 2 44100  + piano
R   81      0      0   1.0ms   5.0ms  0.17  0.99    0   F32LE 2 44100  + piano-otro
S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME
R   80      0      0     ---     ---   ---   ---    7                  + piano
R   80      0      0   1.0ms   2.0ms  0.17  0.35    7   F32LE 2 44100  + piano
EOF
afirmar "máximo, media y xruns del intervalo" "B/Q máx 0.59, medio 0.40, xruns 2" "$(resumir_pwtop piano "$TMP")"
afirmar "nodo sin datos" "SIN_DATOS" "$(resumir_pwtop no-existe "$TMP")"
afirmar "no confunde nodos con prefijo común" "B/Q máx 0.99, medio 0.99, xruns 0" "$(resumir_pwtop piano-otro "$TMP")"
rm -f "$TMP"

# --- iniciar_cliente: reintento si el cliente muere antes de publicar sus puertos (systemd y PipeWire simulados)
SIM="$(mktemp -d)"
intentos() { cat "$SIM/n" 2>/dev/null || echo 0; }
systemd-run() { echo $(( $(intentos) + 1 )) > "$SIM/n"; }
systemctl() { case "$2" in is-active) [ "$(intentos)" -gt "$FALLAN" ] ;; *) return 0 ;; esac; }
puertos() { [ "$(intentos)" -gt "$FALLAN" ] && printf 'in midi cli:midi_in
out audio cli:out_1
'; return 0; }
journalctl() { echo "Failed to connect to audio system"; }
sleep() { :; }
UNIDADES=()
probar() {  # probar FALLAN -> deja SALIDA y RC
    FALLAN=$1; rm -f "$SIM/n"
    SALIDA="$(iniciar_cliente cli "jalv -x -n cli x" '^in midi' 2>&1)"; RC=$?
}
probar 0
afirmar "sin fallos: un solo intento y sin avisos" "0 1 0" "$RC $(intentos) $(grep -c AVISO <<<"$SALIDA")"
probar 1
afirmar "un fallo al arrancar se reintenta y el cliente arranca" "0 2" "$RC $(intentos)"
afirmar "avisa del reintento" "1" "$(grep -c 'AVISO: cli terminó al arrancar (intento 1 de 3); se reintenta' <<<"$SALIDA")"
afirmar "muestra el registro del intento fallido" "1" "$(grep -c '   | Failed to connect to audio system' <<<"$SALIDA")"
probar 2
afirmar "dos fallos: arranca al tercer intento" "0 3" "$RC $(intentos)"
probar 3
afirmar "tres fallos: error y código 1, sin más intentos" "1 3 1" "$RC $(intentos) $(grep -c 'ERROR: cli terminó al arrancar (3 intentos)' <<<"$SALIDA")"
unset -f systemd-run systemctl puertos journalctl sleep
rm -rf "$SIM"

# --- redirigir / redirigir_par / ancla con enlaces simulados (archivo "salida<TAB>destino"). Invariante que se vigila
# en cada desenlace: una salida que tenía enlaces NUNCA se queda sin ninguno (pipewire-jack 1.2.7 haría caer al cliente).
SIM="$(mktemp -d)"
TAB=$'\t'
pw-link() {
    case "$1" in
        -l) awk -F'\t' '{ d[$1] = d[$1] "  |-> " $2 "\n" } END { for (s in d) printf "%s\n%s", s, d[s] }' "$SIM/enlaces" ;;
        -d) echo "quitar $2 -> $3" >> "$SIM/ops"
            [ -n "${NO_QUITAR:-}" ] && return 1
            grep -vxF "$2$TAB$3" "$SIM/enlaces" > "$SIM/e2"; mv "$SIM/e2" "$SIM/enlaces"
            awk -F'\t' -v s="$2" '$1 == s { f = 1 } END { exit !f }' "$SIM/enlaces" || echo "SIN ENLACES $2" >> "$SIM/ops" ;;
        *)  echo "enlazar $1 -> $2" >> "$SIM/ops"
            [ "$2" = "no:existe" ] && return 1
            grep -qxF "$1$TAB$2" "$SIM/enlaces" && return 1      # como pw-link: falla si el enlace ya existe
            printf '%s\t%s\n' "$1" "$2" >> "$SIM/enlaces" ;;
    esac
}
inicial() {   # inicial "salida|destino" ...  (sin argumentos: ningún enlace)
    local e
    : > "$SIM/enlaces"; : > "$SIM/ops"
    for e in "$@"; do tr '|' '\t' <<<"$e" >> "$SIM/enlaces"; done
}
destinos() { destinos_de "$1" | sort | tr '\n' ' '; }
ops() { tr '\n' ';' < "$SIM/ops"; }

inicial "sfizz:out_1|g1:FL"
redirigir sfizz:out_1 fx:in_1
afirmar "redirigir: primero enlaza el destino nuevo y después quita el viejo" \
    "enlazar sfizz:out_1 -> fx:in_1;quitar sfizz:out_1 -> g1:FL;" "$(ops)"
afirmar "redirigir: queda solo el destino pedido" "fx:in_1 " "$(destinos sfizz:out_1)"
inicial "s:1|fx:in_1" "s:1|otro:x" "s:1|otro:y"
redirigir s:1 fx:in_1
afirmar "redirigir: conserva el destino que ya estaba y quita los demás" "fx:in_1 " "$(destinos s:1)"
afirmar "redirigir: nunca deja la salida sin enlaces" "0" "$(grep -c 'SIN ENLACES' "$SIM/ops")"
inicial "s:1|g1:FL"
redirigir s:1 a:1 a:2
afirmar "redirigir: varios destinos (fuente mono a dos entradas)" "a:1 a:2 " "$(destinos s:1)"
inicial "s:1|g1:FL"
SALIDA="$( (redirigir s:1 no:existe) 2>&1 )"; RC=$?
afirmar "redirigir: si no puede enlazar, error y código 1" "1 1" "$RC $(grep -c 'ERROR: no se pudo enlazar s:1 -> no:existe' <<<"$SALIDA")"
afirmar "redirigir: ...sin haber quitado el enlace que sonaba" "g1:FL |0" "$(destinos s:1)|$(grep -c '^quitar' "$SIM/ops")"
inicial "s:1|g1:FL"
SALIDA="$( (NO_QUITAR=1 redirigir s:1 fx:in_1) 2>&1 )"; RC=$?
afirmar "redirigir: si no puede quitar un enlace viejo, error y código 1" "1 1" \
    "$RC $(grep -c 'ERROR: no se pudo dejar s:1 enlazado solo a: fx:in_1' <<<"$SALIDA")"

inicial "p:L|g1:FL" "p:R|g1:FR"
redirigir_par p:L p:R fx:in_L fx:in_R
afirmar "redirigir_par estéreo: izquierda con izquierda y derecha con derecha" "fx:in_L |fx:in_R " "$(destinos p:L)|$(destinos p:R)"
afirmar "redirigir_par estéreo: nunca deja una salida sin enlaces" "0" "$(grep -c 'SIN ENLACES' "$SIM/ops")"
inicial
redirigir_par p:M "" fx:in_L fx:in_R
afirmar "redirigir_par con fuente mono: a las dos entradas" "fx:in_L fx:in_R " "$(destinos p:M)"
inicial
redirigir_par p:L p:R fx:in ""
afirmar "redirigir_par con destino mono: las dos salidas a la misma entrada" "fx:in |fx:in " "$(destinos p:L)|$(destinos p:R)"

# Ancla: grabador simulado (un proceso real que se puede detener) y sus puertos
RATE=44100
pw-record() { echo "$*" > "$SIM/pwrecord"; echo "$BASHPID" >> "$SIM/pids"; exec sleep 30; }
puertos() { [ "$1" = "piano-ancla-prueba-x" ] && printf 'in audio %s:input_FL\nin audio %s:input_FR\n' "$1" "$1"; return 0; }
inicial "p:L|g1:FL" "p:R|g1:FR"
iniciar_ancla piano-ancla-prueba-x p:L p:R
afirmar "ancla: las salidas quedan enlazadas solo al ancla (aisladas de la G1)" \
    "piano-ancla-prueba-x:input_FL |piano-ancla-prueba-x:input_FR " "$(destinos p:L)|$(destinos p:R)"
afirmar "ancla: al aislar, ninguna salida se queda sin enlaces" "0" "$(grep -c 'SIN ENLACES' "$SIM/ops")"
afirmar "ancla: grabador nulo con su nombre de nodo" "1 1" \
    "$(grep -c 'node.name = "piano-ancla-prueba-x"' "$SIM/pwrecord") $(grep -c '/dev/null$' "$SIM/pwrecord")"
afirmar "ancla: deja sus entradas en ANCLA_ENTRADAS (para rehacer los enlaces si se pierden)" \
    "piano-ancla-prueba-x:input_FL piano-ancla-prueba-x:input_FR" "${ANCLA_ENTRADAS[*]}"
kill -0 "$ANCLA_PID" 2>/dev/null && VIVA=1 || VIVA=0
PID_ANCLA="$ANCLA_PID"
detener_ancla
kill -0 "$PID_ANCLA" 2>/dev/null && VIVA_DESPUES=1 || VIVA_DESPUES=0
afirmar "ancla: en marcha hasta detener_ancla, que la termina" "1 0 []" "$VIVA $VIVA_DESPUES [$ANCLA_PID]"
inicial "p:M|g1:FL"
iniciar_ancla piano-ancla-prueba-x p:M
afirmar "ancla con una sola salida (mono): a las dos entradas del ancla" \
    "piano-ancla-prueba-x:input_FL piano-ancla-prueba-x:input_FR " "$(destinos p:M)"
detener_ancla
sleep() { :; }
inicial "p:L|g1:FL"
SALIDA="$( (iniciar_ancla piano-ancla-sin-puertos p:L p:R; echo "siguió") 2>&1 )"; RC=$?
afirmar "ancla sin puertos: error y código 1, sin tocar los enlaces" "1 1 0 g1:FL " \
    "$RC $(grep -c 'ERROR: el ancla piano-ancla-sin-puertos no publicó sus entradas' <<<"$SALIDA") $(grep -c siguió <<<"$SALIDA") $(destinos p:L)"
while read -r p; do kill "$p" 2>/dev/null; done < "$SIM/pids"   # el grabador simulado del caso fallido
unset -f pw-link pw-record puertos sleep
rm -rf "$SIM"

echo
if [ "$FALLOS" -eq 0 ]; then echo "TODAS LAS PRUEBAS PASAN"; else echo "$FALLOS PRUEBA(S) FALLAN"; exit 1; fi
