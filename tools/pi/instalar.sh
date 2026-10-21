#!/bin/bash
# Instalador del Piano Raspberry Pi (fase 09). Se ejecuta EN LA RASPBERRY PI, desde el repositorio clonado
# (./instalar.sh en la raíz llama a este) o desde una copia ya instalada (~/piano/tools/instalar.sh, para actualizar).
#  1) comprueba lo necesario; si falta algo, muestra el «sudo apt install» exacto y termina (no instala paquetes)
#  2) copia las herramientas a ~/piano/tools (las preferencias, en ~/.config/piano, no se tocan)
#  3) instala sfizz compilado (paquete de las Releases: --sfizz ARCHIVO.tar.gz), verificando sus sumas y el parche
#  4) instala el comando «piano» en /usr/local/bin (con sudo si hace falta)
#  5) genera los MIDI de prueba en ~/piano/midi
#  6) arranca PipeWire si no está en marcha (recién instalado) y comprueba que se vea la tarjeta de sonido
#  7) descarga los sonidos (descargar-instrumentos.sh; unos 2,4 GB), salvo --sin-sonidos
#  8) con --fuente-consola, aplica la letra grande Terminus en la consola (fuente-consola.sh; se puede revertir)
#  9) con --arranque-automatico, el piano se abre solo al encender (arranque-automatico.sh; «quitar» lo deshace)
# Uso: instalar.sh [--sfizz ARCHIVO.tar.gz] [--sin-sonidos] [--fuente-consola] [--arranque-automatico] [--comprobar]
#   --comprobar  solo informa qué falta, sin instalar nada
# Variables (pruebas): PIANO_RAIZ (~/piano), PIANO_COMANDO_DIR (/usr/local/bin), LV2_PATH (como lilv/jalv)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
RAIZ="${PIANO_RAIZ:-$HOME/piano}"
COMANDO_DIR="${PIANO_COMANDO_DIR:-/usr/local/bin}"
SFIZZ_PAQUETE=""; SONIDOS=1; FUENTE=0; ARRANQUE=0; SOLO_COMPROBAR=0
while [ $# -gt 0 ]; do
    case "$1" in
        --sfizz) SFIZZ_PAQUETE="${2:?--sfizz necesita el archivo .tar.gz}"; shift 2 ;;
        --sin-sonidos) SONIDOS=0; shift ;;
        --fuente-consola) FUENTE=1; shift ;;
        --arranque-automatico) ARRANQUE=1; shift ;;
        --comprobar) SOLO_COMPROBAR=1; shift ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Opción desconocida: $1 (ver --help)" >&2; exit 2 ;;
    esac
done
paso() { echo "== $*"; }
aviso() { echo "   AVISO: $*"; }
fallar() { echo "ERROR: $*" >&2; exit 1; }

# --- 1) Requisitos
# orden: paquete de Raspberry Pi OS / Debian 12 que la trae
REQUISITOS="python3:python3 jalv:jalv pw-jack:pipewire-jack pw-link:pipewire-bin pw-dump:pipewire-bin
pw-metadata:pipewire-bin pw-top:pipewire-bin pw-record:pipewire-bin wpctl:wireplumber aplaymidi:alsa-utils
aseqdump:alsa-utils aconnect:alsa-utils git:git curl:curl xz:xz-utils tar:tar gzip:gzip taskset:util-linux
flock:util-linux stdbuf:coreutils systemd-run:systemd journalctl:systemd sha256sum:coreutils"
paso "Comprobando requisitos"
FALTAN=()
for r in $REQUISITOS; do
    command -v "${r%%:*}" >/dev/null || FALTAN+=("${r#*:}")
done
# La reverb (mda Ambience) es un plugin LV2: se busca donde la busca jalv (LV2_PATH si está definida)
RUTAS_LV2="${LV2_PATH:-$HOME/.lv2:/usr/local/lib/lv2:/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2}"
HAY_MDA=0
IFS=':' read -r -a rutas <<<"$RUTAS_LV2"
for r in "${rutas[@]}"; do   # paquete mda-lv2: un .so por plugin, declarado en el manifiesto (mda:Ambience)
    [ -f "$r/mda.lv2/Ambience.so" ] && grep -qs "Ambience" "$r/mda.lv2/manifest.ttl" && HAY_MDA=1
