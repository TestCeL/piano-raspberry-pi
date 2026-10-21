#!/bin/bash
# Letra grande en la consola de la Raspberry (sin X): fuente Terminus 16x32 (Uni2).
# En el monitor 1920x1080 la consola pasa de 240x67 a 120x33 caracteres: la interfaz del piano llena la
# pantalla y se lee a distancia. Autorizado por el usuario (2026-10-19). Reversible.
#
# Uso: fuente-consola.sh aplicar | revertir | estado
#   aplicar   guarda /etc/default/console-setup en .antes-piano (una sola vez) y fija Terminus 16x32
#   revertir  restaura la copia guardada
#   estado    muestra la configuración y el tamaño actual de tty1
set -euo pipefail

CONF=/etc/default/console-setup
COPIA=/etc/default/console-setup.antes-piano
FUENTE=/usr/share/consolefonts/Uni2-Terminus32x16.psf.gz
FUENTE_ORIGINAL=/usr/share/consolefonts/Uni2-VGA16.psf.gz

tamano() { stty -F /dev/tty1 size 2>/dev/null || sudo -n stty -F /dev/tty1 size; }

aplicar_config() {
    sudo -n setupcon --force >/dev/null 2>&1 || sudo -n setupcon >/dev/null
}

case "${1:-estado}" in
    aplicar)
        [ -f "$FUENTE" ] || { echo "ERROR: no existe $FUENTE" >&2; exit 1; }
        [ -f "$COPIA" ] || sudo -n cp -p "$CONF" "$COPIA"
        sudo -n sed -i -e 's/^CODESET=.*/CODESET="Uni2"/' -e 's/^FONTFACE=.*/FONTFACE="Terminus"/' \
                       -e 's/^FONTSIZE=.*/FONTSIZE="16x32"/' "$CONF"
        aplicar_config
        echo "Fuente Terminus 16x32 aplicada. tty1: $(tamano) (filas columnas)"
        ;;
    revertir)
        [ -f "$COPIA" ] || { echo "No hay copia previa ($COPIA): nada que revertir." >&2; exit 1; }
        sudo -n cp -p "$COPIA" "$CONF"
        aplicar_config
        # La configuración original no fija fuente (FONTFACE=""): setupcon no la cambia y la Terminus seguiría
        # cargada. Se carga la VGA 8x16 (equivalente a la del kernel) en las consolas activas; en el próximo
        # arranque la configuración restaurada deja la fuente del kernel.
        for tty in /dev/tty[1-6]; do
            sudo -n setfont -C "$tty" "$FUENTE_ORIGINAL" 2>/dev/null || true
        done
        echo "Configuración original restaurada. tty1: $(tamano) (filas columnas)"
        ;;
    estado)
        grep -E '^(CODESET|FONTFACE|FONTSIZE)=' "$CONF"
        echo "copia previa: $([ -f "$COPIA" ] && echo "$COPIA" || echo 'no')"
        echo "tty1: $(tamano) (filas columnas)"
        ;;
    *)
        echo "uso: $0 aplicar | revertir | estado" >&2
        exit 2
        ;;
esac
