#!/bin/bash
# Pruebas de instalar.sh en carpetas temporales: paquete de sfizz y plugin de reverb FALSOS, un origen de sonido falso
# (file://) y el comando «piano» en una carpeta propia (sin sudo). No toca la instalación real.
# Uso: bash test_instalar.sh
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
comprobar() { if eval "$2"; then ok "$1"; else fallo "$1"; fi; }

# Copia de las herramientas como las tendría el repositorio (tools/pi + tools/midi)
mkdir -p "$T/repo/tools/pi" "$T/repo/tools/midi" "$T/lv2/mda.lv2" "$T/lv2-vacio" "$T/comando"
find "$DIR" -maxdepth 1 -type f ! -name '*.pyc' ! -name 'generar_midis_prueba.py' ! -name 'test_generar_midis_prueba.py' \
    -exec cp -p {} "$T/repo/tools/pi/" \;
GEN="$DIR/generar_midis_prueba.py"; [ -f "$GEN" ] || GEN="$DIR/../midi/generar_midis_prueba.py"
cp "$GEN" "$(dirname "$GEN")/test_generar_midis_prueba.py" "$T/repo/tools/midi/"
INSTALAR="$T/repo/tools/pi/instalar.sh"
# Reverb falsa con la forma del paquete mda-lv2 real: prefijo en el manifiesto (mda:Ambience) y un .so por plugin
printf '@prefix mda: <http://drobilla.net/plugins/mda/> .\nmda:Ambience\n\ta lv2:Plugin ;\n\tlv2:binary <Ambience.so> .\n' \
    > "$T/lv2/mda.lv2/manifest.ttl"
touch "$T/lv2/mda.lv2/Ambience.so"
mkdir -p "$T/lv2-sin-so/mda.lv2"; cp "$T/lv2/mda.lv2/manifest.ttl" "$T/lv2-sin-so/mda.lv2/"   # manifiesto sin el plugin

paquete() {   # paquete ARCHIVO [sin-parche|sumas-malas]: un sfizz compilado falso con la forma del de las Releases
    local p="$T/paq/piano-rpi-sfizz-9.9.9-arm64"
    rm -rf "$T/paq"; mkdir -p "$p/licencias/sfizz"
    # Como el real (abseil): --help no lista opciones («No flags matched»); --helpfull, todas.
    local opciones='    --num_voices (Num of voices); default: 32;'
    [ "${2:-}" = sin-parche ] || opciones="$opciones\n    --sample_quality (Live sample quality (0-10)); default: 2;"
    # Y una ayuda LARGA tras la opción buscada: quien la lea con «| grep -q» corta la tubería (SIGPIPE) como con el real.
    printf '#!/bin/sh\nif [ "$1" = --helpfull ]; then printf "%s\\n"; seq 1 20000 | sed "s/^/    --opcion_/"\nelse echo "No flags matched."; fi\n' \
        "$opciones" > "$p/sfizz_jack"
    printf '#!/bin/sh\necho render\n' > "$p/sfizz_render"
    chmod 755 "$p/sfizz_jack" "$p/sfizz_render"
    echo "sfizz=9.9.9" > "$p/BUILDINFO"; echo "BSD-2-Clause" > "$p/licencias/sfizz/LICENSE"
    (cd "$p" && sha256sum sfizz_jack sfizz_render > SHA256SUMS)
    [ "${2:-}" != sumas-malas ] || echo "otra cosa" >> "$p/sfizz_render"
    tar -czf "$1" -C "$T/paq" "$(basename "$p")"
}
paquete "$T/bueno.tar.gz"; paquete "$T/sin-parche.tar.gz" sin-parche; paquete "$T/sumas-malas.tar.gz" sumas-malas

export PIANO_RAIZ="$T/piano" PIANO_COMANDO_DIR="$T/comando" LV2_PATH="$T/lv2"
R="$T/piano"
correr() { SALIDA="$("$@" 2>&1)"; RC=$?; }

# 1) Solo comprobar: no instala nada
correr bash "$INSTALAR" --comprobar
comprobar "1: --comprobar termina bien" '[ "$RC" -eq 0 ] && grep -q "Comprobación terminada" <<<"$SALIDA" || { echo "$SALIDA"; false; }'
comprobar "1: y no instala nada" '[ ! -e "$R" ] && [ -z "$(ls "$T/comando")" ]'

