# Fase 02 — Compilación ARM64 del piano de modelado físico

## Objetivos

- Obtener un binario LV2 de FigBug/Socalabs **Piano v1.0.14** para aarch64 (Cortex-A53) compatible con Debian 12 de la Raspberry Pi.
- No instalar herramientas de compilación en la Pi (requisito «no instalar software innecesario»).
- Compilación reproducible y verificable (commit fijado, parches documentados, sumas SHA-256).

## Funcionalidades abordadas

| Pieza | Ruta | Función |
|-------|------|---------|
| Imagen de compilación | `tools/build-piano/Dockerfile` | Debian 12 bookworm **arm64** (emulado con QEMU en Docker Desktop), GCC 12.2, glibc 2.36: la misma ABI que la Pi |
| Script de compilación | `tools/build-piano/build-in-container.sh` | Clona el tag `v1.0.14`, **verifica el commit** `99bb41c7…`, aplica parches, compila `Piano_LV2` y `PianoTests` con `-mcpu=cortex-a53`, genera `BUILDINFO`, `SHA256SUMS` y `lv2info.txt`, y verifica el bundle con `lv2ls`/`lv2info`. Es incremental si `/work` es un volumen persistente |
| Parches | `tools/build-piano/patches/` | `0001-fft-order-constructor-cxx20.patch` (ver su README) |
| Artefactos | `dist/piano-1.0.14-arm64/` | `Piano.lv2/` (bundle LV2), `PianoTests` (suite + benchmark de upstream), `reference/` (WAV de referencia), `BUILDINFO`, `SHA256SUMS`, `lv2info.txt` |

### Cómo recompilar

```bash
docker build --platform linux/arm64 -t piano-builder:bookworm-arm64 tools/build-piano
docker volume create piano-work
docker run --rm --platform linux/arm64 -v piano-work:/work \
       -v "<ruta>/dist/piano-1.0.14-arm64:/out" piano-builder:bookworm-arm64
```

(En Git Bash de Windows hay que anteponer `MSYS_NO_PATHCONV=1`.)

## Decisiones tomadas

1. **Compilar en el PC con emulación ARM64, no en la Pi.** Evita instalar cmake y unas 15 bibliotecas `-dev` en la Pi, y la compilación de JUCE no se queda sin RAM (1 GB). Se descartó la compilación cruzada nativa x86→arm64: es más rápida, pero JUCE ejecuta `juce_lv2_helper` (un binario del destino) para generar el `manifest.ttl`, y eso complica la configuración.
2. **Fijar el tag v1.0.14 y verificar su commit** (`99bb41c7b3dac5553a466910e6eb82302a050e50`), la versión que añadió el pedal de sustain.
3. **Solo se compilan los formatos necesarios** (LV2 y la suite de pruebas); VST2, VST3, CLAP y Standalone no se generan.
4. **Parche mínimo en lugar de cambiar de compilador.** GCC 12 rechaza en C++20 un constructor escrito como `fft_order<N>()` (CWG DR 2237). La corrección de una línea (`fft_order()`) no cambia el comportamiento y mantiene el compilador de la propia distribución, con ABI idéntica a la de la Pi.

## Incidencias y su resolución

| # | Incidencia | Causa | Resolución |
|---|-----------|-------|------------|
| 1 | `X11/extensions/XInput2.h: No such file or directory` | Faltaba `libxi-dev` (JUCE 8 usa XInput2) | Se añadió al Dockerfile junto con el resto de la lista oficial de JUCE (`ladspa-sdk`, `libegl-dev`, `libglu1-mesa-dev`, `mesa-common-dev`) |
| 2 | `fft.h:815: expected unqualified-id before ')'` | Constructor con *template-id*, inválido en C++20 con GCC 12 | Parche `0001` |
| 3 | La verificación final devolvía `exit=141` | `lv2info \| head` con `pipefail` (SIGPIPE) y `LV2_PATH=/out` mezclaba archivos que no son bundles | `LV2_PATH` aislado con un enlace solo al bundle, y salida de `lv2info` a archivo |

## Verificación del artefacto

- `lv2info`: URI `https://socalabs.com/piano/`. Puertos: `audio_out_1`, `audio_out_2`, `in` (MIDI atom), `out`, `latency`, `freeWheeling`, `enabled` y 34 parámetros físicos. Funcionalidades requeridas: `urid:map`, `buf-size:boundedBlockLength`, `options:options` (todas soportadas por Jalv 1.6.6).
- En la Pi: SHA-256 verificado, `lv2ls` lista el piano y **todas las bibliotecas se resuelven** (`ldd`). El plugin no enlaza X11 de forma fija (JUCE lo carga con `dlopen` solo si se abre la interfaz gráfica).

## Resultado en la Pi (ver detalle en la fase 03)

- Suite de upstream: 5/5 unitarias y 2/3 de integración superadas en la Pi, con diferencias frente a las referencias x86 de 1,8·10⁻⁶ y 4,4·10⁻⁶ RMS.
- **Suite completa superada en ARM64** (contenedor emulado, 134 min): incluye la prueba de estrés de 4 min, con una diferencia RMS de 1,2·10⁻³ frente a un umbral de 0,1. Registro: `dist/pianotests-arm64-emulado.log`.
- Benchmark: **el plugin no es viable en tiempo real en la Pi 3** (≈ 4–5 voces por núcleo). Por eso se evaluaron otros instrumentos en la fase 03.

## Pendientes

- Ninguno en esta fase (el plugin queda descartado por rendimiento; ver fase 03).

## Checklist

- [x] Imagen de compilación ARM64 Debian 12
- [x] Script reproducible con verificación del commit
- [x] Parche documentado
- [x] Compilación correcta de `Piano_LV2` y `PianoTests`
- [x] Verificación del bundle (`lv2ls`, `lv2info`)
- [x] Despliegue en la Pi (`~/.lv2/Piano.lv2`, `~/piano/bench/`), SHA-256 y `ldd` correctos
- [x] Suite de upstream en la Pi (unitarias + escala + acordes)
- [x] Prueba de estrés de upstream (superada en contenedor ARM64)
- [x] Benchmark en la Pi → no viable en tiempo real (fase 03)
