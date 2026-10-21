# Fase 06 — Enrutador MIDI, interfaz ampliada y letra grande

## Petición del usuario (2026-10-19)

Al ver la interfaz en el monitor: «queda mucho espacio», ampliar el teclado, poder elegir el teclado MIDI desde la interfaz y cambiarlo en caliente, y otras mejoras. De la propuesta, el usuario eligió:

| Elegido | No elegido |
|---------|-----------|
| Letra más grande (Terminus 16×32, cambio de sistema autorizado) | Dos filas de teclas para tocar (~2,5 octavas) |
| Teclado dibujado de 4 octavas | |
| **Enrutador MIDI + panel de entradas** (recomendado) | Solo lista y conexión directa / dejar como está |
| Curva de fuerza, transposición, cortes y latencia, guardar preferencias | |

## Arquitectura

```
teclado del PC ─(teclado_piano.py)─> ALSA "Teclado Piano:notas" ─┐
teclado MIDI USB ────────────────────> ALSA "<dispositivo>"       ├─> enrutador_midi.py ─> ALSA "Piano Enrutador:salida"
otros (aplicaciones) ────────────────> ALSA "<cliente>"           ┘   (suscripciones           │ (PipeWire Midi-Bridge)
                                                                       en caliente)              v
interfaz ──órdenes (FIFO)──> enrutador ──estado (JSON)──> interfaz                    sfizz (Salamander) -> reverb -> G1
                                       └─ reverb: FIFO de jalv · latencia: pw-metadata · cortes: pw-top
```

- **`alsa_seq.py`** (nuevo): acceso común al secuenciador ALSA con ctypes (eventos, puertos de entrada/salida, enumeración, suscripciones, lectura no bloqueante). Lo usan la interfaz y el enrutador.
- **`enrutador_midi.py`** (nuevo, unidad `piano-vivo-midi`, núcleos 0–1): única entrada del sintetizador.
  - Detecta fuentes cada segundo (excluye System, Midi Through, PipeWire y a sí mismo). Identifica cada fuente por «cliente:puerto», un nombre estable al reconectar.
  - Activa las fuentes según las preferencias: el teclado del PC siempre; los dispositivos nuevos según «conectar solas» (la decisión se recuerda).
  - Transposición ±12 sin notas colgadas: el note off apaga la nota que realmente sonó, aunque la transposición cambie entretanto. Recuento de notas por si dos teclados tocan la misma nota.
  - Curva de fuerza: suave (γ 0,6), normal o dura (γ 1,6), solo para teclados MIDI (el del PC ya elige su fuerza).
  - Al desenchufar o desactivar una fuente, suelta sus notas. Pánico: note off de todo + CC64/123/120 en los canales usados.
  - Órdenes por FIFO: `transponer ±1|=N`, `curva siguiente|nombre`, `latencia siguiente|N`, `reverb ±1|x`, `fuente on|off|alternar <id>`, `auto [on|off]`, `panico`.
  - Estado JSON (cada cambio, máx. 20/s): fuentes, notas sonando, pedal, última nota y su fuente, ajustes y **cortes del piano** (lee `pw-top -b`; si el nodo se reinicia, conserva la cuenta).
  - **Preferencias** en `~/.config/piano/preferencias.json` (validadas al cargar; valores inválidos → por defecto): transposición, curva, latencia, reverb, conectar solas, fuentes elegidas.
  - `--sin-sistema` (pruebas): no aplica la latencia al PipeWire real.
- **`piano-en-vivo.sh`**: latencia y reverb iniciales desde las preferencias (`-q` manda si se da); arranca el enrutador y enlaza su salida a sfizz (ya no conecta las fuentes directamente). Variable `PIANO_PREFERENCIAS` para que las pruebas no toquen las reales.
- **`lib-pw.sh`**: los clientes se lanzan con `pw-jack` **sin `-s/-p`**. Esas opciones exportan `PIPEWIRE_QUANTUM` y fijaban el bloque del cliente, lo que impedía cambiar la latencia en caliente. Verificado: con sfizz en marcha, 512 → 256 → 1024 → 128 → 512 sin cortes ni caídas (sfizz atiende `jack_set_buffer_size_callback`).

## Interfaz (`teclado_piano.py`, reescrita)

- **Teclado de 4 octavas** (29 blancas + 20 negras). Arranca una octava por debajo de la zona del PC y sigue a la octava y a la transposición. Las letras del PC aparecen sobre las notas que realmente suenan. **Las notas de todas las entradas** (también el teclado MIDI) se iluminan en verde. Ancho de tecla adaptable (4 a 8 columnas; con 4 se abrevian los nombres: «So3»).
- Mapa de las 88 teclas: `═` para la zona dibujada (`▀` no existe en Terminus) y `█` para lo que suena.
- Tres columnas:
  - **ESTADO**: octava, fuerza, pedal (de cualquier entrada), última nota con su fuente, volumen, reverb, sistema (temperatura, CPU, bajo voltaje).
  - **SONIDO**: transposición, curva, latencia (ms), cortes (resaltados si el último fue hace < 10 s). Debajo, **ENTRADAS MIDI**: lista con `[x]`/`[ ]`, PC/MIDI, «desconect.», selección resaltada, y «Nuevas: se conectan solas / no se conectan».
  - **CONTROLES**: todas las teclas.
