#!/bin/bash
# Descarga, verifica y extrae en la Raspberry los instrumentos SFZ del catálogo (fases 07, 08 y 09).
# Cada origen está FIJADO: se instalan exactamente las muestras que se midieron (niveles, afinación, pedal).
#   tar  repositorio de github.com/sfzinstruments: tar.gz de un COMMIT; se comprueba el commit que lleva dentro
#   txz  archivo .tar.xz publicado por FreePats: se comprueba su SHA-256
#   7z   archivo .7z publicado por FreePats (Upright KW): SHA-256; necesita 7z (paquete p7zip-full)
#   git  solo algunas carpetas de un repositorio git grande (clon parcial + sparse checkout) fijado a un commit:
#        git verifica cada archivo por su hash; si la rama ya no apunta a ese commit, se detiene.
# Una descarga que no cuadra se borra y se detiene todo; lo ya instalado de ese instrumento no se toca (se extrae en
# CARPETA.part y solo al final reemplaza a la anterior). Después de vsco2 genera el ensemble de cuerdas
# (generar_cuerdas.py). Reutiliza las descargas existentes (también las de versiones anteriores de este script, por
# rama, si contienen el commit fijado). Registra tamaño y SHA-256 o commit en MANIFIESTO-descargas.txt.
# El Softify Piano (Pianobook, requiere cuenta) se instala aparte: python3 instalar_softify.py ARCHIVO.zip
#
# Uso: descargar-instrumentos.sh [--forzar] [id ...]   (sin ids: todos; con 7z ausente, el Upright se omite con aviso)
#   Lo ya instalado desde el mismo origen fijado (según el manifiesto) se salta; --forzar lo reinstala.
# Variables: PIANO_DESCARGAS (~/piano/descargas), PIANO_INSTRUMENTOS (~/piano/instrumentos),
#            PIANO_ORIGENES (archivo con otras líneas de origen; pruebas), PIANO_CODELOAD (base de los tar.gz)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DESCARGAS="${PIANO_DESCARGAS:-$HOME/piano/descargas}"
DESTINO="${PIANO_INSTRUMENTOS:-$HOME/piano/instrumentos}"
CODELOAD="${PIANO_CODELOAD:-https://codeload.github.com/sfzinstruments}"
MANIFIESTO="$DESTINO/MANIFIESTO-descargas.txt"
# tipo | id | origen | fijado | carpeta (opcional; por defecto, el id)
#   tar: origen = repositorio de sfzinstruments, fijado = commit
#   txz, 7z: origen = dirección, fijado = SHA-256 del archivo
#   git: origen = dirección, fijado = rama@commit:carpeta1;carpeta2;...
ORIGENES="tar|headroom|BengtNilsson.HeadroomPiano|2a7df3f7252227a3484202c1d61bc1bfe352a971|
tar|maestro|MatsHelgesson.MaestroConcertGrandPiano|717078b450eccc4a7733755f4b5973426ebc23e9|
tar|splendid|SplendidGrandPiano|1c595d827b7fd7f0be3134aaed0f90b3662a09cf|
tar|osiris|Osiris_Piano|18c6afccb60cff458edbf7c394571783e074e1e9|
tar|rhodes|jlearman.jRhodes3d|aea5b8d3e11e2f7102593789a4e0a0e41b30271a|
tar|epianos|GregSullivan.E-Pianos|8c3e581acda3594b553948ff0222d4f84a698376|
txz|salamander|https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPianoV3+20161209_44khz16bit.tar.xz|58750eb1366761e187f71ddb9b932355ea894d28ec4331e74ab8acb44c819936|SalamanderGrandPianoV3_44.1khz16bit
7z|upright|https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-SFZ+FLAC-20220221.7z|3a66da3b25a2fd9499d90bcf09f1aee4431825796e249361b48af59b1201e703|
txz|hammond-drawbar|https://freepats.zenvoid.org/Organ/DrawbarOrganEmulation/DrawbarOrganEmulation-SFZ-20190712.tar.xz|e2da18b0a4d13be7020037e18e4a719387433357e7603d0773990e794dcf5d0f|
txz|hammond-rock|https://freepats.zenvoid.org/Organ/RockOrganEmulation/RockOrganEmulation-SFZ-20190715.tar.xz|07321d9498dc31982c44ea9483919df3f426e3d392a15bb2947b0e3fe247f718|
txz|hammond-percusivo|https://freepats.zenvoid.org/Organ/PercussiveOrganEmulation/PercussiveOrganEmulation-SFZ-20190715.tar.xz|c4841f2e7f352692cf14a85a96bd1f40a9ea7a9e2a9ce3512606885d000978c8|
git|vcsl|https://github.com/sgossner/VCSL|sfz@dfcf4a4918771eee884b96ad4493de82ef84daf6:Aerophones/Edge-blown Aerophones/Pipe Organ;Chordophones/Zithers/Harpsichord, Flemish;Electrophones/TX81Z/FM Piano;Idiophones/Struck Idiophones/Vibraphone;Chordophones/Composite Chordophones/Concert Harp;Idiophones/Struck Idiophones/Marimba;Aerophones/Reed Aerophones/Tenor Saxophone|
git|vsco2|https://github.com/sgossner/VSCO-2-CE|SFZ@6dd651d55dde97fd4028699be9d4481f26917891:Strings/Violin Section/susVib;Strings/Viola Section/susvib;Strings/Cello Section/susvib;Strings/Solo Contrabass/SusVib|"
[ -z "${PIANO_ORIGENES:-}" ] || ORIGENES="$(cat "$PIANO_ORIGENES")"

