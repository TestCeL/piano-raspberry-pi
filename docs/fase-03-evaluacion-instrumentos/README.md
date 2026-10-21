# Fase 03 — Evaluación de instrumentos en tiempo real en la Pi 3

## Objetivos

- Medir en la propia Raspberry Pi 3, en **tiempo real** (jalv + PipeWire-JACK, 44,1 kHz, quantum 256 = 5,8 ms), la carga de CPU y los cortes (xruns) de cada candidato.
- Evaluar la calidad sonora con escucha real por la Sound BlasterX G1.
- Verificar niveles (saturación) antes de enviar audio a los auriculares del usuario.
- Seleccionar el instrumento con el usuario.

## Herramientas creadas (`tools/`)

| Herramienta | Función | Pruebas |
|-------------|---------|---------|
| `midi/generar_midis_prueba.py` | MIDIs de evaluación: escala con dinámicas, acordes con pedal, arpegios densos, carga de 4–32 voces sostenidas | `midi/test_generar_midis_prueba.py` (11 pruebas) |
| `pi/pw_puertos.py` | Lista los puertos de un nodo PipeWire (dirección/tipo) desde `pw-dump` | `pi/test_pw_puertos.py` (5) |
| `pi/lib-pw.sh` | `destinos_de` (enlaces de un puerto) y `resumir_pwtop` (B/Q máx/medio y xruns de un nodo) | `pi/test_lib_pw.sh` (8) |
| `pi/analizar_wav.py` | Pico/RMS en dBFS y muestras ≥ 0 dBFS de un WAV (PCM o float 32) | `pi/test_analizar_wav.py` (7) |
| `pi/escuchar-midi.sh` | Reproduce MIDIs por piano (+ efecto opcional) hacia la G1 o en silencio (`-s`), mide B/Q/xruns por archivo, graba en f32 (`-r`). **Instancia única con bloqueo**; revierte los ajustes temporales de PipeWire | `pi/test_escuchar_midi_integracion.sh` (13 comprobaciones) |
| `pi/detener-audio.sh` | Detiene de inmediato cualquier reproducción de prueba y verifica que no queda nada | incluido en la prueba de integración |
| `build-faust-piano/` | Compilación ARM64 del piano Faust/STK como LV2 polifónico (32 voces) con parches | verificación `lv2ls`/`lv2info` en el script |