- Teclas nuevas: **F1/F2** transposición, **F3** curva, **F4** latencia, **F5** conectar solas sí/no, **TAB** elegir entrada, **ENTER** activar/desactivar, **RETROCESO** pánico local + del enrutador. Las flechas de reverb pasan por el enrutador, que guarda la preferencia; sin enrutador, la reverb va directa a jalv.
- Se adapta si cambia el tamaño del terminal con el programa abierto (cambio de fuente, ventana SSH): sin leer teclas de curses no llega `KEY_RESIZE`, así que se compara con el tamaño real y se llama a `resizeterm`.
- Interfaz y enrutador fijados a los **núcleos 0–1** (`taskset`): no compiten con sfizz (2–3).
- Tamaño mínimo 118×30, que cabe en 120×33 (monitor 1080p con Terminus 16×32).

## Letra grande (`fuente-consola.sh`)

- `aplicar`: copia `/etc/default/console-setup` en `.antes-piano` (una vez) y fija `CODESET="Uni2" FONTFACE="Terminus" FONTSIZE="16x32"` + `setupcon`. Consola: **240×67 → 120×33**. Persiste al reiniciar (`console-setup.service` habilitado).
- `revertir`: restaura la copia y carga **Uni2-VGA16** (equivalente a la fuente del kernel) en tty1–6, porque `FONTFACE=""` no cambia la fuente cargada. Verificado: 120×33 ↔ 240×67, dos ciclos.
- Glifos comprobados en `Uni2-Terminus32x16` (512): `█ ░ │ ─ · ° ═ Ñ á í ó ú…`.

## Incidencias

- **Mis pruebas de integración detuvieron el piano que el usuario tenía abierto** (`detener-audio.sh` al inicio). La interfaz quedó huérfana, capturando el teclado. Se cerró con SIGINT (salida ordenada que restaura la consola) y `ejecutar-pruebas.sh` ahora **se niega a ejecutarse si el piano está en uso** (salvo `FORZAR=1`).
- La prueba del enrutador aplicó `latencia 256` al PipeWire real: se restauró y se añadió `--sin-sistema`.
- Condición de carrera en la prueba: `pw-metadata | grep -q` con `pipefail` fallaba por SIGPIPE; se lee primero a una variable.

## Pruebas (`bash ~/piano/tools/ejecutar-pruebas.sh` → 10 suites en verde)

| Suite | Cubre |
|-------|-------|
| `test_enrutador_midi.py` (23) | curva (monótona, límites), preferencias (corruptas, tipos, rangos, ida y vuelta), filtro de fuentes, conexión en caliente y recuerdo, desconexión con notas pulsadas, reconexión con otro nº de cliente, transposición con notas pulsadas, vel 0, re-pulsación, rango, misma nota desde dos fuentes, pedal, pánico multi-canal, todas las órdenes, estado JSON, contador de cortes con reinicio de nodo |
| `test_enrutador_integracion.py` (2) | ALSA real: transposición y curva en la salida (`aseqdump`), teclado nuevo conectado solo, fuente desactivada que deja de sonar (y suelta su nota), pedal, pánico, preferencias guardadas y restauradas al rearrancar, `--pref`, cierre limpio |
| `test_teclado_piano.py` (46) | además de lo anterior: F1–F5/TAB/ENTER, pánico al enrutador, órdenes por FIFO real, selección circular y ajustada al desaparecer fuentes, reverb por enrutador o jalv, geometría de 4 octavas (negras sobre fronteras, nombres según ancho, etiquetas que siguen a la transposición, límites Do0–Do8), paneles (contenido, avisos, anchos ≤ 38, CP437), 1080p Terminus 120×33, pantalla grande, **redimensionado en caliente** |
| `test_piano_en_vivo_integracion.sh` (38) | enrutador activo y enlazado a sfizz, estado publicado, teclado conectado por el enrutador, audio real, volumen, reverb enrutador→jalv, transposición, **latencia cambiada en caliente en PipeWire**, preferencias guardadas y **restauradas al rearrancar**, limpieza de estado/FIFOs y de la latencia, instancia única, `kill -9` |

## Pendientes

- [ ] Prueba del usuario en el monitor con la letra grande.
- [ ] Teclado MIDI real (cuando llegue): verificar su detección, curva y pedal.
- [ ] Arranque automático con systemd (fase 11; la 07 y la 08 pasaron a ser las de instrumentos, la 09 la publicación y la 10 la configuración).

## Checklist

- [x] Módulo común `alsa_seq.py` y refactorización del teclado (pruebas de regresión en verde)
- [x] Enrutador: lógica pura + E/S dirigida por eventos, preferencias, cortes, `--sin-sistema`
- [x] Motor con el enrutador; latencia en caliente (sin `pw-jack -s/-p`)
- [x] Interfaz: 4 octavas, ESTADO/SONIDO/ENTRADAS/CONTROLES, teclas nuevas, redimensionado
- [x] Letra grande Terminus 16×32 aplicada y reversión verificada
- [x] Validación completa en la Pi (10 suites) sin alterar el estado del sistema ni las preferencias reales
- [ ] Uso real por el usuario