FORZAR=0
PEDIDOS=()
for a in "$@"; do
    if [ "$a" = --forzar ]; then FORZAR=1; else PEDIDOS+=("$a"); fi
done
for p in "${PEDIDOS[@]}"; do
    grep -q "^[a-z0-9]*|$p|" <<<"$ORIGENES" || { echo "ERROR: no hay ningún instrumento '$p' para descargar" >&2; exit 2; }
done
quiero() { local x; for x in "${PEDIDOS[@]}"; do [ "$x" = "$1" ] && return 0; done; return 1; }
mkdir -p "$DESCARGAS" "$DESTINO"
touch "$MANIFIESTO"
anotar() {  # anotar ID ORIGEN TAMAÑO HUELLA
    sed -i "/^$1 /d" "$MANIFIESTO"
    echo "$1 $2 $3 $4 $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFIESTO"
}
# ¿Ya está instalado desde el mismo origen fijado? (al actualizar no se reinstala todo: --forzar lo hace igual)
# instalado ID CARPETA CAMPO VALOR: la carpeta existe y la línea del manifiesto tiene VALOR en el CAMPO (1 = id)
instalado() {
    [ -d "$DESTINO/$2" ] && awk -v id="$1" -v c="$3" -v v="$4" '$1 == id && $c == v { e = 1 } END { exit !e }' "$MANIFIESTO"
}
# Una conexión que se cuelga no debe esperar para siempre (visto en la instalación desde cero: 70 min parada en
# 0 KB/s): por debajo de VELOCIDAD_MIN bytes/s durante ESPERA_S segundos, curl corta. Los reintentos los hace este
# script, no curl (los de curl empiezan de cero): cada intento REANUDA el .part (-C -). Si el servidor no admite
# reanudar (curl 33), el siguiente intento empieza de cero; si dos intentos seguidos no avanzan nada, el .part se
# descarta. Si se agotan los intentos, el .part se conserva: al volver a ejecutar, continúa donde quedó.
VELOCIDAD_MIN="${PIANO_CURL_VELOCIDAD_MIN:-10240}"
ESPERA_S="${PIANO_CURL_ESPERA_S:-60}"
REINTENTOS="${PIANO_CURL_REINTENTOS:-6}"
PAUSA_S="${PIANO_CURL_PAUSA_S:-5}"
OPC_CURL=(-fsSL --connect-timeout 20 --speed-limit "$VELOCIDAD_MIN" --speed-time "$ESPERA_S")
tam() { stat -c %s "$1" 2>/dev/null || echo 0; }
bajar() {  # bajar URL ARCHIVO   (si ya está, no se vuelve a bajar; si quedó a medias, se reanuda)
    [ -s "$2" ] && return 0
    local inicio=$(date +%s) intento antes rc sin_avance=0
    for intento in $(seq "$REINTENTOS"); do
        antes="$(tam "$2.part")"
        [ "$antes" -gt 0 ] && echo "   reanudando desde $(du -h "$2.part" | cut -f1) (intento $intento de $REINTENTOS)"
        rc=0; curl "${OPC_CURL[@]}" -C - -o "$2.part" "$1" || rc=$?
        if [ "$rc" = 0 ]; then
            mv "$2.part" "$2"
            echo "   $(du -h "$2" | cut -f1) en $(( $(date +%s) - inicio )) s"
            return 0
        fi
        if [ "$rc" = 33 ]; then
            echo "   AVISO: el servidor no admite reanudar; se descarga de nuevo desde el principio"
            rm -f "$2.part"
        elif [ "$(tam "$2.part")" -le "$antes" ]; then
            sin_avance=$((sin_avance + 1))
            [ "$sin_avance" -lt 2 ] || { rm -f "$2.part"; sin_avance=0; echo "   AVISO: sin avance: se empieza de cero"; }
        else
            sin_avance=0
        fi
        if [ "$intento" -lt "$REINTENTOS" ]; then
            echo "   AVISO: descarga interrumpida (curl $rc); reintento"
            sleep "$PAUSA_S"
        fi
    done
    fallar "no se pudo descargar $(basename "$1") tras $REINTENTOS intentos (al volver a ejecutar, continúa donde quedó)"
}
sha() { sha256sum "$1" | cut -d' ' -f1; }
commit_de() { gzip -dc "$1" 2>/dev/null | git get-tar-commit-id 2>/dev/null || true; }   # commit que lleva el tar de GitHub
fallar() { echo "ERROR: $*" >&2; exit 1; }
instalar() {  # instalar CARPETA: CARPETA.part (ya extraída) reemplaza a la instalada
    rm -rf "${DESTINO:?}/$1"
    mv "$DESTINO/$1.part" "$DESTINO/$1"
}

