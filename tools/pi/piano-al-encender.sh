#!/bin/bash
# Se ejecuta al iniciar sesión en la consola de la Pi (tty1), desde ~/.profile, con el arranque automático activado
# (arranque-automatico.sh activar; fase 11):
#  1) abre el piano (comando «piano») pidiéndole que antes espere hasta PIANO_ESPERA_TARJETA s (20) a la tarjeta
#     preferida: al encender, WirePlumber la publica unos segundos después de iniciar la sesión. Si no llega, el piano
#     usa otra y lo avisa (fase 10). Mientras tanto se ve la pantalla de inicio.
#  2) al salir con ESC, o si no pudo abrirse, deja la consola con indicaciones. No se reintenta en bucle: si algo
#     falla, el error queda a la vista (y siempre se puede entrar por SSH). Con F12, el piano apaga la Pi.
# Variables (pruebas): PIANO_COMANDO (piano), PIANO_ESPERA_TARJETA (20)
set -uo pipefail
COMANDO="${PIANO_COMANDO:-piano}"
ESPERA="${PIANO_ESPERA_TARJETA:-20}"

"$COMANDO" --esperar-tarjeta "$ESPERA"
rc=$?
echo
if [ "$rc" -eq 0 ]; then
    echo "Piano cerrado."
else
    echo "El piano no pudo abrirse o se cerró por un error (código $rc): el detalle está más arriba."
fi
echo "   piano            vuelve a abrirlo"
echo "   sudo poweroff    apaga la Raspberry Pi (desenchúfala cuando se apague la luz verde)"
echo
exit 0
