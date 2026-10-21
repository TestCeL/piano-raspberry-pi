# Fase 04 — Piano muestreado: Salamander Grand Piano con sfizz

## Contexto y decisión

- 2026-10-19: el usuario **flexibiliza el requisito n.º 1** («NO utilizar SoundFonts SF2/SFZ») para evaluar un piano muestreado, tras comprobar en la fase 03 que los pianos sintetizados viables en la Pi 3 (mda, STK) suenan poco realistas y que el modelado físico realista (FigBug) no es viable en tiempo real.
- El resto de requisitos se mantiene: sin demos, software libre, sin escritorio, salida por la G1, MIDI, arranque autónomo.

## Objetivos

- Ejecutar el **Salamander Grand Piano V3** (Alexander Holm, Yamaha C5, 16 capas de velocidad, CC-BY 3.0) en tiempo real en la Pi 3, sin cortes.
- Medir CPU, RAM, cortes y niveles; escucha con el MIDI interpretado del usuario.

## Componentes

| Componente | Origen | Verificación |
|------------|--------|--------------|
| Salamander V3, **44,1 kHz / 16 bits**, SFZ + WAV (641 muestras, 1,2 GB descomprimido) | FreePats: `SalamanderGrandPianoV3+20161209_44khz16bit.tar.xz` (412 313 804 bytes) | SHA-256 `58750eb1366761e187f71ddb9b932355ea894d28ec4331e74ab8acb44c819936` (PC y Pi) |
| sfizz 1.2.3 (`sfizz_jack`, `sfizz_render`), ARM64 Cortex-A53, enlace estático | `tools/build-sfizz/` (fuente oficial verificada por SHA-256) | `dist/sfizz-1.2.3-arm64/SHA256SUMS` comprobado en la Pi |
| sfizz 1.2.3 amd64 (solo render/medición en el PC) | mismo script, `--build-arg PLATAFORMA=linux/amd64`, `CPU_FLAGS=""` | — |
| Parche `0001-sfizz-render-float32` | `tools/build-sfizz/patches/` | Solo la herramienta de render (para medir picos > 0 dBFS) |

En la Pi: binarios en `~/piano/bin/`, instrumento en `~/piano/instrumentos/SalamanderGrandPianoV3_44.1khz16bit/`.

### Por qué sfizz (y no FluidSynth/LinuxSampler)

- En Debian 12 no hay paquete de sfizz y OBS solo publica amd64: se compila.
- sfizz reproduce el SFZ original completo: 16 capas, *release* de martillo y resonancias (`trigger=release`), ruido de pedal ligado al CC64. Además carga desde disco con precarga, así que el instrumento (1,2 GB) no necesita caber en la RAM (906 MiB).
- Experiencia en Pi 3 (foro de Zynthian): LinuxSampler se queda en ~16 voces. Las conversiones SF2 del Salamander que circulan tienen defectos (posición estéreo, ruidos), y FluidSynth carga el SF2 entero en RAM.
- `sfizz_jack` es un cliente JACK independiente (sin jalv ni plugin): más ligero.

### Detalles de integración descubiertos

