#!/bin/bash
# Pruebas del arranque automático (fase 11) en carpetas temporales: arranque-automatico.sh (ajuste de systemd para
# tty1 y bloque de ~/.profile) y piano-al-encender.sh (espera a la tarjeta, abre el piano, deja la consola).
# sudo, systemctl, tty y pw-dump son FALSOS: no se toca la configuración real ni se reinicia nada.
# Uso: bash test_arranque_automatico.sh
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
comprobar() { if eval "$2"; then ok "$1"; else fallo "$1"; fi; }
correr() { SALIDA="$("$@" 2>&1)"; RC=$?; }

# Instalación falsa: las herramientas en $T/piano/tools (como las deja instalar.sh)
mkdir -p "$T/piano/tools" "$T/shim" "$T/getty"
cp "$DIR/arranque-automatico.sh" "$DIR/piano-al-encender.sh" "$DIR/salidas_audio.py" "$T/piano/tools/"
chmod +x "$T/piano/tools/"*.sh
export PIANO_RAIZ="$T/piano" PIANO_GETTY_DIR="$T/getty/getty@tty1.service.d" PIANO_PERFIL="$T/perfil"
AA="$T/piano/tools/arranque-automatico.sh"
AJUSTE="$PIANO_GETTY_DIR/piano-autologin.conf"
# sudo falso: registra la orden y la ejecuta sin privilegios (SHIM_SIN_SUDO: como un sudo que pide contraseña)
cat > "$T/shim/sudo" <<'EOF'
#!/bin/bash
echo "sudo $*" >> "$SHIM_LOG"
[ -z "${SHIM_SIN_SUDO:-}" ] || { echo "sudo: a password is required" >&2; exit 1; }
[ "$1" = -n ] && shift
exec "$@"
EOF
printf '#!/bin/bash\necho "systemctl $*" >> "$SHIM_LOG"\n' > "$T/shim/systemctl"
chmod +x "$T/shim/sudo" "$T/shim/systemctl"
export SHIM_LOG="$T/shim/log" PATH="$T/shim:$PATH"

ORIGINAL=$'# ~/.profile de prueba\nif [ -d "$HOME/bin" ] ; then\n    PATH="$HOME/bin:$PATH"\nfi\n'
printf '%s' "$ORIGINAL" > "$PIANO_PERFIL"

# 1) activar
: > "$SHIM_LOG"
correr bash "$AA" activar
comprobar "1: activar termina bien y dice desde cuándo vale" \
    '[ "$RC" -eq 0 ] && grep -q "desde el próximo encendido" <<<"$SALIDA" || { echo "$SALIDA"; false; }'
comprobar "1: ajuste de systemd para tty1 con inicio de sesión automático de este usuario" \
    'grep -qx "ExecStart=" "$AJUSTE" && grep -qxF "ExecStart=-/sbin/agetty -o '"'"'-p -f -- \\\\u'"'"' --noclear --autologin $(id -un) - \$TERM" "$AJUSTE"'
comprobar "1: con sudo y recargando systemd" \
    'grep -q "^sudo -n tee $AJUSTE" "$SHIM_LOG" && grep -qx "systemctl daemon-reload" "$SHIM_LOG"'
comprobar "1: el perfil conserva lo que tenía y añade el bloque al final" \
    '[ "$(head -c ${#ORIGINAL} "$PIANO_PERFIL"; echo x)" = "${ORIGINAL}x" ] && tail -1 "$PIANO_PERFIL" | grep -q "^# <<< piano: arranque automático"'
comprobar "1: el bloque solo actúa en tty1 y sin SSH, y llama al lanzador instalado" \
    'grep -qF "[ \"\$(tty)\" = /dev/tty1 ] && [ -z \"\${SSH_CONNECTION:-}\" ]" "$PIANO_PERFIL" && grep -qF "\"$T/piano/tools/piano-al-encender.sh\"" "$PIANO_PERFIL"'
correr bash "$AA" estado
comprobar "1: estado: activado" '[ "$RC" -eq 0 ] && grep -q "=> activado" <<<"$SALIDA"'

# 2) activar otra vez: no duplica nada ni vuelve a tocar systemd si el ajuste está igual
: > "$SHIM_LOG"
cp "$PIANO_PERFIL" "$T/perfil-1"
correr bash "$AA" activar
comprobar "2: activar dos veces: un solo bloque, el perfil igual" \
    '[ "$RC" -eq 0 ] && [ "$(grep -c "^# >>> piano: arranque automático" "$PIANO_PERFIL")" -eq 1 ] && cmp -s "$PIANO_PERFIL" "$T/perfil-1"'
comprobar "2: y sin volver a escribir el ajuste de systemd (ya estaba igual)" '! grep -q "tee" "$SHIM_LOG"'

# 3) el bloque del perfil, ejecutado como lo haría el inicio de sesión (sh), con tty y lanzador falsos
cp "$T/piano/tools/piano-al-encender.sh" "$T/lanzador-real"
printf '#!/bin/sh\necho lanzado >> "%s"\n' "$T/lanzado" > "$T/piano/tools/piano-al-encender.sh"
bloque_en() {   # bloque_en TTY [ssh]: ejecuta el perfil con ese tty; deja en $T/lanzado si se abrió el piano
    rm -f "$T/lanzado"
    printf '#!/bin/sh\necho %s\n' "$1" > "$T/shim/tty"; chmod +x "$T/shim/tty"
    if [ -n "${2:-}" ]; then
        env SSH_CONNECTION="10.0.0.2 5000 10.0.0.1 22" HOME="$T" sh "$PIANO_PERFIL" >/dev/null 2>&1
    else   # sin SSH: se quita la del entorno (las pruebas suelen correr por SSH)
        env -u SSH_CONNECTION HOME="$T" sh "$PIANO_PERFIL" >/dev/null 2>&1
    fi
}
bloque_en /dev/tty1
comprobar "3: en la consola de la Pi (tty1) abre el piano" '[ "$(cat "$T/lanzado" 2>/dev/null)" = lanzado ]'
bloque_en /dev/tty1 ssh
comprobar "3: por SSH, nunca (aunque fuera tty1)" '[ ! -e "$T/lanzado" ]'
bloque_en /dev/pts/0
comprobar "3: en otra terminal, tampoco" '[ ! -e "$T/lanzado" ]'
bloque_en "not a tty"
comprobar "3: sin terminal (scripts), tampoco" '[ ! -e "$T/lanzado" ]'
cp "$T/lanzador-real" "$T/piano/tools/piano-al-encender.sh"; rm -f "$T/shim/tty"

