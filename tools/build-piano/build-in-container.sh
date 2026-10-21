#!/bin/bash
# Compila FigBug/Socalabs Piano (LV2) y su suite de pruebas para aarch64 (Cortex-A53).
# Uso (dentro del contenedor): build-in-container.sh  -> deja los artefactos en /out
set -euo pipefail

REPO="https://github.com/FigBug/Piano.git"
TAG="${PIANO_TAG:-v1.0.14}"
COMMIT="${PIANO_COMMIT:-99bb41c7b3dac5553a466910e6eb82302a050e50}"
CPU_FLAGS="${CPU_FLAGS:--mcpu=cortex-a53}"
SRC=/work/src
BUILD=/work/build
OUT=/out

# /work puede ser un volumen persistente: si ya contiene el commit correcto se reutiliza
# (compilación incremental); si no, se clona desde cero.
if [ -d "$SRC/.git" ] && [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null)" = "$COMMIT" ]; then
    echo "== Reutilizando fuente existente @ $COMMIT"
else
    echo "== Clonando $REPO @ $TAG"
    rm -rf "$SRC" "$BUILD"
    git -c advice.detachedHead=false clone --quiet --branch "$TAG" --depth 1 "$REPO" "$SRC"
fi
ACTUAL="$(git -C "$SRC" rev-parse HEAD)"
if [ "$ACTUAL" != "$COMMIT" ]; then
    echo "ERROR: el tag $TAG apunta a $ACTUAL y se esperaba $COMMIT" >&2
    exit 1
fi
git -C "$SRC" submodule update --init --recursive --depth 1 --quiet \
  || git -C "$SRC" submodule update --init --recursive --quiet

# Parches locales (ver tools/build-piano/patches/README.md). Idempotente.
PATCH_DIR=/usr/local/share/piano-patches
APLICADOS=""
for p in "$PATCH_DIR"/*.patch; do
    [ -e "$p" ] || continue
    if git -C "$SRC" apply --reverse --check "$p" 2>/dev/null; then
        echo "== Parche ya aplicado: $(basename "$p")"
    else
        git -C "$SRC" apply "$p"
        echo "== Parche aplicado: $(basename "$p")"
    fi
    APLICADOS="$APLICADOS $(basename "$p")"
done

echo "== Configurando (Release, $CPU_FLAGS)"
cmake -S "$SRC" -B "$BUILD" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTS=ON \
      -DCMAKE_C_FLAGS="$CPU_FLAGS" \
      -DCMAKE_CXX_FLAGS="$CPU_FLAGS"

echo "== Compilando Piano_LV2 y PianoTests"
cmake --build "$BUILD" --target Piano_LV2 PianoTests -j"$(nproc)"

LV2_DIR="$(find "$BUILD" -type d -name 'Piano.lv2' -path '*Release*' | head -1)"
TESTS_BIN="$(find "$BUILD" -type f -name 'PianoTests' -perm -u+x | head -1)"
[ -n "$LV2_DIR" ] || { echo "ERROR: no se generó Piano.lv2" >&2; exit 1; }
[ -n "$TESTS_BIN" ] || { echo "ERROR: no se generó PianoTests" >&2; exit 1; }
[ -f "$LV2_DIR/manifest.ttl" ] || { echo "ERROR: Piano.lv2 sin manifest.ttl" >&2; exit 1; }

echo "== Copiando artefactos a $OUT"
rm -rf "$OUT/Piano.lv2" "$OUT/PianoTests" "$OUT/reference"
mkdir -p "$OUT"
cp -a "$LV2_DIR" "$OUT/Piano.lv2"
cp -a "$TESTS_BIN" "$OUT/PianoTests"
cp -a "$SRC/tests/reference" "$OUT/reference"

{
    echo "repo=$REPO"
    echo "tag=$TAG"
    echo "commit=$ACTUAL"
    echo "cpu_flags=$CPU_FLAGS"
    echo "patches=${APLICADOS# }"
    echo "build_type=Release"
    echo "compiler=$(g++ --version | head -1)"
    echo "glibc=$(ldd --version | head -1)"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT/BUILDINFO"

( cd "$OUT" && find Piano.lv2 PianoTests -type f -print0 | sort -z | xargs -0 sha256sum ) > "$OUT/SHA256SUMS"

echo "== Verificación del bundle LV2"
file "$OUT/Piano.lv2/"*.so "$OUT/PianoTests"
# LV2_PATH aislado: solo el bundle generado (el resto de /out no son bundles LV2)
VERIF="$(mktemp -d)"
ln -s "$OUT/Piano.lv2" "$VERIF/Piano.lv2"
PLUGINS="$(LV2_PATH="$VERIF" lv2ls)"
echo "$PLUGINS"
[ "$PLUGINS" = "https://socalabs.com/piano/" ] || { echo "ERROR: lv2ls no lista exactamente el piano" >&2; exit 1; }
LV2_PATH="$VERIF" lv2info https://socalabs.com/piano/ > "$OUT/lv2info.txt"
grep -E "Name:|Binary:|Required Features|Has latency" "$OUT/lv2info.txt"
rm -rf "$VERIF"
echo "== OK"
