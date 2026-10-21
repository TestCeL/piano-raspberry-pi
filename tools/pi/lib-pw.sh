# Funciones de apoyo para PipeWire (se cargan con `source`).

# Destinos enlazados a un puerto de salida, según `pw-link -l`. Uno por línea.
# destinos_de PUERTO [TEXTO]: con TEXTO, se usa esa lectura de `pw-link -l` ya hecha (varias consultas, una lectura).
destinos_de() {
    { if [ $# -ge 2 ]; then printf '%s\n' "$2"; else pw-link -l; fi; } | awk -v p="$1" '
        $0 == p { dentro = 1; next }
        /^[^ \t]/ { dentro = 0 }
        dentro && /\|->/ { sub(/^[ \t]*\|->[ \t]*/, ""); print }'
}

# Resume un registro de `pw-top -b` para un nodo: B/Q máximo y medio, y xruns ocurridos en el intervalo.
# Uso: resumir_pwtop NODO ARCHIVO   ->  "B/Q máx 0.42, medio 0.30, xruns 0"  |  "SIN_DATOS"
resumir_pwtop() {
    awk -v c="$1" '
        $NF == c {
            if ($8 ~ /^[0-9.]+$/) { n++; if ($8 + 0 > max) max = $8 + 0; suma += $8 }
            if ($9 ~ /^[0-9]+$/) { if (primero == "") primero = $9; ultimo = $9 }
        }
        END {
            if (n == 0) { print "SIN_DATOS"; exit }
            printf "B/Q máx %.2f, medio %.2f, xruns %d\n", max, suma / n, ultimo - primero
        }' "$2"
}

# ---------------------------------------------------------------------------------------------
# Arranque de clientes JACK y enlaces. Variables globales requeridas por quien hace `source`:
#   DIR (carpeta con pw_puertos.py), RATE, QUANTUM, y el array UNIDADES (unidades a detener al salir).

# Puertos de un nodo: líneas "<in|out> <midi|audio|otro> <nodo:puerto>"
puertos() { pw-dump | python3 "$DIR/pw_puertos.py" "$1"; }

# iniciar_cliente CLIENTE "COMANDO" PATRON_REQUERIDO [REGEX_LISTO] [FIFO_ORDENES]
#   -> deja en $P los puertos del cliente
# COMANDO es un cliente JACK (jalv, sfizz_jack...) que se ejecuta con pw-jack en una unidad de usuario.
# Si se da REGEX_LISTO, además se espera ese texto en su salida (p. ej. sfizz_jack publica los puertos
# ANTES de cargar el instrumento: enviar MIDI antes perdería notas).
# Si se da FIFO_ORDENES, su entrada estándar es ese FIFO abierto en lectura-escritura: nunca ve EOF y
# otros procesos pueden enviarle órdenes (p. ej. a jalv: "mix = 0.5").
# Si el cliente muere ANTES de publicar sus puertos (fallo transitorio al conectar con PipeWire, visto con
# jalv: "Failed to connect to audio system"), se reintenta hasta INTENTOS_CLIENTE veces, avisando y mostrando
# el registro del intento fallido. Una vez publicados los puertos no se reintenta nada.
INTENTOS_CLIENTE="${INTENTOS_CLIENTE:-3}"
iniciar_cliente() {
    local cliente="$1" comando="$2" requerido="$3" listo="${4:-}" fifo="${5:-}" desde lanzador intento murio
    echo "== Iniciando $cliente: $comando"
    # jalv 1.6.6 termina con EOF en stdin y sfizz_jack entra en un bucle al 100 % de CPU:
    # se les da una entrada que nunca se cierra. stdbuf -oL: salida por líneas hacia el journal.
    # Sin "pw-jack -s/-p": esas opciones exportan PIPEWIRE_QUANTUM y FIJAN el bloque del cliente, lo que
    # impediría cambiar la latencia en caliente. Frecuencia y bloque los gobiernan los ajustes globales
    # clock.force-rate / clock.force-quantum que fija quien llama (RATE/QUANTUM).
    if [ -n "$fifo" ]; then
        lanzador="exec pw-jack stdbuf -oL $comando <> '$fifo'"
    else
        lanzador="sleep infinity | exec pw-jack stdbuf -oL $comando"
    fi
    UNIDADES+=("$cliente")
    for intento in $(seq "$INTENTOS_CLIENTE"); do
        systemctl --user stop "$cliente" 2>/dev/null || true
        systemctl --user reset-failed "$cliente" 2>/dev/null || true
        desde="$(date '+%Y-%m-%d %H:%M:%S')"
        systemd-run --user --quiet --unit="$cliente" --collect /bin/sh -c "$lanzador"
        P=""
        murio=0
        for _ in $(seq 120); do
            P="$(puertos "$cliente" || true)"
            if grep -q "$requerido" <<<"$P" && grep -q '^out audio' <<<"$P"; then break; fi
            systemctl --user is-active --quiet "$cliente" || { murio=1; break; }
            sleep 0.5
        done
        [ "$murio" = 1 ] || break
        if [ "$intento" -ge "$INTENTOS_CLIENTE" ]; then
            echo "ERROR: $cliente terminó al arrancar ($intento intentos)" >&2
            journalctl --user-unit="$cliente" --since "$desde" --no-pager | tail -20 >&2
            exit 1
        fi
        echo "AVISO: $cliente terminó al arrancar (intento $intento de $INTENTOS_CLIENTE); se reintenta:" >&2
        journalctl --user-unit="$cliente" --since "$desde" --no-pager -o cat | tail -5 | sed 's/^/   | /' >&2
        sleep 1
    done
    grep -q '^out audio' <<<"$P" || { echo "ERROR: $cliente no publicó sus puertos en 60 s" >&2; exit 1; }
    [ -n "$listo" ] || return 0
    local salida t0
    t0=$(date +%s)
    for _ in $(seq 360); do
        salida="$(journalctl --user-unit="$cliente" --since "$desde" --no-pager -o cat 2>/dev/null || true)"
        if grep -qE "$listo" <<<"$salida"; then
            echo "   listo en $(( $(date +%s) - t0 )) s ($(grep -m1 -E "$listo" <<<"$salida"))"
            return 0
        fi
        grep -qE "Could not load|Can't load" <<<"$salida" && { echo "ERROR: $cliente no pudo cargar:" >&2; tail -5 <<<"$salida" >&2; exit 1; }
        systemctl --user is-active --quiet "$cliente" || { echo "ERROR: $cliente terminó durante la carga" >&2; exit 1; }
        sleep 0.5
    done
    echo "ERROR: $cliente no terminó de cargar en 180 s" >&2
    exit 1
}

enlazar() { pw-link "$1" "$2" 2>/dev/null || destinos_de "$1" | grep -qxF "$2" || { echo "ERROR: no se pudo enlazar $1 -> $2" >&2; exit 1; }; }

# ---------------------------------------------------------------------------------------------
# Enlaces sin dejar NUNCA una salida sin destino mientras su cliente procesa audio.
# pipewire-jack 1.2.7 (el de la Pi) libera los búferes de un puerto que pierde su último enlace sin esperar al ciclo
# de audio en curso: si el cliente (sfizz, jalv) está escribiendo en ellos, cae con SIGSEGV. Se reprodujo en la fase
# 08 enlazando y desenlazando un grabador (fallo en el ciclo 140; con un ancla, 319 ciclos sin fallo). Está corregido
# en PipeWire 1.6 («loop: add method to run a function with the lock»), que no está publicado para la Pi.
# Por eso: primero se enlaza lo nuevo y después se quita lo viejo, y en silencio las salidas quedan en un ancla.

_en_lista() { local x="$1" y; shift; for y in "$@"; do [ "$x" = "$y" ] && return 0; done; return 1; }

# redirigir SALIDA DESTINO [DESTINO...]: deja SALIDA enlazada exactamente a esos destinos ("conectar antes de cortar").
# Si no puede enlazar, termina con error sin haber quitado nada.
redirigir() {
    local s="$1" o
    shift
    for o in "$@"; do enlazar "$s" "$o"; done
    while read -r o; do
        if [ -n "$o" ] && ! _en_lista "$o" "$@"; then pw-link -d "$s" "$o" || true; fi
    done < <(destinos_de "$s")
    [ "$(destinos_de "$s" | sort -u)" = "$(printf '%s\n' "$@" | sort -u)" ] \
        || { echo "ERROR: no se pudo dejar $s enlazado solo a: $*" >&2; exit 1; }
}

# redirigir_par S_IZQ S_DER D_IZQ D_DER: el par estéreo de siempre; S_DER o D_DER vacíos = mono (como ${X[1]:-${X[0]}})
redirigir_par() {
    local s0="$1" s1="${2:-$1}" d0="$3" d1="${4:-$3}"
    if [ "$s0" = "$s1" ]; then
        redirigir "$s0" "$d0" "$d1"
    else
        redirigir "$s0" "$d0"
        redirigir "$s1" "$d1"
    fi
}

# iniciar_ancla NODO S_IZQ [S_DER]: un grabador a /dev/null (nodo NODO) pasa a ser el ÚNICO destino de esas salidas.
# Así quedan aisladas de la G1 (silencio) sin quedarse sin enlaces, y los grabadores de prueba pueden ir y venir.
# Deja el PID en ANCLA_PID y sus dos entradas en ANCLA_ENTRADAS (para rehacer los enlaces si se pierden).
# detener_ancla lo para, y hay que llamarla DESPUÉS de detener los clientes enlazados.
# 8>&-: no hereda el bloqueo de instancia única de piano-en-vivo.sh (si el script muriera, no lo dejaría tomado).
ANCLA_PID=""
ANCLA_ENTRADAS=()
iniciar_ancla() {
    local nodo="$1" g="" ent
    pw-record --target 0 -P "{ node.name = \"$nodo\" }" --rate "$RATE" --channels 2 --format f32 /dev/null 8>&- &
    ANCLA_PID=$!
    for _ in $(seq 80); do
        g="$(puertos "$nodo" || true)"
        [ "$(grep -c '^in audio' <<<"$g")" -ge 2 ] && break
        sleep 0.25
    done
    mapfile -t ent < <(awk '$1=="in" && $2=="audio"' <<<"$g" | cut -d' ' -f3-)
    [ "${#ent[@]}" -ge 2 ] || { echo "ERROR: el ancla $nodo no publicó sus entradas en 20 s" >&2; exit 1; }
    ANCLA_ENTRADAS=("${ent[0]}" "${ent[1]}")
    redirigir_par "$2" "${3:-}" "${ent[0]}" "${ent[1]}"
}
detener_ancla() {
    [ -n "$ANCLA_PID" ] || return 0
    kill -TERM "$ANCLA_PID" 2>/dev/null || true
    wait "$ANCLA_PID" 2>/dev/null || true
    ANCLA_PID=""
}
