#!/bin/bash
# Instalador del Piano Raspberry Pi: ejecutar en la Raspberry Pi desde esta carpeta. Opciones: ./instalar.sh --help
exec bash "$(cd "$(dirname "$0")" && pwd)/tools/pi/instalar.sh" "$@"
