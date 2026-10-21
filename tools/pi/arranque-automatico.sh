#!/bin/bash
# Arranque automático del piano al encender la Raspberry Pi (fase 11).
#   activar  la consola de la Pi (tty1) inicia sesión sola con este usuario y, en esa consola (nunca por SSH), se abre
#            el piano (piano-al-encender.sh): espera a la tarjeta de sonido y, al salir con ESC, deja la consola
#   quitar   lo deshace: la consola vuelve a pedir usuario y contraseña al encender
#   estado   dice si está activado
# Cambia la configuración del sistema: un ajuste de systemd para tty1 (con sudo) y unas líneas marcadas en ~/.profile.
# Vale desde el próximo encendido: la consola actual no se reinicia (cortaría la sesión que haya en ella).
# El inicio de sesión automático es necesario: el sonido (PipeWire) funciona dentro de la sesión de un usuario.
# Variables (pruebas): PIANO_RAIZ (~/piano), PIANO_GETTY_DIR (/etc/systemd/system/getty@tty1.service.d),
#                      PIANO_PERFIL (~/.profile)
set -euo pipefail

RAIZ="${PIANO_RAIZ:-$HOME/piano}"
GETTY_DIR="${PIANO_GETTY_DIR:-/etc/systemd/system/getty@tty1.service.d}"
AJUSTE="$GETTY_DIR/piano-autologin.conf"
PERFIL="${PIANO_PERFIL:-$HOME/.profile}"
LANZADOR="$RAIZ/tools/piano-al-encender.sh"
INICIO_BLOQUE="# >>> piano: arranque automático"
FIN_BLOQUE="# <<< piano: arranque automático"
USUARIO="$(id -un)"

fallar() { echo "ERROR: $*" >&2; exit 1; }

# Igual que la línea de getty@.service de Debian 12, con inicio de sesión automático (forma de la wiki de Debian:
# «-f» le dice a login que no pida contraseña). En los archivos de systemd, «\\u» llega a agetty como «\u».
ajuste() {
    sed "s/@USUARIO@/$USUARIO/" <<'EOF'
# Piano Raspberry Pi: la consola tty1 inicia sesión sola (arranque-automatico.sh activar; «quitar» lo deshace)
[Service]
ExecStart=
ExecStart=-/sbin/agetty -o '-p -f -- \\u' --noclear --autologin @USUARIO@ - $TERM
EOF
}

bloque() {
    cat <<EOF
$INICIO_BLOQUE (se quita con: bash $RAIZ/tools/arranque-automatico.sh quitar)
# Solo en la consola de la Pi (tty1), nunca por SSH: abre el piano al encender.
if [ "\$(tty)" = /dev/tty1 ] && [ -z "\${SSH_CONNECTION:-}" ] && [ -x "$LANZADOR" ]; then
    "$LANZADOR"
fi
$FIN_BLOQUE
EOF
}

tiene_bloque() { [ -f "$PERFIL" ] && grep -qF "$INICIO_BLOQUE" "$PERFIL"; }

quitar_bloque() {   # reescribe el perfil sin el bloque (conserva el archivo: permisos y dueño)
    local tmp="$PERFIL.piano-tmp"
    awk -v i="$INICIO_BLOQUE" -v f="$FIN_BLOQUE" \
        'index($0, i) == 1 { fuera = 1 } !fuera { print } index($0, f) == 1 { fuera = 0 }' "$PERFIL" > "$tmp"
    cat "$tmp" > "$PERFIL"
    rm -f "$tmp"
}

activar() {
    [[ "$USUARIO" =~ ^[a-z_][a-z0-9_-]*$ ]] || fallar "nombre de usuario no admitido para el inicio automático: $USUARIO"
    [ "$USUARIO" != root ] || fallar "no se activa para root: usa el usuario del piano"
    case "$RAIZ" in *[\"\$\`\\]*) fallar "la carpeta $RAIZ tiene caracteres no admitidos" ;; esac
    [ -x "$LANZADOR" ] || fallar "falta $LANZADOR: instala primero con instalar.sh"
    # 1) systemd: la consola tty1 inicia sesión sola. Si no se puede, no se toca el perfil.
    if ! cmp -s <(ajuste) "$AJUSTE" 2>/dev/null; then
        { sudo -n mkdir -p "$GETTY_DIR" && ajuste | sudo -n tee "$AJUSTE" >/dev/null && sudo -n systemctl daemon-reload; } \
            || fallar "no se pudo escribir $AJUSTE (hace falta sudo sin contraseña)"
    fi
    # 2) ~/.profile: el bloque al final (si ya estaba, se reemplaza: p. ej. otra carpeta del piano)
    touch "$PERFIL"
    tiene_bloque && quitar_bloque
    if [ -s "$PERFIL" ] && [ -n "$(tail -c 1 "$PERFIL")" ]; then echo >> "$PERFIL"; fi   # terminaba sin salto de línea
    bloque >> "$PERFIL"
    echo "Arranque automático activado: desde el próximo encendido, la Raspberry Pi abre el piano sola."
    echo "   Probarlo ahora: sudo reboot        Quitarlo: bash $RAIZ/tools/arranque-automatico.sh quitar"
}

quitar() {
    if [ -e "$AJUSTE" ]; then
        { sudo -n rm -f "$AJUSTE" && sudo -n systemctl daemon-reload; } \
            || fallar "no se pudo quitar $AJUSTE (hace falta sudo sin contraseña)"
        sudo -n rmdir "$GETTY_DIR" 2>/dev/null || true      # solo si quedó vacía
    fi
    if tiene_bloque; then quitar_bloque; fi
    echo "Arranque automático desactivado: al encender, la consola volverá a pedir usuario y contraseña."
}

estado() {
    local a=no p=no
    [ -f "$AJUSTE" ] && a=sí
    tiene_bloque && p=sí
    echo "inicio de sesión automático en la consola (tty1): $a"
    echo "piano al iniciar sesión en la consola:            $p"
    case "$a$p" in
        sísí) echo "=> activado" ;;
        nono) echo "=> desactivado" ;;
        *)    echo "=> a medias: ejecuta «activar» o «quitar»" ;;
    esac
}

case "${1:-}" in
    activar) activar ;;
    quitar) quitar ;;
    estado) estado ;;
    *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