done
[ "$HAY_MDA" = 1 ] || FALTAN+=(mda-lv2)
if [ ${#FALTAN[@]} -gt 0 ]; then
    paquetes="$(printf '%s\n' "${FALTAN[@]}" | sort -u | tr '\n' ' ')"
    echo "   Faltan programas. Instálalos con:"
    echo "      sudo apt install ${paquetes% }"
    exit 1
fi
echo "   programas y reverb (mda-lv2): bien"
command -v 7z >/dev/null || aviso "sin 7z no se descarga el piano vertical Upright KW (sudo apt install p7zip-full)"
[ "$(uname -m)" = aarch64 ] || aviso "esta máquina es $(uname -m); el piano se probó en una Raspberry Pi 3 de 64 bits"
[[ " $(id -nG) " == *" input "* ]] || aviso "tu usuario no está en el grupo «input»: no podrá leer el teclado"
sudo -n true 2>/dev/null || aviso "sin sudo sin contraseña, «piano» no puede usar el modo rendimiento (-p)"
# Recién instalado, PipeWire no está en marcha hasta volver a iniciar sesión: el paso 6 lo arranca.
systemctl --user is-active --quiet pipewire || aviso "PipeWire no está en marcha (el instalador lo arranca)"
[ "$SOLO_COMPROBAR" = 0 ] || { echo "== Comprobación terminada (no se instaló nada)"; exit 0; }

# --- 2) Herramientas
GEN="$DIR/generar_midis_prueba.py"; [ -f "$GEN" ] || GEN="$DIR/../midi/generar_midis_prueba.py"
TEST_GEN="$(dirname "$GEN")/test_generar_midis_prueba.py"
[ -f "$GEN" ] && [ -f "$DIR/piano-en-vivo.sh" ] || fallar "no encuentro las herramientas junto a $0 (¿repositorio completo?)"
paso "Herramientas en $RAIZ/tools"
mkdir -p "$RAIZ/tools" "$RAIZ/bin" "$RAIZ/midi"
if [ "$(cd "$RAIZ/tools" && pwd -P)" != "$(cd "$DIR" && pwd -P)" ]; then
    find "$DIR" -maxdepth 1 -type f ! -name '*.pyc' -exec cp -p {} "$RAIZ/tools/" \;
    cp -p "$GEN" "$TEST_GEN" "$RAIZ/tools/"
    chmod +x "$RAIZ/tools/"*.sh "$RAIZ/tools/piano"
    echo "   $(find "$DIR" -maxdepth 1 -type f ! -name '*.pyc' | wc -l) archivos copiados"
else
    echo "   (ya se ejecuta desde $RAIZ/tools)"
fi

# --- 3) sfizz
con_parche() {   # con_parche PROGRAMA: ¿lleva el parche 0002 del proyecto? (abseil: --help no lista opciones; --helpfull sí)
    # La ayuda se guarda antes de buscar: con pipefail, «… | grep -q» falla si el programa sigue escribiendo (SIGPIPE).
    local ayuda
    ayuda="$("$1" --helpfull 2>&1 || true)"
    grep -q -- "--sample_quality" <<<"$ayuda"
}
if [ -n "$SFIZZ_PAQUETE" ]; then
    paso "sfizz desde $(basename "$SFIZZ_PAQUETE")"
    [ -s "$SFIZZ_PAQUETE" ] || fallar "no existe $SFIZZ_PAQUETE"
    TMPS="$(mktemp -d)"; trap 'rm -rf "$TMPS"' EXIT
    tar -xzf "$SFIZZ_PAQUETE" -C "$TMPS" || fallar "$SFIZZ_PAQUETE no es un paquete válido"
    p="$(find "$TMPS" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [ -f "$p/sfizz_jack" ] && [ -f "$p/SHA256SUMS" ] && [ -d "$p/licencias" ] \
        || fallar "el paquete no tiene sfizz_jack, SHA256SUMS y licencias/"
    (cd "$p" && sha256sum -c --quiet SHA256SUMS) || fallar "las sumas SHA-256 del paquete no coinciden"
    con_parche "$p/sfizz_jack" || fallar "este sfizz_jack no lleva el parche del proyecto (--sample_quality)"
    install -m 755 "$p/sfizz_jack" "$p/sfizz_render" "$RAIZ/bin/"
    install -m 644 "$p/SHA256SUMS" "$p/BUILDINFO" "$RAIZ/bin/"
    rm -rf "$RAIZ/bin/licencias"; cp -r "$p/licencias" "$RAIZ/bin/licencias"
    echo "   instalado en $RAIZ/bin (sumas verificadas, con sus licencias)"
elif [ -x "$RAIZ/bin/sfizz_jack" ]; then
    paso "sfizz: se conserva el instalado ($RAIZ/bin/sfizz_jack)"
    con_parche "$RAIZ/bin/sfizz_jack" || fallar "el sfizz_jack instalado no lleva el parche del proyecto: reinstalar con --sfizz"
else
    fallar "falta sfizz: descarga piano-rpi-sfizz-*-arm64.tar.gz de las Releases y usa --sfizz ARCHIVO
       (o compílalo con tools/build-sfizz en un PC con Docker)"
fi

# --- 4) Comando «piano»
paso "Comando piano en $COMANDO_DIR"
if cmp -s "$DIR/piano" "$COMANDO_DIR/piano"; then
    echo "   ya estaba al día"
elif [ -w "$COMANDO_DIR" ]; then
    install -m 755 "$DIR/piano" "$COMANDO_DIR/piano"
else
    sudo install -m 755 "$DIR/piano" "$COMANDO_DIR/piano"
fi

# --- 5) MIDI de prueba
paso "MIDI de prueba en $RAIZ/midi"
python3 "$GEN" "$RAIZ/midi" >/dev/null
echo "   $(ls "$RAIZ/midi" | wc -l) archivos"

# --- 6) PipeWire en marcha y la tarjeta de sonido a la vista
# En un sistema recién instalado (p. ej. Raspberry Pi OS Lite + apt install pipewire...), sus servicios de usuario
# quedan habilitados pero no arrancan hasta el próximo inicio de sesión: se arrancan aquí.
paso "PipeWire"
if systemctl --user is-active --quiet pipewire; then
    echo "   en marcha"
else
    systemctl --user start pipewire.socket pipewire wireplumber \
        || fallar "no se pudo arrancar PipeWire: systemctl --user start pipewire wireplumber"
    for _ in $(seq 20); do systemctl --user is-active --quiet pipewire && break; sleep 0.5; done
    systemctl --user is-active --quiet pipewire || fallar "PipeWire no arrancó: systemctl --user status pipewire"
    echo "   arrancado (desde ahora arranca solo al iniciar sesión)"
fi
# Tarjetas de sonido USB a la vista (fase 10: sirve cualquiera; se elige con F10). WirePlumber tarda un poco en
# publicarlas tras arrancar.
TARJETAS=""
for _ in $(seq 20); do
    TARJETAS="$(python3 "$DIR/salidas_audio.py" lista 2>/dev/null | awk '$1 == "usb"' || true)"
    [ -n "$TARJETAS" ] && break
    sleep 0.5
done
if [ -n "$TARJETAS" ]; then
    echo "   tarjetas de sonido USB a la vista:"
    sed 's/^/      /' <<<"$TARJETAS"
else
    aviso "no veo ninguna tarjeta de sonido USB: el piano usará la salida de auriculares de la Pi (o conecta una)"
fi
# El piano lee lo que imprimen sus servicios (confirmaciones de sfizz, cortes de PipeWire) con «journalctl
# --user-unit». En Raspberry Pi OS Lite el registro es solo en memoria (Storage=volatile) y para leerlo hay que estar
# en el grupo adm o systemd-journal: se comprueba de verdad, con un servicio de prueba que escribe una marca.
MARCA="registro-piano-$$"
systemd-run --user --quiet --wait --collect --unit="piano-prueba-registro-$$" /bin/echo "$MARCA" >/dev/null 2>&1 || true
REGISTRO=0
for _ in $(seq 10); do
    leido="$(journalctl --user-unit="piano-prueba-registro-$$" --no-pager -o cat 2>/dev/null || true)"
    grep -qx "$MARCA" <<<"$leido" && { REGISTRO=1; break; }
    sleep 0.5
done
[ "$REGISTRO" = 1 ] && echo "   registro de los servicios: legible" \
    || fallar "no puedo leer el registro de los servicios del piano: sudo usermod -aG systemd-journal $USER (y vuelve a iniciar sesión)"

# --- 7) Sonidos
if [ "$SONIDOS" = 1 ]; then
    paso "Sonidos (descarga verificada; puede tardar)"
    PIANO_INSTRUMENTOS="${PIANO_INSTRUMENTOS:-$RAIZ/instrumentos}" PIANO_DESCARGAS="${PIANO_DESCARGAS:-$RAIZ/descargas}" \
        bash "$RAIZ/tools/descargar-instrumentos.sh"
else
    paso "Sonidos: omitidos (--sin-sonidos); más tarde: bash $RAIZ/tools/descargar-instrumentos.sh"
fi

# --- 8) Letra de la consola
if [ "$FUENTE" = 1 ]; then
    paso "Letra grande en la consola"
    bash "$RAIZ/tools/fuente-consola.sh" aplicar
fi

# --- 9) Arranque automático
if [ "$ARRANQUE" = 1 ]; then
    paso "Arranque automático al encender"
    bash "$RAIZ/tools/arranque-automatico.sh" activar | sed 's/^/   /'
fi

echo
echo "== Listo."
echo "   Tocar:      piano            (ESC para salir; F9 menú de sonidos)"
[ "$ARRANQUE" = 1 ] || echo "   Al encender: bash $RAIZ/tools/arranque-automatico.sh activar   (el piano se abre solo)"
echo "   Softify:    descárgalo de https://www.pianobook.co.uk/packs/softify-piano-vol-1/ (requiere cuenta) y:"
echo "               python3 $RAIZ/tools/instalar_softify.py \"Softify Piano Vol 1 v1.1.zip\""
echo "   Pruebas:    bash $RAIZ/tools/ejecutar-pruebas.sh"
