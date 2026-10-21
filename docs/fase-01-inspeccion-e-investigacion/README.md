# Fase 01 — Inspección del sistema e investigación de instrumentos

## Objetivos

- Obtener acceso SSH no interactivo a la Raspberry Pi 3 (`usuario@ip-de-la-pi`).
- Inventariar hardware y software: CPU, RAM, kernel, tarjetas de sonido (Sound Blaster), dispositivos MIDI, servicios activos.
- Identificar pianos de modelado físico LV2/VST3 que funcionen en Linux ARM64 (aarch64), **verificándolo en la propia Raspberry**.
- Evaluar calidad sonora y consumo de CPU/RAM en una Pi 3 (4 × Cortex-A53, 1 GB RAM).
- Elegir el instrumento y presentarlo al usuario **antes de instalarlo**.

## Restricciones del requerimiento

| # | Restricción |
|---|-------------|
| 1 | Sin SoundFonts (SF2/SFZ) |
| 2 | Sin versiones demo ni software con interrupciones |
| 3 | Priorizar modelado físico |
| 4 | LV2 o VST3 compatible con Linux ARM64 |
| 5 | Preferir software libre y gratuito |
| 6 | Sin escritorio gráfico |
| 7 | CPU y RAM optimizados para Pi 3 |
| 8 | Salida de audio por la Sound Blaster |
| 9 | Entrada MIDI desde un teclado |
| 10 | Arranque autónomo (systemd) |

## Estado del acceso

- 2026-10-18: el host responde (kernel `6.12.109+rpt-rpi-v8`, aarch64). Al principio solo aceptaba contraseña.
- 2026-10-18: el primer intento de autorizar la clave desde PowerShell dejó una línea inválida (caracteres invisibles por la codificación de la tubería). Se añadió de nuevo pasando la clave como argumento. **Acceso por clave `id_ed25519` operativo.** `sudo` funciona sin contraseña para el usuario de la Pi.

## Inventario del sistema (2026-10-18)

| Elemento | Valor |
|----------|-------|
| Modelo | Raspberry Pi 3 Model B Rev 1.2 |
| SO | Raspberry Pi OS (Debian 12 bookworm), imagen 2024-11-19, arm64 |
| Kernel | `6.12.109+rpt-rpi-v8`, `CONFIG_PREEMPT=y` (no RT), `HZ=250` |
| CPU | 4 × Cortex-A53, 600–1200 MHz, *governor* `ondemand`, 56 °C, sin *throttling* (`0x0`) |
| RAM | 906 MiB útiles (GPU 76 MB), swap 512 MiB (`dphys-swapfile`), `swappiness=60` |
| Disco | microSD 58 GB, 15 % usado |
| Arranque | `multi-user.target` (sin escritorio). `lightdm` habilitado pero inactivo. Autologin de consola en `tty1` |
| Audio | **Sound BlasterX G1** (USB `041e:3249`, *full speed*): tarjeta ALSA 0 `G1`. **Solo admite S16_LE, 2 canales, 44 100 Hz** (reproducción y captura). Mezclador: `Speaker` 0–44 (al 48 %) |
| Otras salidas | `bcm2835 Headphones` (tarjeta 1), `vc4-hdmi` (tarjeta 2) |
| MIDI | **Ningún teclado MIDI conectado** (`amidi -l` vacío). Solo `Midi Through` y los clientes ALSA-seq de PipeWire |
| Servidor de audio | PipeWire 1.2.7 + WirePlumber 0.4.13 (servicios de usuario) + `filter-chain`. **El grafo trabaja a 48 000 Hz y la G1 solo admite 44 100 Hz: hay remuestreo continuo** |
| Tiempo real | `rtkit-daemon` activo. Existe el grupo `pipewire` (con límites rtprio 95), pero el usuario de la Pi no pertenece a él. `ulimit -r` = 0 |
| Jalv | 1.6.6, enlazado contra **libjack** (solo backend JACK). Hay versiones `jalv.gtk3` y `jalv.qt5`, que no se usarán |
| Plugins LV2 | **Ninguno instalado** (no existe `/usr/lib/lv2`). Por eso `lv2ls` no muestra nada |
| Compiladores | `build-essential`, g++ 12, `libx11-dev`. No están `cmake` ni las cabeceras de ALSA/JACK |

### Procesos ajenos detectados y acciones (autorizadas por el usuario)

- Un servicio propio del usuario, ajeno al piano, ocupaba ~238 MB de RAM. **Detenido y deshabilitado** a petición del usuario (los archivos se conservan; se puede volver a habilitar con `sudo systemctl enable --now`).
- Cadena `mc` → `xdg-open` → `www-browser` → `vlc` en `tty1`, detenida (estado `T`) desde hacía más de 2 h al reproducir `Front_Center.wav`. **Terminada** a petición del usuario (SIGTERM + SIGCONT).
- Resultado: RAM disponible de **488 → 699 MiB**.

