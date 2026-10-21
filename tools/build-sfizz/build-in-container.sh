#!/bin/bash
# Compila sfizz (sfztools) para aarch64/Cortex-A53: sfizz_jack (sintetizador JACK con entrada MIDI)
# y sfizz_render (render offline MIDI -> WAV). Biblioteca enlazada estáticamente (sin libsfizz.so).
# Uso (dentro del contenedor): build-in-container.sh  -> artefactos en /out
set -euo pipefail

VERSION="${SFIZZ_VERSION:-1.2.3}"
SHA256="${SFIZZ_SHA256:-a9339eac7620d7f0f6b44bdfe860680fab73e66efad4b5f15b21198dd9436822}"
URL="https://github.com/sfztools/sfizz/releases/download/$VERSION/sfizz-$VERSION.tar.gz"
CPU_FLAGS="${CPU_FLAGS--mcpu=cortex-a53}"   # vacío permitido (amd64)
W=/work
OUT=/out

mkdir -p "$W" "$OUT"
cd "$W"
if [ ! -d "sfizz-$VERSION" ]; then
    curl -sSL -o "sfizz-$VERSION.tar.gz" "$URL"
    echo "$SHA256  sfizz-$VERSION.tar.gz" | sha256sum -c -
    tar -xzf "sfizz-$VERSION.tar.gz"
fi

# Parches locales (ver patches/README.md). Idempotente.
APLICADOS=""
for p in /usr/local/share/sfizz-patches/*.patch; do
    [ -e "$p" ] || continue
    if patch -s -d "sfizz-$VERSION" -p1 -R --dry-run -f < "$p" >/dev/null 2>&1; then
        echo "== Parche ya aplicado: $(basename "$p")"
    else
        patch -s -d "sfizz-$VERSION" -p1 < "$p"
        echo "== Parche aplicado: $(basename "$p")"
    fi
    APLICADOS="$APLICADOS $(basename "$p")"
done

cmake -S "sfizz-$VERSION" -B build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_C_FLAGS="$CPU_FLAGS" -DCMAKE_CXX_FLAGS="$CPU_FLAGS" \
      -DSFIZZ_JACK=ON -DSFIZZ_RENDER=ON -DSFIZZ_SHARED=OFF \
      -DSFIZZ_TESTS=OFF -DSFIZZ_BENCHMARKS=OFF -DSFIZZ_DEMOS=OFF -DSFIZZ_DEVTOOLS=OFF \
      -DSFIZZ_GIT_SUBMODULE_CHECK=OFF
cmake --build build --target sfizz_jack sfizz_render -j"$(nproc)"

for b in sfizz_jack sfizz_render; do
    f="$(find build -type f -name "$b" -perm -u+x | head -1)"
    [ -n "$f" ] || { echo "ERROR: no se generó $b" >&2; exit 1; }
    cp -a "$f" "$OUT/$b"
done
{
    echo "sfizz=$VERSION"
    echo "fuente=$URL"
    echo "sha256_fuente=$SHA256"
    echo "cpu_flags=$CPU_FLAGS"
    echo "arch=$(uname -m)"
    echo "patches=${APLICADOS# }"
    echo "compiler=$(g++ --version | head -1)"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT/BUILDINFO"
( cd "$OUT" && sha256sum sfizz_jack sfizz_render ) > "$OUT/SHA256SUMS"
file "$OUT/sfizz_jack" "$OUT/sfizz_render"
"$OUT/sfizz_render" --help | head -5
echo "== OK"