# 2) Faltan programas: dice el «apt install» exacto (sin jalv en el PATH y sin la reverb)
mkdir -p "$T/sinjalv"
for f in /usr/local/bin/* /usr/bin/* /bin/*; do
    n="$(basename "$f")"; [ "$n" = jalv ] || [ -e "$T/sinjalv/$n" ] || ln -s "$f" "$T/sinjalv/$n"
done
SALIDA="$(PATH="$T/sinjalv" LV2_PATH="$T/lv2-vacio" bash "$INSTALAR" --sin-sonidos 2>&1)"; RC=$?
comprobar "2: faltan jalv y la reverb: error con «sudo apt install jalv mda-lv2»" \
    '[ "$RC" -eq 1 ] && grep -q "sudo apt install jalv mda-lv2$" <<<"$SALIDA"'
comprobar "2: y no instala nada" '[ ! -e "$R" ]'
SALIDA="$(LV2_PATH="$T/lv2-sin-so" bash "$INSTALAR" --comprobar 2>&1)"; RC=$?
comprobar "2: un manifiesto sin el plugin (.so) no cuenta como reverb instalada" \
    '[ "$RC" -eq 1 ] && grep -q "sudo apt install mda-lv2$" <<<"$SALIDA"'

# 3) Sin sfizz (ni paquete ni instalado): error con las instrucciones
correr bash "$INSTALAR" --sin-sonidos
comprobar "3: sin sfizz: error que indica las Releases y --sfizz" '[ "$RC" -eq 1 ] && grep -q -- "--sfizz" <<<"$SALIDA" && grep -q "Releases" <<<"$SALIDA"'

# 4) Instalación completa (sin sonidos)
correr bash "$INSTALAR" --sin-sonidos --sfizz "$T/bueno.tar.gz"
comprobar "4: termina bien" '[ "$RC" -eq 0 ] && grep -q "== Listo" <<<"$SALIDA" || { echo "$SALIDA"; false; }'
comprobar "4: herramientas copiadas (también el generador de MIDI y el propio instalador)" \
    '[ -x "$R/tools/piano-en-vivo.sh" ] && [ -f "$R/tools/teclado_piano.py" ] && [ -f "$R/tools/generar_midis_prueba.py" ] && [ -x "$R/tools/instalar.sh" ]'
comprobar "4: sfizz instalado, ejecutable, con sus sumas y licencias" \
    '[ -x "$R/bin/sfizz_jack" ] && [ -x "$R/bin/sfizz_render" ] && (cd "$R/bin" && sha256sum -c --quiet SHA256SUMS) && [ -f "$R/bin/licencias/sfizz/LICENSE" ]'
comprobar "4: comando piano instalado e idéntico al del repositorio" 'cmp -s "$T/comando/piano" "$T/repo/tools/pi/piano" && [ -x "$T/comando/piano" ]'
comprobar "4: MIDI de prueba generados" '[ -s "$R/midi/01-escala-dinamicas.mid" ] && [ "$(ls "$R/midi" | wc -l)" -ge 11 ]'
comprobar "4: dice cómo instalar el Softify (Pianobook) y cómo validar" \
    'grep -q "pianobook.co.uk" <<<"$SALIDA" && grep -q "instalar_softify.py" <<<"$SALIDA" && grep -q "ejecutar-pruebas.sh" <<<"$SALIDA"'
SUMA_BUENA="$(sha256sum "$R/bin/sfizz_jack" | cut -d' ' -f1)"

# 5) Paquetes malos: no tocan el sfizz instalado
correr bash "$INSTALAR" --sin-sonidos --sfizz "$T/sumas-malas.tar.gz"
comprobar "5: sumas que no coinciden: error" '[ "$RC" -eq 1 ] && grep -q "no coinciden" <<<"$SALIDA"'
correr bash "$INSTALAR" --sin-sonidos --sfizz "$T/sin-parche.tar.gz"
comprobar "5: sfizz sin el parche del proyecto: error" '[ "$RC" -eq 1 ] && grep -q "parche" <<<"$SALIDA"'
echo "no es un tar" > "$T/roto.tar.gz"
correr bash "$INSTALAR" --sin-sonidos --sfizz "$T/roto.tar.gz"
comprobar "5: archivo que no es un paquete: error" '[ "$RC" -eq 1 ]'
comprobar "5: el sfizz instalado sigue intacto" '[ "$(sha256sum "$R/bin/sfizz_jack" | cut -d" " -f1)" = "$SUMA_BUENA" ]'

# 6) Volver a ejecutar sin --sfizz conserva el instalado; desde la copia instalada también funciona (actualizar)
correr bash "$INSTALAR" --sin-sonidos
comprobar "6: sin --sfizz conserva el instalado" '[ "$RC" -eq 0 ] && grep -q "se conserva el instalado" <<<"$SALIDA"'
correr bash "$R/tools/instalar.sh" --sin-sonidos
comprobar "6: desde ~/piano/tools/instalar.sh (ya instalado)" '[ "$RC" -eq 0 ] && grep -q "ya se ejecuta desde" <<<"$SALIDA" && grep -q "ya estaba al día" <<<"$SALIDA"'

# 7) Con sonidos: llama a la descarga (con un origen falso local)
mkdir -p "$T/fuente/Top"; echo "<region> sample=x.wav" > "$T/fuente/Top/x.sfz"; tar -cJf "$T/s.tar.xz" -C "$T/fuente" Top
echo "txz|prueba|file://$T/s.tar.xz|$(sha256sum "$T/s.tar.xz" | cut -d' ' -f1)|" > "$T/origenes.txt"
SALIDA="$(PIANO_ORIGENES="$T/origenes.txt" bash "$INSTALAR" 2>&1)"; RC=$?
comprobar "7: descarga los sonidos en ~/piano/instrumentos" '[ "$RC" -eq 0 ] && [ -f "$R/instrumentos/prueba/x.sfz" ] || { echo "$SALIDA" | tail -5; false; }'

# 8) Opción desconocida y ayuda
correr bash "$INSTALAR" --no-existe
comprobar "8: opción desconocida: código 2" '[ "$RC" -eq 2 ]'
correr bash "$INSTALAR" --help
comprobar "8: --help explica los pasos" '[ "$RC" -eq 0 ] && grep -q "sudo apt install" <<<"$SALIDA" && grep -q -- "--sin-sonidos" <<<"$SALIDA"'

# 10) PipeWire: recién instalado no está en marcha y el instalador lo arranca; avisa si no se ve la tarjeta.
#     systemctl --user y pw-dump FALSOS (no se toca el PipeWire real): estado en un archivo, arranques registrados;
#     pw-dump publica una tarjeta USB de prueba (o ninguna, con SHIM_SIN_USB).
mkdir -p "$T/shim"
cat > "$T/shim/systemctl" <<'EOF'
#!/bin/bash
[ "$1" = --user ] || exec /usr/bin/systemctl "$@"
shift
case "$1" in
    is-active) [ "$(cat "$SHIM_ESTADO" 2>/dev/null)" = activo ] ;;
    start) echo "start ${*:2}" >> "$SHIM_ESTADO.log"; [ -z "${SHIM_FALLA_START:-}" ] && echo activo > "$SHIM_ESTADO" ;;
    *) exec /usr/bin/systemctl --user "$@" ;;
esac
EOF
cat > "$T/shim/pw-dump" <<'EOF'
#!/bin/bash
if [ -n "${SHIM_SIN_USB:-}" ]; then echo "[]"; exit 0; fi
echo '[{"id": 99, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink",
  "node.name": "alsa_output.usb-Prueba_Tarjeta-00.analog-stereo", "node.description": "Tarjeta de Prueba Analog Stereo",
  "api.alsa.path": "front:99"}, "params": {}}}]'
EOF
chmod +x "$T/shim/systemctl" "$T/shim/pw-dump"
export SHIM_ESTADO="$T/shim/estado"
con_shim() { SALIDA="$(PATH="$T/shim:$PATH" bash "$INSTALAR" "$@" 2>&1)"; RC=$?; }
rm -f "$SHIM_ESTADO" "$SHIM_ESTADO.log"
con_shim --comprobar
comprobar "10: --comprobar avisa que PipeWire no está en marcha, sin arrancarlo" \
    '[ "$RC" -eq 0 ] && grep -q "PipeWire no está en marcha" <<<"$SALIDA" && [ ! -e "$SHIM_ESTADO.log" ]'
con_shim --sin-sonidos
comprobar "10: PipeWire parado: lo arranca (socket, servicio y WirePlumber)" \
    '[ "$RC" -eq 0 ] && grep -q "arrancado" <<<"$SALIDA" && grep -qx "start pipewire.socket pipewire wireplumber" "$SHIM_ESTADO.log"'
comprobar "10: y muestra las tarjetas USB a la vista (cualquiera sirve)" \
    'grep -q "tarjetas de sonido USB a la vista" <<<"$SALIDA" && grep -q "Tarjeta de Prueba" <<<"$SALIDA"'
rm -f "$SHIM_ESTADO.log"
con_shim --sin-sonidos
comprobar "10: PipeWire en marcha: no lo vuelve a arrancar" '[ "$RC" -eq 0 ] && grep -q "   en marcha" <<<"$SALIDA" && [ ! -e "$SHIM_ESTADO.log" ]'
SALIDA="$(SHIM_SIN_USB=1 PATH="$T/shim:$PATH" bash "$INSTALAR" --sin-sonidos 2>&1)"; RC=$?
comprobar "10: sin tarjeta USB: termina, pero avisa (se usará la salida de la Pi)" \
    '[ "$RC" -eq 0 ] && grep -q "AVISO: no veo ninguna tarjeta de sonido USB" <<<"$SALIDA"'
rm -f "$SHIM_ESTADO"
SALIDA="$(SHIM_FALLA_START=1 PATH="$T/shim:$PATH" bash "$INSTALAR" --sin-sonidos 2>&1)"; RC=$?
comprobar "10: si PipeWire no arranca: error que dice qué ejecutar" '[ "$RC" -eq 1 ] && grep -q "systemctl --user" <<<"$SALIDA"'

# 11) El registro de los servicios: legible de verdad (servicio de prueba con una marca); si no (p. ej. Lite con
#     registro en memoria y el usuario fuera de adm/systemd-journal), error con el comando para arreglarlo.
mkdir -p "$T/shim-registro"
printf '#!/bin/sh\nexit 0\n' > "$T/shim-registro/journalctl"       # un registro que no devuelve nada
chmod +x "$T/shim-registro/journalctl"
correr bash "$INSTALAR" --sin-sonidos
comprobar "11: el registro de los servicios se puede leer (journalctl --user-unit)" \
    '[ "$RC" -eq 0 ] && grep -q "registro de los servicios: legible" <<<"$SALIDA" || { echo "$SALIDA" | tail -3; false; }'
SALIDA="$(PATH="$T/shim-registro:$PATH" bash "$INSTALAR" --sin-sonidos 2>&1)"; RC=$?
comprobar "11: si no se puede leer: error con «usermod -aG systemd-journal»" \
    '[ "$RC" -eq 1 ] && grep -q "usermod -aG systemd-journal" <<<"$SALIDA"'
comprobar "11: ningún script lee el registro con «journalctl --user» (no funciona con el registro en memoria)" \
    '! grep -l "journalctl --user[[:space:]]" "$DIR"/*.sh "$DIR"/*.py | grep -v "/test_instalar.sh$"'

# 12) --arranque-automatico (fase 11): llama a arranque-automatico.sh activar. sudo falso (systemctl solo se registra) y
#     carpetas temporales para el ajuste de tty1 y el perfil: no se toca la configuración real.
mkdir -p "$T/shim-arranque"
cat > "$T/shim-arranque/sudo" <<'EOF'
#!/bin/bash
[ "$1" = -n ] && shift
[ "$1" = systemctl ] && { echo "$*" >> "$SHIM_ARRANQUE_LOG"; exit 0; }
exec "$@"
EOF
chmod +x "$T/shim-arranque/sudo"
con_arranque() {
    SALIDA="$(SHIM_ARRANQUE_LOG="$T/arranque.log" PIANO_GETTY_DIR="$T/getty" PIANO_PERFIL="$T/perfil-arranque" \
              PATH="$T/shim-arranque:$PATH" bash "$INSTALAR" --sin-sonidos "$@" 2>&1)"; RC=$?
}
con_arranque
comprobar "12: sin --arranque-automatico no lo activa, pero dice cómo" \
    '[ "$RC" -eq 0 ] && [ ! -e "$T/getty/piano-autologin.conf" ] && [ ! -e "$T/perfil-arranque" ] && grep -q "arranque-automatico.sh activar" <<<"$SALIDA"'
con_arranque --arranque-automatico
comprobar "12: --arranque-automatico lo activa: ajuste de tty1, bloque del perfil y systemd recargado" \
    '[ "$RC" -eq 0 ] && grep -q -- "--autologin $(id -un) " "$T/getty/piano-autologin.conf" && grep -q "^# >>> piano: arranque automático" "$T/perfil-arranque" && grep -qx "systemctl daemon-reload" "$T/arranque.log" && grep -q "Arranque automático activado" <<<"$SALIDA" || { echo "$SALIDA" | tail -5; false; }'
comprobar "12: el bloque llama al lanzador instalado" 'grep -qF "\"$R/tools/piano-al-encender.sh\"" "$T/perfil-arranque" && [ -x "$R/tools/piano-al-encender.sh" ]'
correr bash "$INSTALAR" --help
comprobar "12: --help lo explica" 'grep -q -- "--arranque-automatico" <<<"$SALIDA" && grep -q "quitar" <<<"$SALIDA"'

# 9) El acceso directo de la raíz del repositorio (si se ejecuta desde el repositorio)
RAIZ_REPO="$(cd "$DIR/../.." && pwd)"
if [ -f "$RAIZ_REPO/instalar.sh" ] && [ -d "$RAIZ_REPO/tools/pi" ]; then
    correr bash "$RAIZ_REPO/instalar.sh" --comprobar
    comprobar "9: ./instalar.sh de la raíz llama al instalador" '[ "$RC" -eq 0 ] && grep -q "Comprobación terminada" <<<"$SALIDA"'
fi

echo
[ "$FALLOS" -eq 0 ] && echo "TODAS LAS PRUEBAS PASAN" || { echo "$FALLOS FALLO(S)"; exit 1; }