Material MIDI en `~/piano/midi/` de la Pi: los generados + obras de dominio público de [Mutopia](https://www.mutopiaproject.org): Satie, *Gymnopédie n.º 1*; Bach, *Preludio BWV 846*; Chopin, *Fantaisie-Impromptu Op. 66*.

## Resultados de capacidad (tiempo real, Pi 3 a 1,2 GHz, sin *throttling*)

B/Q = tiempo de proceso / duración del bloque. Por encima de ~0,8 hay riesgo de cortes; por encima de 1 hay cortes seguros.

| Instrumento | Síntesis | Carga medida | xruns | Veredicto |
|-------------|----------|--------------|-------|-----------|
| FigBug/Socalabs Piano 1.0.14 | Modelado físico completo (DWGS) | 4 voces: B/Q 1,47 · 8: 2,3 · 16: 4,1 · 32: 6,4 | miles | **No viable** (≈ 4–5 voces por núcleo) |
| STK Piano (Faust) con reverb por voz | Guía de ondas conmutada | B/Q ≈ 1,0 constante | miles | No viable |
| **STK Piano (Faust), seco** | Guía de ondas conmutada (modelado físico) + pedal CC64 añadido | B/Q ≈ 0,46 constante (Faust calcula las 32 voces siempre) | **0** | Viable |
| **mda Piano** (mda-lv2 1.2.10) | Híbrido síntesis + muestras internas (no es modelado físico, no es SoundFont) | 32 voces: B/Q 0,16 · Satie: 0,06 | **0** | Viable, el más ligero |
| mda Ambience (reverb de sala) | — | B/Q 0,01 | 0 | Viable como efecto |

### Análisis de FigBug

- El benchmark de upstream en la Pi da 8,68× / 3,43× / 2,44× / 1,50× tiempo real (1/4/8/16 voces), unas 19 veces más lento que en x86. Pero ese benchmark pulsa notas que se apagan durante sus 30 s (cada voz se elimina al decaer 80 dB), así que **sobrestima** la capacidad con teclas mantenidas.
- En tiempo real el coste es ≈ 4–5 µs por voz y muestra (≈ 35 % de un núcleo por voz). No depende del tamaño de bloque (256 o 1024) y casi no cambia con los parámetros físicos (barrido de `Downsample`, `Dwgs4`, longitud/radio de cuerda, tabla armónica…).
- Repartir las voces entre los 4 núcleos exigiría modificar el motor y aun así no llegaría a las 24–32 voces necesarias con pedal.

### Suite de pruebas de upstream (FigBug) en ARM64

- En la Pi: 5/5 unitarias y 2/3 de integración superadas (escala: RMS de diferencia 1,8·10⁻⁶; acordes: 4,4·10⁻⁶ frente a las referencias x86). La prueba de estrés se interrumpió en la Pi (≈ 0,2× tiempo real) y se reejecuta en el contenedor ARM64 emulado.

## Incidencia de escucha (2026-10-19) y corrección

**Síntomas reportados por el usuario:** «saturación muy fuerte, como un pre saturado» y «se escucha 2 veces».

**Causas:**
1. Al interrumpir comandos desde el PC se cortó SSH, pero sin tty la Pi no envía ninguna señal: `aplaymidi` y las unidades jalv siguieron vivos. Dos interpretaciones de la misma obra sonaron superpuestas.
2. **Saturación digital previa al volumen**: mda Piano solo, con los acordes con pedal, da un pico de **+5,0 dBFS** (2106 muestras ≥ 0 dBFS). Al convertirse a S16 para la G1 se recorta. Bajar el volumen de la G1 no lo arregla porque atenúa una señal ya recortada.

**Corrección:**
- `escuchar-midi.sh` con bloqueo exclusivo (`flock`), archivo PID, `aplaymidi` controlado por el script (`wait`) y *traps* INT/TERM/HUP; al arrancar detiene cualquier reproducción previa.
- `detener-audio.sh` para parar al instante.
- Medición de niveles en f32 (`-r` + `analizar_wav.py`) **obligatoria en silencio antes de reproducir** para el usuario.
- Pendiente: ajuste de ganancia de la cadena (ver Pendientes).

Volumen de la G1 cambiado a petición del usuario: 0,40 → **0,20** (−23 dB → −41 dB en el control `Speaker`).

### Segunda incidencia: «sigue clipeando en las partes fuertes»

- Con −12 dB de ganancia (`mda Ambience output=0.2`), la señal grabada justo antes de la G1 estaba **limpia** (pico −2,1 dBFS, 0 muestras ≥ 0 dBFS).
- Causa real: el MIDI de Mutopia (`12-chopin-fantaisie-impromptu-op66.mid`, generado por LilyPond) tiene **todas las notas a velocidad 127**; las dinámicas van por CC7 (823 eventos), que mda Piano ignora. Cada nota sonaba con el martillo más duro, con el timbre más áspero de mda.
- El usuario aportó un MIDI interpretado (`13-chopin-fantaisie-impromptu-fontana.mid`, 3049 notas, velocidades 16–127, mediana 64; coincide con la transcripción del rollo Duo-Art de Harold Bauer). Con mda + Ambience a −12 dB: pico −6,3 dBFS, 0 muestras ≥ 0 dBFS.
- La comparación A/B controlada confirmó la fórmula de ganancia de mda Ambience: `10^(2·output−1)` (de 0,5 a 0,2 = −12,0 dB). Una medición anterior, hecha en la misma sesión tras otra obra, estaba contaminada por el estado previo: **las mediciones de nivel se hacen siempre en sesiones limpias**.

### Interrupciones desde el PC

- Al interrumpir un comando, el entorno de control **no mata** el `ssh` local, así que ni SIGHUP ni el vigilante `-x` detienen la reproducción en la Pi. Procedimiento: tras cada interrupción, `ssh usuario@ip-de-la-pi ~/piano/tools/detener-audio.sh`.
- El usuario puede detener el audio por su cuenta con ese mismo comando desde PowerShell.
- El vigilante `-x` sigue siendo útil para cortes reales de SSH (probado con entrada y salida cerradas a la vez).

## Decisiones tomadas

- FigBug descartado por rendimiento (medido, no supuesto).
- La reverb por voz de STK descartada; se usa una reverb global (mda Ambience) tras el piano.
- Interés del usuario por **mda Piano + reverb** por ser liviano.
- **2026-10-19: el usuario flexibiliza el requisito n.º 1** («NO utilizar SoundFonts») para evaluar un piano muestreado: **Salamander Grand Piano V3** (Alexander Holm, Yamaha C5, CC-BY 3.0). Motivo: en la Pi 3 los pianos sintetizados viables (mda, STK) suenan poco realistas y el modelado físico realista (FigBug) no es viable. La evaluación sigue en la fase 04.

## Pendientes

- [ ] Ajustar la ganancia de la cadena para picos ≤ −1 dBFS en el peor caso (Chopin, acordes *ff* con pedal) y valorar un limitador final de seguridad.
- [ ] Escucha de mda Piano + Ambience con la ganancia corregida (Fantaisie-Impromptu).
- [ ] Decisión final del instrumento con el usuario.

## Checklist

- [x] Herramientas de medición con pruebas (44 comprobaciones)
- [x] Capacidad en tiempo real de FigBug, STK (2 variantes), mda Piano y mda Ambience
- [x] Escucha STK Piano (acordes con pedal + Satie): 0 xruns
- [x] Diagnóstico y corrección de la doble reproducción
- [x] Diagnóstico de la saturación (medida: +5,0 dBFS)
- [x] Corrección de la ganancia y verificación en silencio (A/B controlado)
- [x] Escucha de mda Piano + reverb (Fontana, señal limpia; interrumpida por el usuario para valorar SoundFonts)
- [ ] Selección final aprobada por el usuario → continúa en la fase 04 (Salamander)
