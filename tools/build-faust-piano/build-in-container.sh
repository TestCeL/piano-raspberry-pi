#!/bin/bash
# Genera dos variantes LV2 del piano Faust/STK (Romain Michon, licencia STK-4.3) para aarch64:
#   stkpiano_reverb : modelo original (reverberación dentro de cada voz) + pedal de sustain
#   stkpiano_seco   : igual, sin la reverberación por voz
# Uso (dentro del contenedor): build-in-container.sh   -> artefactos en /out
set -euo pipefail

NVOICES="${NVOICES:-32}"
CPU_FLAGS="${CPU_FLAGS:--mcpu=cortex-a53}"
EJEMPLOS=/usr/share/doc/faust-common/examples/physicalModeling/faust-stk
PATCHES=/usr/local/share/stkpiano-patches
OUT=/out
W="$(mktemp -d)"

declare -A PARCHES=(
    [stkpiano_reverb]="0001-sustain-pedal-cc64.patch"
    [stkpiano_seco]="0001-sustain-pedal-cc64.patch 0002-sin-reverb-por-voz.patch"
)
declare -A NOMBRES=(
    [stkpiano_reverb]="STK Piano (reverb por voz)"
    [stkpiano_seco]="STK Piano (seco)"
)

FAUST_VER="$(dpkg-query -W -f='${Version}' faust)"
mkdir -p "$OUT"

for v in stkpiano_reverb stkpiano_seco; do
    echo "== $v"
    d="$W/$v"
    mkdir -p "$d"
    cp "$EJEMPLOS/piano.dsp" "$EJEMPLOS"/*.h "$d/"
    for p in ${PARCHES[$v]}; do
        patch -s -d "$d" -p1 < "$PATCHES/$p"
        echo "   parche $p"
    done
    sed -i "s|^declare name \"piano\";|declare name \"${NOMBRES[$v]}\";|" "$d/piano.dsp"
    grep -q "declare name \"${NOMBRES[$v]}\"" "$d/piano.dsp" || { echo "ERROR: no se pudo renombrar $v" >&2; exit 1; }
    mv "$d/piano.dsp" "$d/$v.dsp"
    ( cd "$d" && CXXFLAGS="$CPU_FLAGS -I$d" faust2lv2 -nvoices "$NVOICES" "$v.dsp" )
    [ -f "$d/$v.lv2/manifest.ttl" ] || { echo "ERROR: faust2lv2 no generó $v.lv2" >&2; exit 1; }
    rm -rf "${OUT:?}/$v.lv2"
    cp -a "$d/$v.lv2" "$OUT/"
done

{
    echo "fuente=$EJEMPLOS/piano.dsp (faust-common $FAUST_VER, Debian 12)"
    echo "faust=$(faust --version | head -1)"
    echo "nvoices=$NVOICES"
    echo "cpu_flags=$CPU_FLAGS"
    for v in stkpiano_reverb stkpiano_seco; do echo "parches[$v]=${PARCHES[$v]}"; done
    echo "compiler=$(g++ --version | head -1)"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT/BUILDINFO"
( cd "$OUT" && find stkpiano_reverb.lv2 stkpiano_seco.lv2 -type f -print0 | sort -z | xargs -0 sha256sum ) > "$OUT/SHA256SUMS"

echo "== Verificación"
VERIF="$(mktemp -d)"
ln -s "$OUT/stkpiano_reverb.lv2" "$OUT/stkpiano_seco.lv2" "$VERIF/"
LV2_PATH="$VERIF" lv2ls | tee "$OUT/lv2ls.txt"
[ "$(wc -l < "$OUT/lv2ls.txt")" -eq 2 ] || { echo "ERROR: se esperaban 2 plugins" >&2; exit 1; }
while read -r uri; do
    LV2_PATH="$VERIF" lv2info "$uri" > "$OUT/lv2info-$(basename "$uri").txt"
    grep -E "^\s+Name:|Symbol:" "$OUT/lv2info-$(basename "$uri").txt" | head -12
done < "$OUT/lv2ls.txt"
file "$OUT"/*.lv2/*.so
echo "== OK"