OMITIDOS=()
while IFS='|' read -r tipo id origen fijado carpeta; do
    [ -n "$tipo" ] || continue
    [ ${#PEDIDOS[@]} -eq 0 ] || quiero "$id" || continue
    carpeta="${carpeta:-$id}"
    parte="$DESTINO/$carpeta.part"
    case "$tipo" in   # lo que el manifiesto anota de cada origen fijado (ver «anotar» en cada tipo)
        tar) clave=(2 "$origen@$fijado") ;;
        git) c="${fijado#*@}"; clave=(2 "$origen@${c%%:*}") ;;
        *) clave=(4 "$fijado") ;;
    esac
    if [ "$FORZAR" = 0 ] && instalado "$id" "$carpeta" "${clave[@]}"; then
        echo "== $id: ya instalado (mismo origen fijado; --forzar para reinstalar)"
        continue
    fi
    echo "== $id ($tipo)"
    case "$tipo" in
        tar)
            archivo="$DESCARGAS/$origen-$fijado.tar.gz"
            if [ ! -s "$archivo" ]; then   # una descarga anterior por rama sirve si es del commit fijado
                for viejo in "$DESCARGAS/$origen"-*.tar.gz; do
                    [ -s "$viejo" ] && [ "$(commit_de "$viejo")" = "$fijado" ] && { mv "$viejo" "$archivo"; break; }
                done
            fi
            bajar "$CODELOAD/$origen/tar.gz/$fijado" "$archivo"
            real="$(commit_de "$archivo")"
            [ "$real" = "$fijado" ] || { rm -f "$archivo"; fallar "$origen: el archivo es del commit '$real', no del fijado $fijado"; }
            rm -rf "$parte"; mkdir -p "$parte"
            if ! tar -xzf "$archivo" -C "$parte" --strip-components=1; then   # truncado: se borra para no repetir el fallo
                rm -rf "$parte"; rm -f "$archivo"
                fallar "$(basename "$archivo") dañado: no se pudo extraer (descarga borrada)"
            fi
            instalar "$carpeta"
            anotar "$id" "$origen@$fijado" "$(stat -c %s "$archivo")" "$(sha "$archivo")"
            ;;
        txz|7z)
            if [ "$tipo" = 7z ] && ! command -v 7z >/dev/null; then
                [ ${#PEDIDOS[@]} -eq 0 ] || fallar "$id necesita 7z: sudo apt install p7zip-full"
                echo "   AVISO: se omite $id: falta 7z (sudo apt install p7zip-full)"
                OMITIDOS+=("$id")
                continue
            fi
            archivo="$DESCARGAS/$(basename "$origen")"
            bajar "$origen" "$archivo"
            real="$(sha "$archivo")"
            [ "$real" = "$fijado" ] || { rm -f "$archivo"; fallar "$(basename "$origen"): SHA-256 $real, se esperaba $fijado (descarga borrada)"; }
            rm -rf "$parte"; mkdir -p "$parte"
            if [ "$tipo" = txz ]; then
                tar -xJf "$archivo" -C "$parte" --strip-components=1 || { rm -rf "$parte"; fallar "$archivo no se pudo extraer (¿espacio en disco?)"; }
            else
                7z x -y "-o$parte" "$archivo" >/dev/null || { rm -rf "$parte"; fallar "$archivo no se pudo extraer (¿espacio en disco?)"; }
            fi
            instalar "$carpeta"
            anotar "$id" "freepats:$(basename "$origen")" "$(stat -c %s "$archivo")" "$real"
            ;;
        git)
            rama="${fijado%%@*}"; resto="${fijado#*@}"; commit="${resto%%:*}"
            IFS=';' read -r -a carpetas <<<"${resto#*:}"
            # Como con curl: una conexión colgada corta (lowSpeed) y se reintenta. El clon (solo la estructura) se
            # repite desde cero; la descarga de los archivos (checkout) conserva lo ya bajado entre intentos.
            lento=(-c "http.lowSpeedLimit=$VELOCIDAD_MIN" -c "http.lowSpeedTime=$ESPERA_S")
            hecho=0
            for intento in $(seq "$REINTENTOS"); do
                rm -rf "$parte"
                git "${lento[@]}" clone --quiet --filter=blob:none --no-checkout --depth 1 --branch "$rama" "$origen" "$parte" \
                    && { hecho=1; break; }
                [ "$intento" -lt "$REINTENTOS" ] && { echo "   AVISO: clon interrumpido; reintento"; sleep "$PAUSA_S"; }
            done
            [ "$hecho" = 1 ] || { rm -rf "$parte"; fallar "no se pudo clonar $origen tras $REINTENTOS intentos"; }
            real="$(git -C "$parte" rev-parse HEAD)"
            [ "$real" = "$commit" ] || { rm -rf "$parte"; fallar "$origen ($rama) está en $real, no en el commit fijado $commit"; }
            git -C "$parte" sparse-checkout set --cone "${carpetas[@]}"
            hecho=0
            for intento in $(seq "$REINTENTOS"); do
                # reset --hard al commit fijado: si un intento quedó a medias, completa lo que falte (con sparse)
                git "${lento[@]}" -C "$parte" reset --quiet --hard "$commit" && { hecho=1; break; }
                [ "$intento" -lt "$REINTENTOS" ] && { echo "   AVISO: descarga de archivos interrumpida; reintento"; sleep "$PAUSA_S"; }
            done
            [ "$hecho" = 1 ] || { rm -rf "$parte"; fallar "no se pudieron bajar los archivos de $origen tras $REINTENTOS intentos"; }
            for c in "${carpetas[@]}"; do [ -d "$parte/$c" ] || { rm -rf "$parte"; fallar "falta la carpeta '$c' en $origen"; }; done
            rm -rf "$parte/.git"                      # ya verificado por git; ahorra el doble de espacio
            if [ "$id" = vsco2 ]; then                # el ensemble de cuerdas del catálogo se genera de estas muestras
                python3 "$DIR/generar_cuerdas.py" "$parte" || { rm -rf "$parte"; fallar "no se pudo generar el ensemble de cuerdas"; }
            fi
            instalar "$carpeta"
            anotar "$id" "$origen@$commit" "$(du -sb "$DESTINO/$carpeta" | cut -f1)" "git:${#carpetas[@]}carpetas"
            ;;
        *) fallar "tipo de origen desconocido: $tipo" ;;
    esac
    echo "   instalado en $DESTINO/$carpeta ($(du -sh "$DESTINO/$carpeta" | cut -f1))"
done <<<"$ORIGENES"
[ ${#OMITIDOS[@]} -eq 0 ] || echo "== Omitidos (falta 7z): ${OMITIDOS[*]}"
echo "== Listo. Manifiesto: $MANIFIESTO"
