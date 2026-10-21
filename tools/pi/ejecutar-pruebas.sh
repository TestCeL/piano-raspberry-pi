#!/bin/bash
# Validación completa del proyecto EN LA RASPBERRY: pruebas unitarias + integración de flujos reales
# (secuenciador ALSA, PipeWire, cadena de audio en tiempo real, limpieza). Todo en modo silencio.
# Uso: bash ejecutar-pruebas.sh        (código 0 solo si todo pasa)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
# Las pruebas detienen el piano: no ejecutarlas si alguien lo está usando (salvo FORZAR=1).
# Patrón anclado al inicio: no confundir con una shell cuyo texto de orden mencione la interfaz.
if [ "${FORZAR:-0}" != 1 ] && { pgrep -f '^python3 \S*teclado_piano\.py --titulo' >/dev/null || systemctl --user is-active --quiet piano-vivo-cadena; }; then
    echo "El piano está en uso (interfaz o motor en marcha): no se ejecutan las pruebas. Ciérralo (ESC) o usa FORZAR=1." >&2
    exit 4
fi
RESULTADOS=()
FALLOS=0

correr() {  # nombre, comando...
    local nombre="$1"; shift
    local salida rc
    salida="$("$@" 2>&1)"; rc=$?
    if [ "$rc" -eq 0 ]; then
        RESULTADOS+=("OK     $nombre")
    else
        RESULTADOS+=("FALLO  $nombre")
        FALLOS=$((FALLOS + 1))
        echo "----- $nombre (rc=$rc) -----"; tail -30 <<<"$salida"
    fi
}

correr "unidad: generador de MIDIs"        python3 -m unittest test_generar_midis_prueba
correr "unidad: puertos PipeWire"           python3 -m unittest test_pw_puertos
correr "unidad: análisis de WAV"            python3 -m unittest test_analizar_wav
correr "unidad: teclado (lógica, binario, interfaz)" python3 -m unittest test_teclado_piano
correr "unidad: lib-pw.sh"                  bash test_lib_pw.sh
correr "unidad: enrutador MIDI"             python3 -m unittest test_enrutador_midi
correr "unidad: cambio de instrumento (enrutador)"   python3 -m unittest test_enrutador_instrumentos
correr "unidad: catálogo de instrumentos"   python3 -m unittest test_catalogo_instrumentos
correr "unidad: medición de instrumentos"   python3 -m unittest test_medir_instrumentos
correr "unidad: ensemble de cuerdas"        python3 -m unittest test_generar_cuerdas
correr "unidad: créditos del proyecto"      python3 -m unittest test_generar_creditos
correr "unidad: descarga de instrumentos"   bash test_descargar_instrumentos.sh
correr "unidad: instalación del Softify"    python3 -m unittest test_instalar_softify
correr "unidad: instalador"                 bash test_instalar.sh
correr "unidad: salidas de audio"           python3 -m unittest test_salidas_audio
correr "unidad: arranque automático"        bash test_arranque_automatico.sh
correr "unidad: pantalla de inicio"         python3 -m unittest test_pantalla_inicio
correr "unidad: lanzador (piano-teclado.sh)" bash test_piano_teclado.sh
correr "integración: enrutador MIDI con ALSA real"   python3 -m unittest test_enrutador_integracion
correr "integración: teclado -> ALSA -> PipeWire"    bash test_teclado_alsa_integracion.sh
correr "integración: reproducción de prueba (escuchar-midi)" bash test_escuchar_midi_integracion.sh
correr "integración: órdenes de sfizz_jack (parche 0002)"     bash test_sfizz_jack_ordenes.sh
correr "integración: piano en vivo"         bash test_piano_en_vivo_integracion.sh
correr "integración: salida de audio (F10)"  bash test_salidas_integracion.sh

echo
printf '%s\n' "${RESULTADOS[@]}"
echo
if [ "$FALLOS" -eq 0 ]; then echo "VALIDACIÓN COMPLETA: TODO PASA"; else echo "VALIDACIÓN: $FALLOS SUITE(S) FALLAN"; exit 1; fi