- `sfizz_jack` publica sus puertos **antes** de cargar el instrumento: `escuchar-midi.sh` espera el mensaje `Instrument loaded` (`PIANO_LISTO`) antes de enviar MIDI.
- Con EOF en la entrada estándar, `sfizz_jack` entra en un bucle al 100 % de CPU (`getline`): se le da una entrada que nunca se cierra (`sleep infinity |`).
- Su salida se fuerza a línea por línea con `stdbuf -oL` para poder leerla en el journal.
- Las rutas del SFZ usan `\` (estilo Windows); sfizz las resuelve en Linux sin cambios.

## Resultados

### Niveles (render offline, sfizz_render float32)

| MIDI | Pico | RMS | Muestras ≥ 0 dBFS |
|------|------|-----|-------------------|
| Fontana (interpretado por el usuario) — PC | −7,5 dBFS | −29 dBFS | 0 |
| Mutopia (todas las notas a 127, peor caso) — PC | −0,0 dBFS | −17 dBFS | 0 |
| Acordes con pedal — Pi (ARM64) | −9,8 dBFS | −31 dBFS | 0 |

El Salamander no satura; para tocar en vivo se prevé una ganancia maestra de −3 dB como margen.

Render offline en la Pi: 22 s de audio en 14,1 s (carga incluida).

### Tiempo real en la Pi (silencio, 44,1 kHz, quantum 256 = 5,8 ms salvo indicación)

| Prueba | Configuración | B/Q máx / medio | Voces activas | xruns |
|--------|---------------|-----------------|---------------|-------|
| 16 voces sostenidas | cúbica, 64 voces | 0,13 / 0,06 | — | 4 |
| 32 voces sostenidas | cúbica, 64 voces | 0,38 / 0,16 | — | 8 |
| Arpegios densos con pedal | cúbica, 64 voces | 1,92 / 1,33 | (hasta 64) | 2391 |
| Arpegios densos con pedal | lineal, 64 voces | 1,66 / 0,90 | — | 1329 |
| Arpegios densos con pedal | cúbica, 32 voces | 1,02–1,11 / 0,72–0,76 | máx 32, media 28–29 | 611–709 |
| Arpegios densos con pedal | **lineal, 32 voces** | **0,92 / 0,62** | máx 32, media 27,5 | **69** |

- El cuello de botella es el hilo de audio (`data-loop.0`, SCHED tiempo real prioridad 20 vía rtkit): 74–86 % de CPU. La carga desde disco de sfizz usa ~10 % en hilos normales.
- Cada nota repetida bajo el pedal crea una voz nueva, y cada tecla soltada dispara muestras de *release* (martillo y resonancias): con pedal, las voces suben enseguida hasta el límite.
- `sample_quality=1` (interpolación lineal) se aplica con un SFZ envoltorio (`salamander-pi-sq1.sfz`, junto al original, que no se modifica).
  **Sustituido en la fase 07**: la opción `--sample_quality 1` de `sfizz_jack` (parche 0002) aplica lo mismo a todos los instrumentos, porque un envoltorio no sirve para los que declaran su propio `<global>`. El motor carga ahora el SFZ original; el envoltorio sigue en disco, sin uso.
- RAM: `sfizz_jack` hasta 348 MB (64 voces); quedan ≈ 727 MB disponibles.
- Una medición aislada (lineal/32 voces con B/Q 0,06) no se reprodujo al repetirla con grabación y recuento de voces: se descarta como anómala. Toda configuración se valida ahora **grabando** (para confirmar que hay audio) y con `--state`.

### Música real: Fontana (lineal, 32 voces)

| Configuración | B/Q máx / medio | Voces | xruns | Pico |
|---------------|-----------------|-------|-------|------|
| quantum 256, `ondemand` (silencio) | 0,65 / 0,42 | máx 32, media 24,6 | 79 en 245 s | −7,8 dBFS |
| quantum 512, `ondemand`, + Ambience (escucha) | 0,80 / 0,41 | — | 47 en 183 s (clics audibles) | −9,3 dBFS |
| **quantum 512, `performance` + núcleos 2–3, + Ambience (escucha completa)** | **0,57 / 0,37** | — | **1 en 251 s** | −8,2 dBFS |

Opinión del usuario: «se escucha bien, solo esos clics de repente» (antes del ajuste de CPU).

### Clics: causa y corrección

- Los xruns estaban **en el nodo del piano** (sfizz), no en la G1 (0 xruns): el hilo de audio no terminaba algunos bloques a tiempo aunque la carga media fuera moderada.
- Prueba autorizada por el usuario (temporal, revertida): gobernador `performance` + fijar `sfizz_jack` a los núcleos 2–3 (`taskset -c 2,3`, lejos de las interrupciones USB del núcleo 0). En los arpegios densos los xruns bajan de 13–517 (muy variable) a 5–8 (estable); en música real, de 47 a 1.
- `sfizz_jack` calcula todas las voces en **un solo hilo**: usa un núcleo de los cuatro. Mejora posible: dos instancias en paralelo (graves/agudos).

### Incidencia de hardware: bajo voltaje y desconexiones de la G1

- 02:37:50 primera desconexión USB de la G1, 1 s antes de `Undervoltage detected!` (2 avisos, 02:37–02:38). Coincidió con la escucha por la G1 (amplificador de auriculares) sumada a la carga de CPU/SD.
- La G1 quedó en un **bucle de reinicios**: unas 47 desconexiones entre 02:37 y 05:38, incluso sin audio, y con errores `cannot set freq 44100`.
- Solución aplicada: **apagado completo con la alimentación desenchufada**. Después, 0 desconexiones y `throttled=0x0` durante todas las pruebas y la escucha.
- Consumo USB declarado: WiFi RTL8188EUS 500 mA, teclado mecánico 100 mA, receptor Logitech 98 mA, G1 100 mA. Recomendado: fuente oficial de 5,1 V / 2,5 A y/o **hub USB alimentado** para la G1. Pendiente de confirmar con el usuario qué fuente usa.

### Lecciones de operación

- Al interrumpir, el entorno de control no mata el `ssh` local. El vigilante `-x` funciona ante un corte real de SSH, pero aquí no dispara. `tail -f /dev/null | ssh …` deja el comando colgado aunque la Pi termine, así que no se usa: tras cada interrupción se ejecuta `detener-audio.sh`.

## Pendientes

- [x] Decisión del usuario: ¿Salamander como instrumento final? → pidió varios instrumentos seleccionables (fase 07); el Salamander es el de referencia y el inicial por defecto.
- [ ] Aprobación para dejar **permanente** el gobernador `performance` (hoy solo temporal).
- [ ] Opcional: dos instancias de sfizz para usar dos núcleos.
- [ ] Ganancia maestra y reverb definitivas para tocar en vivo (latencia: quantum 256 o 512).
- [ ] Fuente de alimentación / hub alimentado (hardware, usuario).

## Checklist

- [x] Decisión del usuario registrada (requisito n.º 1 flexibilizado)
- [x] Salamander oficial descargado y verificado (SHA-256)
- [x] sfizz 1.2.3 compilado para ARM64 y amd64 con parche documentado
- [x] `escuchar-midi.sh` admite `PIANO_CMD`/`PIANO_LISTO` (pruebas de integración en verde)
- [x] Render offline: niveles sin saturación (PC y Pi)
- [x] Capacidad en tiempo real (voces, xruns, RAM, temperatura, por hilo)
- [x] Diagnóstico de clics → gobernador + afinidad de núcleos (1 xrun en 251 s)
- [x] Diagnóstico de desconexiones de la G1 → bajo voltaje; apagado completo
- [x] Escucha completa del usuario (Fontana) con la configuración ajustada
- [ ] Aprobación final del usuario
