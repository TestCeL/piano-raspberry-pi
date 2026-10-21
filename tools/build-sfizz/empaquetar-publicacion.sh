#!/bin/bash
# Arma el paquete de sfizz compilado para publicarlo en las Releases de GitHub (fase 09): sfizz_jack (parche 0002) y
# sfizz_render (parche 0001), su BUILDINFO y sumas, los parches, un LEEME en español e inglés y TODAS las licencias de
# sfizz y de los componentes que trae dentro (las exigen su licencia BSD-2 y la de cada componente para redistribuir).
# Comprobaciones antes de empaquetar (si alguna falla, no se crea nada):
#  - las sumas SHA-256 de los programas coinciden con su SHA256SUMS;
#  - el código fuente del que salen las licencias es el oficial (SHA-256 del tar.gz = el de BUILDINFO);
#  - BUILDINFO declara los dos parches del repositorio.
# El tar se crea dentro de Linux (Docker): permisos de ejecución correctos, dueño root y orden fijo.
# Uso (en el PC, Git Bash): tools/build-sfizz/empaquetar-publicacion.sh [CARPETA_BINARIOS] [VOLUMEN_DOCKER]
#   por defecto dist/sfizz-1.2.3-arm64 y el volumen sfizz-work-arm64 de build-in-container.sh
#   -> dist/publicacion/piano-rpi-sfizz-1.2.3-arm64.tar.gz y .tar.gz.sha256
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="${1:-$RAIZ/dist/sfizz-1.2.3-arm64}"
VOLUMEN="${2:-sfizz-work-arm64}"
VERSION=1.2.3
NOMBRE="piano-rpi-sfizz-$VERSION-arm64"
SALIDA="$RAIZ/dist/publicacion"
IMAGEN=debian:bookworm-slim
export MSYS_NO_PATHCONV=1
ruta_nativa() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }   # Docker y Python de Windows

for f in sfizz_jack sfizz_render BUILDINFO SHA256SUMS; do
    [ -s "$BIN/$f" ] || { echo "ERROR: falta $BIN/$f (compilar con tools/build-sfizz)" >&2; exit 1; }
done
# Sumas con Python en el mismo formato que sha256sum de Linux (el de Git Bash escribe "*archivo").
python -I - "$(ruta_nativa "$BIN")" <<'EOF'
import hashlib, os, sys
d = sys.argv[1]
esperadas = dict(reversed(l.split(None, 1)) for l in open(os.path.join(d, "SHA256SUMS"), encoding="ascii").read().splitlines() if l.strip())
for nombre in ("sfizz_jack", "sfizz_render"):
    real = hashlib.sha256(open(os.path.join(d, nombre), "rb").read()).hexdigest()
    if esperadas.get(nombre) != real:
        sys.exit(f"ERROR: la suma de {nombre} no coincide con SHA256SUMS")
