#!/bin/bash
# Prepara en el PC el piano vertical "Upright Piano KW" (FreePats, CC0) y lo copia a la Raspberry (fase 07).
# Se distribuye solo en .7z y la Pi no tiene 7-Zip (no se instala software solo para esto): se descarga,
# se verifica (SHA-256) y se extrae en un contenedor Docker del PC, y se envía a la Pi como tar por SSH.
# Al final compara las sumas SHA-256 de todos los archivos en ambos lados (orden C: independiente del
# idioma del sistema) y lo anota en el manifiesto.
#
# Uso (en el PC, Git Bash): tools/instrumentos/preparar-upright-kw.sh usuario@ip-de-la-pi   (o con PIANO_PI)
set -euo pipefail

PI="${1:-${PIANO_PI:-}}"          # la Pi por SSH: argumento o variable PIANO_PI
[ -n "$PI" ] || { echo "Uso: $0 usuario@ip-de-la-pi   (o define PIANO_PI=usuario@ip-de-la-pi)" >&2; exit 2; }
URL="https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-SFZ+FLAC-20220221.7z"
SHA256_ESPERADO="3a66da3b25a2fd9499d90bcf09f1aee4431825796e249361b48af59b1201e703"
VOLUMEN=instrumentos-pc          # volumen Docker de trabajo (reutiliza la descarga si ya existe)
DESTINO='piano/instrumentos/upright'
IMAGEN=debian:bookworm-slim
export MSYS_NO_PATHCONV=1

echo "== Descarga, verificación y extracción (Docker, volumen $VOLUMEN)"
docker volume create "$VOLUMEN" >/dev/null
docker run --rm --platform linux/amd64 -v "$VOLUMEN:/i" "$IMAGEN" bash -c '
set -euo pipefail
cd /i
if [ ! -s kw.7z ] || [ "$(sha256sum kw.7z | cut -d" " -f1)" != "'"$SHA256_ESPERADO"'" ]; then
    apt-get update -qq >/dev/null && apt-get install -y -qq curl ca-certificates >/dev/null 2>&1
    curl -sSL --retry 3 -o kw.7z.part "'"$URL"'" && mv kw.7z.part kw.7z
fi
suma="$(sha256sum kw.7z | cut -d" " -f1)"
[ "$suma" = "'"$SHA256_ESPERADO"'" ] || { echo "ERROR: SHA-256 inesperado: $suma" >&2; exit 1; }
echo "   SHA-256 correcto ($(stat -c %s kw.7z) bytes)"
if [ ! -s upright/UprightPianoKW-SFZ+FLAC-20220221/UprightPianoKW-20220221.sfz ]; then
    command -v 7z >/dev/null || { apt-get update -qq >/dev/null && apt-get install -y -qq p7zip-full >/dev/null 2>&1; }
    rm -rf upright && 7z x -y -oupright kw.7z >/dev/null
fi
cd upright && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /i/upright.sha256
echo "   $(wc -l < /i/upright.sha256) archivos, $(du -sh . | cut -f1)"
'

echo "== Copia a $PI:~/$DESTINO"
ssh -n -o BatchMode=yes "$PI" "rm -rf ~/$DESTINO.part && mkdir -p ~/$DESTINO.part"
docker run --rm --platform linux/amd64 -v "$VOLUMEN:/i:ro" "$IMAGEN" tar -C /i/upright -cf - . \
    | ssh -o BatchMode=yes "$PI" "tar -xf - -C ~/$DESTINO.part"

echo "== Verificación de los archivos en la Pi"
LOCAL="$(docker run --rm --platform linux/amd64 -v "$VOLUMEN:/i:ro" "$IMAGEN" sha256sum /i/upright.sha256 | cut -d' ' -f1)"
REMOTO="$(ssh -n -o BatchMode=yes "$PI" "cd ~/$DESTINO.part && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1")"
[ "$LOCAL" = "$REMOTO" ] || { echo "ERROR: los archivos copiados no coinciden (PC $LOCAL, Pi $REMOTO)" >&2; exit 1; }
TAM="$(docker run --rm --platform linux/amd64 -v "$VOLUMEN:/i:ro" "$IMAGEN" stat -c %s /i/kw.7z)"
ssh -n -o BatchMode=yes "$PI" "set -e; rm -rf ~/$DESTINO; mv ~/$DESTINO.part ~/$DESTINO
    m=~/piano/instrumentos/MANIFIESTO-descargas.txt; touch \$m; sed -i '/^upright /d' \$m
    echo \"upright freepats:UprightPianoKW-SFZ+FLAC-20220221.7z $TAM $SHA256_ESPERADO \$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> \$m
    du -sh ~/$DESTINO"
echo "== Listo: Upright Piano KW en $PI:~/$DESTINO (todas las sumas coinciden)"