# 4) quitar: deja el perfil exactamente como estaba y borra el ajuste
: > "$SHIM_LOG"
correr bash "$AA" quitar
comprobar "4: quitar termina bien" '[ "$RC" -eq 0 ] && grep -q "desactivado" <<<"$SALIDA"'
comprobar "4: el perfil queda exactamente como estaba" '[ "$(cat "$PIANO_PERFIL"; echo x)" = "${ORIGINAL}x" ]'
comprobar "4: el ajuste de systemd se borra (y la carpeta vacía), recargando systemd" \
    '[ ! -e "$AJUSTE" ] && [ ! -d "$PIANO_GETTY_DIR" ] && grep -qx "systemctl daemon-reload" "$SHIM_LOG"'
correr bash "$AA" estado
comprobar "4: estado: desactivado" 'grep -q "=> desactivado" <<<"$SALIDA"'
correr bash "$AA" quitar
comprobar "4: quitar sin estar activado: sin error" '[ "$RC" -eq 0 ]'

# 5) casos límite
printf 'sin salto final' > "$PIANO_PERFIL"
bash "$AA" activar >/dev/null 2>&1
comprobar "5: perfil que termina sin salto de línea: el bloque empieza en su propia línea" \
    '[ "$(head -1 "$PIANO_PERFIL")" = "sin salto final" ] && sed -n 2p "$PIANO_PERFIL" | grep -q "^# >>> piano"'
bash "$AA" quitar >/dev/null 2>&1
rm -f "$PIANO_PERFIL"
bash "$AA" activar >/dev/null 2>&1
comprobar "5: sin ~/.profile: lo crea con el bloque" 'grep -q "^# >>> piano" "$PIANO_PERFIL"'
bash "$AA" quitar >/dev/null 2>&1
printf '%s' "$ORIGINAL" > "$PIANO_PERFIL"
correr env SHIM_SIN_SUDO=1 bash "$AA" activar
comprobar "5: sin sudo: error, y el perfil sin tocar" \
    '[ "$RC" -eq 1 ] && grep -q "hace falta sudo" <<<"$SALIDA" && [ "$(cat "$PIANO_PERFIL"; echo x)" = "${ORIGINAL}x" ] && [ ! -e "$AJUSTE" ]'
correr env PIANO_RAIZ="$T/no-instalado" bash "$AA" activar
comprobar "5: sin el piano instalado: error que dice instalar primero" '[ "$RC" -eq 1 ] && grep -q "instala primero" <<<"$SALIDA"'
correr bash "$AA"
comprobar "5: sin orden: muestra el uso (código 2)" '[ "$RC" -eq 2 ] && grep -q "activar" <<<"$SALIDA" && grep -q "quitar" <<<"$SALIDA"'

# 6) piano-al-encender.sh: abre el piano UNA vez pidiéndole que espere a la tarjeta, y deja indicaciones
#    (la espera en sí y la pantalla de inicio se prueban en test_piano_teclado.sh)
printf '#!/bin/bash\necho "piano $*" >> "%s"\nexit "${SHIM_RC_PIANO:-0}"\n' "$T/veces" > "$T/shim/piano-falso"
chmod +x "$T/shim/piano-falso"
export PIANO_COMANDO=piano-falso
LANZ="$T/piano/tools/piano-al-encender.sh"
rm -f "$T/veces"
correr bash "$LANZ"
comprobar "6: abre el piano una vez, pidiéndole esperar hasta 20 s a la tarjeta" \
    '[ "$RC" -eq 0 ] && [ "$(cat "$T/veces")" = "piano --esperar-tarjeta 20" ] || { echo "$SALIDA"; cat "$T/veces"; false; }'
comprobar "6: al salir con ESC deja la consola con indicaciones (volver a abrir y apagar)" \
    'grep -q "Piano cerrado" <<<"$SALIDA" && grep -q "^   piano " <<<"$SALIDA" && grep -q "sudo poweroff" <<<"$SALIDA"'
rm -f "$T/veces"
correr env PIANO_ESPERA_TARJETA=7 bash "$LANZ"
comprobar "6: la espera se puede cambiar (PIANO_ESPERA_TARJETA)" '[ "$(cat "$T/veces")" = "piano --esperar-tarjeta 7" ]'
rm -f "$T/veces"
correr env SHIM_RC_PIANO=1 bash "$LANZ"
comprobar "6: si el piano falla: lo dice, no reintenta y deja la consola (código 0)" \
    '[ "$RC" -eq 0 ] && grep -q "no pudo abrirse" <<<"$SALIDA" && [ "$(wc -l < "$T/veces")" -eq 1 ] && grep -q "sudo poweroff" <<<"$SALIDA"'

echo
[ "$FALLOS" -eq 0 ] && echo "TODAS LAS PRUEBAS PASAN" || { echo "$FALLOS FALLO(S)"; exit 1; }