print("== Sumas de los programas: correctas")
EOF
grep -q "^sfizz=$VERSION$" "$BIN/BUILDINFO" || { echo "ERROR: BUILDINFO no es de sfizz $VERSION" >&2; exit 1; }
for p in "$RAIZ"/tools/build-sfizz/patches/*.patch; do
    grep -q "$(basename "$p")" "$BIN/BUILDINFO" || { echo "ERROR: BUILDINFO no declara $(basename "$p")" >&2; exit 1; }
done
SHA_FUENTE="$(sed -n 's/^sha256_fuente=//p' "$BIN/BUILDINFO")"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/$NOMBRE/patches" "$SALIDA"
cp "$BIN/sfizz_jack" "$BIN/sfizz_render" "$BIN/BUILDINFO" "$BIN/SHA256SUMS" "$TMP/$NOMBRE/"
cp "$RAIZ"/tools/build-sfizz/patches/* "$TMP/$NOMBRE/patches/"
cat > "$TMP/$NOMBRE/LEEME.txt" <<'EOF'
Piano Raspberry Pi - sfizz 1.2.3 compilado para Raspberry Pi 3 (aarch64, Cortex-A53)
Piano Raspberry Pi - sfizz 1.2.3 built for Raspberry Pi 3 (aarch64, Cortex-A53)

[ES]
Programas
  sfizz_jack    sintetizador SFZ para JACK/PipeWire, con el parche 0002 del proyecto: opción --sample_quality,
                órdenes set_volume y set_cc por la entrada estándar, y cierre inmediato al detenerlo.
  sfizz_render  render MIDI -> WAV sin tiempo real, con el parche 0001 (WAV en coma flotante de 32 bits).
Instalación en la Pi
  mkdir -p ~/piano/bin && install -m 755 sfizz_jack sfizz_render ~/piano/bin/
  Comprobar: sha256sum -c SHA256SUMS
Origen
  sfizz 1.2.3 oficial (BUILDINFO: dirección y SHA-256 del código fuente), compilado con tools/build-sfizz/ del
  repositorio Piano Raspberry Pi. Los parches aplicados están en patches/.
Necesita en el sistema
  libjack.so.0 (pipewire-jack o libjack-jackd2-0) y las bibliotecas de C/C++ de Debian 12 (bookworm).
Licencias
  sfizz se distribuye bajo la licencia BSD-2-Clause (licencias/sfizz/LICENSE; autores en AUTHORS.md). Contiene
  componentes de terceros con sus propias licencias libres (Apache-2.0, MIT, BSD, Boost, zlib, dominio público y
  otras): todos sus avisos están en licencias/sfizz/, en la misma ruta que en el código fuente de sfizz.
  Se entrega SIN GARANTÍA de ningún tipo (ver las licencias).

[EN]
Programs
  sfizz_jack    SFZ synthesizer for JACK/PipeWire, with the project's patch 0002: --sample_quality option,
                set_volume and set_cc commands on standard input, and immediate exit when stopped.
  sfizz_render  offline MIDI -> WAV renderer, with patch 0001 (32-bit floating point WAV).
Installing on the Pi
  mkdir -p ~/piano/bin && install -m 755 sfizz_jack sfizz_render ~/piano/bin/
  Verify: sha256sum -c SHA256SUMS
Origin
  Official sfizz 1.2.3 (BUILDINFO: source URL and SHA-256), built with tools/build-sfizz/ from the Piano Raspberry
  Pi repository. The applied patches are in patches/.
System requirements
  libjack.so.0 (pipewire-jack or libjack-jackd2-0) and the Debian 12 (bookworm) C/C++ libraries.
Licenses
  sfizz is distributed under the BSD-2-Clause license (licencias/sfizz/LICENSE; authors in AUTHORS.md). It contains
  third-party components under their own free licenses (Apache-2.0, MIT, BSD, Boost, zlib, public domain and
  others): all their notices are in licencias/sfizz/, at the same path as in the sfizz source code.
  Provided WITHOUT WARRANTY of any kind (see the licenses).
EOF

echo "== Licencias desde el código fuente oficial y empaquetado (Docker, volumen $VOLUMEN)"
docker run --rm -v "$VOLUMEN:/work:ro" -v "$(ruta_nativa "$TMP"):/staging" -v "$(ruta_nativa "$SALIDA"):/salida" \
    -e SHA_FUENTE="$SHA_FUENTE" -e NOMBRE="$NOMBRE" -e VERSION="$VERSION" "$IMAGEN" /bin/sh -euc '
    echo "$SHA_FUENTE  /work/sfizz-$VERSION.tar.gz" | sha256sum -c - >/dev/null \
        || { echo "ERROR: el código fuente del volumen no es el oficial de BUILDINFO" >&2; exit 1; }
    destino="/staging/$NOMBRE/licencias/sfizz"
    mkdir -p "$destino"
    cd "/work/sfizz-$VERSION"
    find . -path ./tests -prune -o -type f \( -iname "license*" -o -iname "copying*" \) -print | sort > /tmp/lista
    echo ./AUTHORS.md >> /tmp/lista
    tar -cf - -T /tmp/lista | tar -xf - -C "$destino"
    echo "   $(grep -c . /tmp/lista) avisos de licencia copiados"
    cd /staging
    chmod 755 "$NOMBRE/sfizz_jack" "$NOMBRE/sfizz_render"
    find "$NOMBRE" -type d -exec chmod 755 {} +
    find "$NOMBRE" -type f ! -name sfizz_jack ! -name sfizz_render -exec chmod 644 {} +
    fecha="$(sed -n "s/^built_at=//p" "$NOMBRE/BUILDINFO")"
    tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="$fecha" -czf "/salida/$NOMBRE.tar.gz" "$NOMBRE"
    cd /salida && sha256sum "$NOMBRE.tar.gz" > "$NOMBRE.tar.gz.sha256"
    tar -tvzf "$NOMBRE.tar.gz" | awk "{print \$1, \$6}" | grep -E "sfizz_(jack|render)$|LEEME|SHA256SUMS$|patches/0"'
echo "== Listo: $SALIDA/$NOMBRE.tar.gz"
cat "$SALIDA/$NOMBRE.tar.gz.sha256"