## Investigación de candidatos (sin verificar todavía en la Pi)

| Candidato | Síntesis | Licencia | ARM64 / LV2 | Encaje con requisitos | Riesgo en Pi 3 |
|-----------|----------|----------|-------------|-----------------------|----------------|
| ~~Pianoteq 9~~ (Modartt) — **DESCARTADO** | Modelado físico completo | Propietaria, de pago | Build oficial aarch64 desde la 7.1; LV2/VST3 | Mejor calidad, pero la prueba silencia 8 notas y hay que reiniciarla cada 20 min. Descartado por el usuario (ver Decisiones) | Alto: los usuarios de Pi 3 reportan ~22 050 Hz de frecuencia interna y 24–48 voces de polifonía |
| **Piano** (FigBug / Socalabs) | Guía de ondas digital (fork de *qiano*): martillo, cuerda, modos longitudinales, tabla armónica | GPL-3.0 / AGPL | Código C++ con CMake; LV2 en Linux. Binario aarch64 no confirmado (hay que compilarlo) | Libre, modelado físico, LV2 | Desconocido: el modelo DWGS de *qiano* es costoso; hay que medirlo |
| Piano de Faust/STK | Síntesis conmutada (modelado físico simplificado) | Libre | Compilable a LV2 con `faust2lv2` | Libre, modelado físico, ligero | Bajo en CPU, pero calidad modesta |
| mda Piano (`mda-lv2`) | Híbrido con muestras internas pequeñas | Libre | Paquete Debian arm64 | **No** es modelado físico | Muy bajo; solo como respaldo |
| Piano Forte (Omnes Sonos) | Red neuronal + modelo físico | Libre | Solo Windows x64; depende de ONNX Runtime | No viable en ARM64 | — |

Fuentes:
- https://forum.modartt.com/viewtopic.php?id=7220 (build aarch64 de Pianoteq)
- https://forum.modartt.com/viewtopic.php?id=5195, https://forum.modartt.com/viewtopic.php?id=5572 (Pianoteq en Pi 3)
- https://www.modartt.com/try (limitaciones de la prueba 9.2.5)
- https://github.com/figbug/piano, https://socalabs.com/synths/piano/
- https://discourse.zynthian.org/t/free-and-open-source-digital-waveguide-piano-physical-model/8588

## Decisiones tomadas

- 2026-10-18 — **Pianoteq descartado por el usuario.** Motivo: la versión de prueba silencia notas y obliga a reiniciar cada 20 minutos, y el instrumento no puede detenerse ni dejar teclas mudas. No se evaluará ni se instalará ninguna edición de Pianoteq.
- La selección entre los candidatos libres se hará con mediciones reales en la Pi.

## Plan de verificación (cuando haya acceso SSH)

1. Inventario: `lscpu`, `free -h`, `aplay -l`, `amidi -l`, `aconnect -l`, `lsusb`, `systemctl get-default`, servicios activos, `lv2ls`, `LV2_PATH`.
2. Compilar FigBug/Piano en la Pi y medir el factor de tiempo real con su CLI (render offline de acordes densos con pedal).
3. Si resulta inviable, evaluar el piano de Faust/STK y comparar.
4. Presentar al usuario la recomendación con datos de CPU/RAM antes de instalar.

## Verificación del candidato principal (FigBug/Socalabs Piano)

- El código fuente (v1.0.14, commit `99bb41c7`) confirma **modelado físico real**: guías de onda (`dwgs.cpp`), martillo no lineal (`hammer.cpp`), modos longitudinales y tabla armónica con reverberación FDN. La descripción «Sampled piano plugin» del paquete Debian de upstream es un texto copiado por error.
- Motor: un solo hilo, bloque interno de 32 muestras (32 muestras de latencia añadida), sin límite explícito de polifonía (hasta 128 notas activas; las voces se liberan al decaer su energía).
- Upstream no publica binarios aarch64: se compila con `tools/build-piano/` (Docker ARM64 Debian 12, emulado con QEMU en el PC de control).
- Benchmark de upstream (x86, un hilo): 16 voces ≈ 29× tiempo real. Estimación para la Pi 3: 1,5–3×. **Pendiente medirlo en la Pi.**

## Checklist

- [x] Comprobar que el host responde por SSH
- [x] Acceso SSH por clave
- [x] Inventario de hardware y software
- [x] Identificar la Sound Blaster (BlasterX G1, 44,1 kHz / 16 bits)
- [x] Identificar dispositivos MIDI (ninguno conectado aún; hay que conectar el teclado para la prueba final)
- [x] Investigación documental de candidatos
- [x] Pianoteq descartado (decisión del usuario)
- [x] Verificación real en ARM64 (compilación: fase 02; medición en tiempo real: fase 03)
- [ ] Recomendación presentada y aprobada por el usuario (en curso en la fase 03)
