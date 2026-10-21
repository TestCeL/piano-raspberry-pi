# Fase 07 — Instrumentos seleccionables en caliente

## Petición del usuario (2026-10-19)

> «¿Hay otros sonidos que podamos seleccionar? … ¿es posible que me hagas una selección y los dejes disponibles para poder cambiar entre ellos?»

Respuesta previa: el Salamander no se modificó (solo un envoltorio de cuatro líneas que fija la interpolación lineal). De la propuesta, el usuario eligió **todo**:

| Acústicos | Eléctricos |
|-----------|-----------|
| Headroom (Yamaha C3), Maestro (Yamaha CF-3), Splendid (Steinway), pianos verticales (Upright KW + Osiris) | Rhodes Mark I (jRhodes3d), Wurlitzer EP200 + Yamaha CP80 + Hohner Pianet T |

Con el Salamander son **10 sonidos**. Se cambian con **F6 / F7** sin reiniciar la cadena.

## Objetivos

1. Descargar y verificar los instrumentos en la Pi, y comprobar que sfizz los reproduce en ARM64.
2. Igualar su volumen, para que cambiar de sonido no dé saltos ni sature.
3. Comprobar que son **tocables en tiempo real** en la Pi 3 (carga, cortes, RAM).
4. Cambio en caliente desde la interfaz, recordado para el próximo arranque.

## Instrumentos (catálogo `tools/pi/instrumentos.json`)

| F6/F7 | id | Nombre | SFZ (en `~/piano/instrumentos/`) | Ganancia | Controles iniciales |
|---|---|---|---|---|---|
| 1 | salamander | Salamander (Yamaha C5) | `SalamanderGrandPianoV3_44.1khz16bit/SalamanderGrandPianoV3.sfz` | 0 dB (referencia) | — |
| 2 | headroom | Headroom (Yamaha C3) | `headroom/Headroom Piano (NoFX).sfz` | +9,2 dB | CC77 = 0 (sin micrófono Decca) |
| 3 | maestro | Maestro (Yamaha CF-3) | `maestro/Maestro Concert Grand.sfz` | +3,2 dB | — |
| 4 | splendid | Splendid (Steinway) | `splendid/Splendid Grand Piano.sfz` | −2,5 dB | — |
| 5 | upright | Kawai vertical (Upright KW) | `upright/UprightPianoKW-SFZ+FLAC-20220221/UprightPianoKW-20220221.sfz` | −1,8 dB | — |
| 6 | osiris | Osiris (vertical) | `osiris/Programs/01-natural.sfz` | −4,0 dB | CC101 = CC102 = 0 (solo micrófono A) |
| 7 | rhodes | Rhodes Mark I (jRhodes3d) | `rhodes/jRhodes3d-st.sfz` | −10,2 dB | — |
| 8 | wurlitzer | Wurlitzer EP200 | `epianos/Wurlitzer EP200/Wurlitzer EP200.sfz` | −1,5 dB | — |
| 9 | cp80 | Yamaha CP80 | `epianos/CP80/CP80.sfz` | −4,3 dB | — |
| 10 | pianet | Hohner Pianet T | `epianos/Pianet T/Pianet T.sfz` | −4,4 dB | — |

- Variantes **NoFX** (sin efectos internos: la reverb es la mda Ambience de la cadena).
- **Micrófonos**: Headroom y Osiris graban varios micrófonos por nota (2 y 3 voces por nota). Sus SFZ desactivan del todo una capa cuando su control vale 0 (`locc77=1`, `locc101/102=1`). Así cada nota gasta una sola voz, como el Salamander. El README de Headroom lo documenta («reduce polyphony by half»).
- Rhodes: la línea 1 de su SFZ (`A0 bankname: jRhodes3d`) produce un aviso de sintaxis que sfizz ignora (carga permisiva); su «medio pedal» usa opcodes que sfizz no admite en `<control>`, así que el pedal funciona como un pedal normal.
- Splendid y Osiris redirigen el pedal (`sustain_cc=90`) para el medio pedal con `ampeg_releasecc64`, que sfizz sí admite. Se verificó que sostienen con el CC64 normal (tabla de mediciones).

### Créditos y licencias

`python3 ~/piano/tools/catalogo_instrumentos.py creditos` imprime este listado desde el catálogo.

| Instrumento | Autor | Licencia |
|---|---|---|
| Salamander | Alexander Holm | CC BY 3.0 |
| Headroom | Bengt Nilsson (SFZ: kinwie) | CC BY 4.0 |
| Maestro | Mats Helgesson (SFZ: kinwie) | Libre, con permiso del autor |
| Splendid | Akai (SFZ: kinwie; resonancia y medio pedal: P. Eastman) | Dominio público |
| Upright KW | FreePats (grabación: Gonzalo y Roberto) | CC0 |
| Osiris | Karoryfer Samples | CC0 |
| Rhodes jRhodes3d | Jeff Learman | **Muestras CC BY-NC 4.0 (solo uso no comercial)**; SFZ CC0 |
| Wurlitzer, CP80, Pianet | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 |

## Descarga y verificación

- `tools/pi/descargar-instrumentos.sh` (en la Pi): tarballs de los repositorios oficiales de `github.com/sfzinstruments`. Tamaño y SHA-256 quedan en `~/piano/instrumentos/MANIFIESTO-descargas.txt`. Total ≈ 1,1 GB extraído (más 1,4 GB de tarballs en `~/piano/descargas`); quedan 43 GB libres.
- `tools/instrumentos/preparar-upright-kw.sh` (en el PC): el Upright KW solo se distribuye en `.7z`, y la Pi no tiene 7-Zip; **no se instaló** software para esto. En un contenedor Docker se descarga, se verifica el SHA-256 publicado (`3a66da3b…e703`) y se extrae; luego se copia a la Pi por SSH (tar). Se comparan las sumas SHA-256 de los 70 archivos en ambos lados. El orden se fija con `LC_ALL=C`: la primera comparación falló porque la Pi y el contenedor ordenaban distinto, aunque el contenido era idéntico.

## Cambios en sfizz (parche 0002, `tools/build-sfizz/patches/`)

Un SFZ envoltorio (como el del Salamander) no sirve para los demás instrumentos, porque declaran su propio `<global>`/`<master>`. Lo necesario existe en la API pública de sfizz, y el cliente JACK lo expone con un parche pequeño:

| Añadido | Uso |
|---|---|
| `--sample_quality N` | Interpolación lineal (1) para todos: es la que evitó los cortes en la Pi 3 (fase 04). Sustituye al envoltorio. |
| `set_volume <dB>` (entrada estándar) | Ganancia de cada instrumento. Se verificó que **se conserva al cargar otro instrumento** (no se reinicia en `load_instrument`). |
| `set_cc <n> <valor>` | Controles iniciales (micrófonos). **Cada carga restablece los `set_ccN` del SFZ**, así que se reenvían tras cada carga. |
| Salida sin esperar al hilo de órdenes | Con la entrada en un FIFO (necesario para recibir órdenes), sfizz esperaba para siempre a su hilo de órdenes al terminar. Ahora cierra JACK y sale (`std::_Exit`). Ver «Incidencia en la prueba del usuario». |

Comprobado en el código de sfizz 1.2.3: `load_instrument` toma el bloqueo del proceso de audio, así que durante la carga la salida es silencio y no se leen los eventos MIDI. El volumen por defecto es 0 dB, por lo que el Salamander con ganancia 0 suena igual que antes. `sfizz_render` no cambia (mismo SHA-256), así que la compilación amd64 del PC (solo render) no se rehízo y conserva solo el parche 0001.

Despliegue: `~/piano/bin/sfizz_jack` (SHA-256 `4e420525…7749`, con la salida corregida; `SHA256SUMS` verificado en la Pi). La versión anterior se conserva como `sfizz_jack.sin-parche-0002`.

## Igualación de nivel y pedal (`tools/pi/medir_instrumentos.py`, render en la Pi)

Render offline en la Pi (ARM64, `sfizz_render` float 32, interpolación lineal, 32 voces), con los controles iniciales de cada instrumento añadidos al principio del MIDI.
- **Nivel**: pieza `02-acordes-pedal`; la ganancia iguala el RMS al del Salamander.
- **Pedal**: pieza nueva `04-prueba-pedal`, el mismo acorde sin y con pedal. Se compara la cola ya soltada.

| id | RMS | Pico | Ganancia | Pico con ganancia | Sostiene con el pedal | Render (22 s de audio) |
|---|---|---|---|---|---|---|
| salamander | −31,3 | −9,8 | 0 | −9,8 | sí (+47 dB) | 11,2 s |
| headroom | −40,5 | −18,9 | +9,2 | −9,7 | sí | 5,5 s |
| maestro | −34,5 | −13,9 | +3,2 | −10,7 | sí | 9,9 s |
| splendid | −28,8 | −7,2 | −2,5 | −9,7 | sí | 7,6 s |
| upright | −29,5 | −7,6 | −1,8 | −9,4 | sí | 3,6 s |
| osiris | −27,4 | −7,3 | −4,0 | −11,3 | sí | 18,0 s |
| rhodes | −21,1 | −0,9 | −10,2 | −11,1 | sí | 6,5 s |
| wurlitzer | −29,8 | −12,2 | −1,5 | −13,7 | sí | 2,0 s |
| cp80 | −27,0 | −11,7 | −4,3 | −16,0 | sí | 2,6 s |
| pianet | −26,9 | −9,4 | −4,4 | −13,8 | sí | 2,8 s |

(dBFS. «sí» sin cifra: la cola sin pedal es silencio absoluto.) Con las ganancias, **ningún instrumento supera el pico del Salamander** (−9,4 dBFS como máximo frente a −9,8): cambiar de sonido no acerca la señal a la saturación.

## Tiempo real en la Pi

Condiciones del piano en vivo: quantum 512 (11,6 ms), sfizz en los núcleos 2–3, interpolación lineal, 32 voces y gobernador `performance` solo durante la medición. Todo en **silencio**: la salida va a un grabador, nunca a la G1. Pieza `03-arpegios-densos`: arpegios de 4 octavas con pedal, que **saturan las 32 voces**; es el peor caso, no una interpretación normal. Con esta prueba el Salamander, que el usuario ya toca, da 16 cortes en 30 s, frente a 1 en 251 s con música real (fase 04).

| id | B/Q máx | B/Q medio | Cortes | RAM de sfizz | Pico grabado* |
|---|---|---|---|---|---|
| salamander | 0,89 | 0,55 | 16 | 414 MB | −14,1 |
| headroom | 0,32 | 0,15 | 0 | 230 MB | −22,5 |
| maestro | 0,84 | 0,58 | 15 | 328 MB | −15,7 |
| splendid | 0,53 | 0,32 | 0 | 198 MB | −10,6 |
| upright | 0,31 | 0,15 | 0 | 76 MB | −10,2 |
| osiris | 0,55 | 0,31 | 2 | 454 MB | −12,7 |
| rhodes | 0,44 | 0,22 | 0 | 208 MB | −4,9 |
| wurlitzer | 0,19 | 0,09 | 0 | 30 MB | −13,3 |
| cp80 | 0,19 | 0,10 | 0 | 51 MB | −11,5 |
| pianet | 0,61 | 0,43 | 1 | 72 MB | −11,4 |

\* dBFS, sin la ganancia del catálogo: esta medición lanza sfizz directamente, sin el enrutador. Todas las pasadas tienen sonido verificado.

**Conclusión: los 10 son tocables en la Pi 3.** Ninguno es más exigente que el Salamander; el Maestro es el que más se le acerca. La memoria máxima (Osiris, 454 MB) cabe en el 1 GB.

**Cambio de instrumento en la cadena real** (silencio, sin notas, ciclo osiris → maestro → salamander ×2 → headroom → rhodes → salamander):

| Cambio a | Tiempo (incluye los 0,6 s de espera) |
|---|---|
| Osiris | 7,7–9,1 s |
| Maestro | 3,0–4,6 s |
| Salamander, Headroom | 1,7 s |
| Rhodes | 1,1 s |

- **Memoria**: tras la primera carga de Osiris, sfizz se queda en ≈ 204 MB (el montón ya reservado se reutiliza) y **no crece** en los cambios siguientes. Quedan ≈ 540 MB disponibles.
- Durante el cambio hay silencio (sfizz no lee MIDI mientras carga) y la interfaz muestra «cargando: …».

### Incidencias de la medición

- **Primera ronda inválida**: la medición en tiempo real no grababa la salida. Una pasada (Splendid) dio B/Q 0,02, es decir, sfizz sin notas, y parecía una carga bajísima. Repetida a mano, grabando, Splendid suena (pico −10,7 dBFS) con B/Q 0,61. Corrección en `medir_instrumentos.py`:
  - la medición en tiempo real **graba**;
  - una pasada sin audio es un **error**, no un dato;
  - se repite una vez, se anota el número de intentos y se guarda la salida de la pasada fallida.
- La segunda ronda tuvo el mismo fallo en Headroom (otra posición de la secuencia). Ocho pasadas seguidas sin renders entre medias no lo reprodujeron. Es intermitente, del camino de prueba (`aplaymidi` → «Midi Through» → Midi-Bridge, que en silencio hace de reloj del grafo), y no del piano en vivo. El motor usa el enrutador, y sus pruebas de integración siempre han tenido audio. Headroom repetido: correcto, en 1 intento.
- **Falsa alarma de «piano en uso»**: la comprobación buscaba `teclado_piano.py --titulo` en cualquier proceso, y encontró el texto de mi propia orden SSH. Además, la interfaz nueva ya no pasaba `--titulo`, así que una interfaz real no se habría detectado. Corregido:
  - `piano-teclado.sh` vuelve a pasar `--titulo`;
  - `ejecutar-pruebas.sh` y `medir_instrumentos.py` usan un patrón anclado (`^python3 \S*teclado_piano\.py --titulo`).

  Verificado en la Pi: detecta una interfaz lanzada como lo hace `piano` y no una shell que la menciona.
- **Fallo de arranque de jalv**: en las dos validaciones completas, al arrancar la reverb, `jalv` no pudo abrir su cliente JACK («Failed to connect to audio system», y SEGV al salir). Ocurrió 0,3 s después de que sfizz cargara sin problemas, y siempre en el mismo punto, tras la suite nueva de sfizz.
  - Aislado no se reprodujo: la suite del piano en vivo sola pasa entera, y 3 secuencias «prueba de sfizz → arranque del motor» también arrancan. PipeWire no deja nada colgado.
  - Sea cual sea la causa interna (jalv/pipewire-jack), el piano no puede depender de ella. Corrección en `lib-pw.sh`: `iniciar_cliente` **reintenta hasta 3 veces** si un cliente muere **antes de publicar sus puertos**, con aviso visible y las líneas del registro del intento fallido. Una vez arrancado, no reintenta nada.
  - Pruebas simuladas en `test_lib_pw.sh`: 0, 1, 2 y 3 fallos.
  - También sirve al arranque automático (fase 11).
  - Tercera validación completa, ya con la corrección: el fallo de jalv volvió a ocurrir una vez (14:24:59) y el reintento lo resolvió. **Las 14 suites pasan.**

## Cambio en caliente

```
interfaz (F6/F7) ──"instrumento siguiente"──> enrutador ──load_instrument / set_voices / set_cc / set_volume──> FIFO de sfizz
                                                 ^                                                               │
                                                 └──── "Instrument loaded: …", "Volume set: …" ── journalctl -f ─┘
```

- **`catalogo_instrumentos.py`** (nuevo): carga y valida el catálogo:
  - ids únicos;
  - rutas relativas, sin `..` ni comillas;
  - ganancia entre −30 y +24 dB;
  - controles entre 0 y 127;
  - nombre de ≤ 28 caracteres, que cabe en el panel.

  Además: disponibilidad (solo los que tienen su SFZ en disco), siguiente/anterior circular, y las órdenes para sfizz (`set_volume` va la última y su confirmación marca el final). Su CLI `elegir` lo usa el motor.
- **Enrutador** (`GestorInstrumentos`, lógica pura):
  - **0,6 s de pausa** tras la última pulsación antes de cargar: se recorre la lista con F7 sin cargar cada sonido.
  - Estados: *elegido* → *cargando* → *listo*.
  - Antes de cargar suelta las notas que suenan. Si el pedal cambió durante la carga (sfizz no lee MIDI mientras carga), reenvía su estado. Si no cambió, no lo reenvía, para no disparar ruidos de pedal (Maestro).
  - Guarda la **preferencia** `instrumento` solo cuando sfizz confirma la carga.
  - Si la carga **falla**, vuelve a cargar el anterior y muestra el error. Si sfizz no contesta en 180 s, da error.
- **Motor** (`piano-en-vivo.sh`):
  - Elige el instrumento inicial: el de las preferencias, o el primero disponible si ya no existe.
  - Arranca sfizz con `--sample_quality 1` y la entrada estándar en un FIFO (`$XDG_RUNTIME_DIR/piano-vivo.ctl`).
  - Pasa al enrutador el FIFO, el catálogo y `journalctl --user -u piano-vivo -f --since @<ahora>`. Solo cuentan las líneas de esta sesión, y no se pierde ninguna aunque lleguen antes de que el lector esté listo.
  - Se sustituyen las variables `SFZ` y `VOCES` por `INSTRUMENTO` (id) y el catálogo.
- **Interfaz**:
  - **F6/F7**. El panel SONIDO muestra «Sonido: <nombre>» y debajo «3 de 10   F6/F7 cambiar», «> <elegido>», «cargando: <nombre>» o «ERROR: …» en rojo; el texto largo se parte en dos filas.
  - El **título** muestra el instrumento que suena (antes decía siempre «Salamander Grand Piano»).
  - Tamaño mínimo 118×31 (cabe en 120×33).

## Incidencia en la prueba del usuario (2026-10-19)

**El usuario probó los sonidos: «se escuchan casi perfecto».** Al salir con ESC, la consola quedó bloqueada unos 90 s («se quedó tomada la app»).

- **Causa**: sfizz ahora lee sus órdenes de un FIFO abierto en lectura-escritura, que nunca da fin de archivo. Al recibir SIGTERM cerraba JACK y luego **esperaba a su hilo de órdenes**, bloqueado leyendo ese FIFO. systemd lo mataba con SIGKILL a los 90 s. Mientras tanto, `piano-teclado.sh` esperaba a la parada y la consola no respondía. Además, el motor también agotó su tiempo y no llegó a restaurar el gobernador; lo restauró `detener-audio.sh` con su marca.
- **Por qué no lo detectaron las pruebas**: la parada ordenada de la prueba de integración esperaba sin límite de tiempo. Pasaba, pero tardaba 90 s; por eso las validaciones se habían alargado.
- **Corrección**: en el parche 0002, sfizz sale sin esperar a ese hilo. Pruebas de regresión nuevas:
  - `test_sfizz_jack_ordenes.sh` (7): parada con SIGTERM y entrada en FIFO en < 5 s, cierre ordenado y sin SIGKILL. **Con el binario anterior falla** (90,3 s, SIGKILL); con el nuevo tarda 0,3 s.
  - `test_piano_en_vivo_integracion.sh` (4): parada del motor en < 15 s.

### Otras observaciones del usuario

- **«Polifonía de 7 notas»**: el sintetizador toca 32 voces. El límite está en el **teclado del PC**: su descriptor HID dice que la interfaz principal (`event4`, la que lee el piano) informa como máximo **6 teclas a la vez** («boot keyboard»). Tiene una segunda interfaz (`event7`) con mapas de bits para todas las teclas (NKRO).
  - **Confirmado** con una escucha de solo lectura mientras el usuario pulsaba 8 teclas: la 7.ª (J) llegó por `event7`, que el piano no leía. No sonaba y, al no estar capturada, se escribía en la consola.
  - **Corrección** en `teclado_piano.py`: lee y captura **todas las interfaces del mismo teclado USB con teclas de letras** (`dispositivos_del_teclado`, criterio `tiene_letras`: A, Z y espacio). Así quedan fuera las interfaces multimedia y de sistema, y otros teclados. Una tecla notificada por dos interfaces no suena dos veces.
  - Verificado en la Pi: detecta `event4` + `event7`.
  - Pruebas: capacidades reales de las 4 interfaces, árbol sysfs simulado (otro teclado USB y uno no USB quedan fuera), 7 teclas repartidas entre dos interfaces suenan las 7.
  - El teclado MIDI no tiene este límite.
- **Un pequeño «clic» al inicio de la nota en algunos instrumentos** («muy sutil»): durante esa sesión hubo **0 cortes**, así que no es la CPU, sino algo del sonido. Pendiente de investigar: en qué instrumentos y con qué notas. Hipótesis principal: `note_polyphony=1` de los SFZ (todos salvo el Salamander) corta la voz anterior de la misma nota en pocos milisegundos al repetirla.

### Cortes al usar el pedal (sesión del usuario, 2026-10-19)

El usuario oyó «unos pequeños cortes, muy pocos, cuando apliqué el pedal», con el Salamander y la interfaz en el monitor.

- **Registro de PipeWire de esa sesión**: 53 líneas de xrun, en ráfagas (16:25:02–18 y 16:28:24–51). Casi todas son «graph xrun not-triggered» del **reloj del grafo (la G1)**: algún nodo llegó 3–5 ms tarde en un bloque de 11,6 ms, a veces sfizz («status:awake»). El contador de la interfaz solo miraba el nodo de sfizz, así que no los reflejaba todos.
- **Lo que no es**:
  - La carga de cálculo: por el camino real (motor + enrutador + teclado del PC simulado, 8 teclas + pedal ×5), el Salamander da 0 cortes y B/Q máximo 0,31 en silencio.
  - La G1 ni el USB: con la G1 como reloj pero silenciada en el sumidero, 0 cortes de sfizz.
- **Sospecha principal: el dibujo de la interfaz en la consola HDMI.** El núcleo del sistema dibuja la letra grande (16×32) sin aceleración en los núcleos de la interfaz (0–1). Ahí también corrían el proceso de PipeWire (el reloj del grafo) y la reverb (jalv), que no estaban fijados como sfizz. Ahí se atienden además las interrupciones USB.
- **Incidente durante la investigación**: para confirmarlo dibujé de forma continua en `/dev/tty1` con el piano en `performance`. La Pi dejó de responder por SSH y **se apagó por bajo voltaje** («Undervoltage detected!», 16:39:35); el usuario creyó que era calor y le puso un ventilador. Además, la G1 quedó silenciada tras el reinicio (WirePlumber guardó el silencio de la prueba) y se restauró a mano. Lecciones:
  - las pruebas de carga se hacen ahora con vigilancia (`con_vigilancia.sh`: aborta a 75 °C o con bajo voltaje);
  - no se estresa la consola;
  - la fuente de alimentación queda justa bajo carga máxima (pendiente del usuario).
- **Cambios**:
  - **El contador de cortes ve todo el grafo**: vigila sfizz, la reverb y la G1. En cada instantánea de pw-top suma el mayor incremento, porque un mismo corte se marca a la vez en el reloj y en sus seguidores.
  - **Cada corte queda en el registro del enrutador** con su contexto: nodos, instrumento, pedal, notas, B/Q, temperatura y energía (`vcgencmd`). Ejemplo: `CORTE +1 (total 3) | nodos: alsa_output…G1 | instrumento salamander | pedal sí | notas 8 | B/Q 0.31 | 52 °C | energía ok`. Sirve para encontrar la causa en sesiones reales: `journalctl --user -u piano-vivo-midi | grep CORTE`.
  - **Reverb (jalv) fijada a los núcleos 2–3** (como sfizz).
  - **Con `-p`** (lo usa el comando `piano`), PipeWire y todos sus hilos pasan a los núcleos 2–3 durante la sesión. Se restaura al salir y, tras una muerte brusca, lo restaura `detener-audio.sh` con una marca (solo si es el mismo proceso). `PIANO_FIJAR_PIPEWIRE=0` lo desactiva para comparar.
- **Verificación**: la prueba de integración comprueba los núcleos de PipeWire (todos los hilos) y de jalv durante la sesión, su restauración al parar y tras `kill -9`, y que el enrutador vigila la reverb. Temperatura máxima durante la prueba: 48 °C, sin limitación.
- **Resultado (sesión del usuario, 20:59–21:09, los 10 instrumentos, con pedal)**: «¡se escucha espectacular!».
  - El registro de PipeWire anotó **1 solo corte mientras tocaba** (21:05:19, Rhodes); los otros 2 fueron al arrancar, antes de que hubiera sonido. Antes había 53 líneas de xrun en 8 minutos, en ráfagas.
  - Temperatura de 62 °C con ventilador y sin bajo voltaje.
- **Fallo del contador encontrado en esa sesión**: «Cortes» marcaba 0 pese a ese corte. `pw-top` **no cuenta** los «graph xrun not-triggered»: el ERR de la G1 seguía en 0, y son justo los que se oyen. Corrección:
  - el enrutador lee el **registro de PipeWire** (`--registro-pipewire`, `journalctl --user -u pipewire -f`) y cuenta las líneas «graph xrun» del reloj de su cadena. Cada una vale 1 + las repeticiones que PipeWire omitió («N suppressed»);
  - otros relojes (Dummy-Driver, Midi-Bridge) no cuentan;
  - con esa fuente activa, el ERR de `pw-top` no se suma (no contar dos veces) y `pw-top` solo aporta la carga.

  Pruebas: unitarias con las líneas reales de la sesión, y de integración con el enrutador real y un registro simulado (estado = 9 cortes, 2 líneas `CORTE`, nada de otros relojes, lector terminado al salir).

### Pausa del piano y ventana «Cargando» durante el cambio de sonido (petición del usuario)

> «Cuando carga entre sonido y sonido, me gustaría que se bloquee el piano y espere que el siguiente termine de cargar; es muy fácil seguir tocando y forzar el colapso del proceso. Quizás una barra de progreso encima que diga cargando, como un modal.»

En el registro de esa sesión **no hubo fallos del proceso**. Lo que ocurría: durante `load_instrument`, sfizz no lee el MIDI, pero el enrutador seguía enviándole notas, que se perdían a medias.

- **Pausa**: mientras hay una carga en curso (hasta la confirmación `Volume set`), el enrutador **no envía notas, controles ni pitch bend** a sfizz, sea cual sea la entrada (teclado del PC o MIDI). Las notas tampoco aparecen como sonando en la interfaz. El pedal se sigue registrando y, si cambió, se reenvía al terminar. Las notas pulsadas antes del cambio se sueltan al empezar (como antes).
- **Ventana** centrada sobre el teclado dibujado (blanco sobre azul, caracteres CP437):
  - el texto «Cargando instrumento»;
  - el nombre;
  - una barra de 34 caracteres con el porcentaje;
  - «El piano está en pausa hasta que termine»;
  - «Después: …» si se eligió otro con F6/F7 durante la carga.

  Se cierra cuando sfizz confirma la carga.
- **Progreso**: sfizz no informa su avance, así que la barra es una **estimación por tiempo**. Es lineal hasta el 90 % del tiempo previsto; después se acerca al 99 % sin llegar, y el 100 % es la confirmación real.
  - El tiempo previsto sale de lo **aprendido** (preferencia `tiempos_carga`: media entre la medida anterior y la última) o, si no hay, del catálogo (`carga_s`, medido en la Pi con el disco en frío).
  - El enrutador publica `carga` (id, nombre, `inicio` en hora de reloj, `estimado_s`, `despues`) y anota en su registro `INSTRUMENTO <id> cargado en N s`.
- **Tiempos de carga medidos** (cadena real, silencio, dos vueltas; segundos):

  | Instrumento | 1.ª vuelta | 2.ª vuelta |
  |---|---|---|
  | Osiris | 8,8 | 8,1 |
  | Maestro | 4,9 | 1,8 |
  | Headroom | 2,1 | 1,0 |
  | Splendid | 1,6 | 0,9 |
  | Salamander | 0,9 | 0,8 |
  | Upright KW | 0,9 | 0,6 |
  | Rhodes | 0,4 | 0,5 |
  | Wurlitzer, CP80, Pianet | 0,3–0,4 | 0,3–0,4 |
- **Pruebas**:
  - en el enrutador: pausa de notas, controles y pedal (reenvío al terminar), datos de la ventana («Después»), aprendizaje y guardado de tiempos, sin ventana en los ajustes del arranque;
  - en las preferencias: validación de `tiempos_carga`. En el catálogo: validación de `carga_s`;
  - en la interfaz: progreso (no retrocede, < 99 %), contenido y anchos de la ventana en CP437, y dibujo real en una pseudoterminal 120×33;
  - integración con ALSA real (enrutador + sfizz simulado): **ninguna nota ni pedal pasa a la salida durante la carga**, el pedal se envía al terminar, se vuelve a tocar y el tiempo queda aprendido.

## Decisiones tomadas

- Un solo sintetizador con carga en caliente (`load_instrument`), en lugar de varias instancias: la Pi 3 tiene 1 GB. Durante la carga hay silencio, unos segundos según el instrumento.
- Variantes de **un micrófono** en Headroom y Osiris: la mitad o un tercio de voces, con el mismo realismo por nota que el Salamander.
- Igualación por **RMS** con la misma pieza y comprobación de **pico**. El volumen general sigue siendo el de la G1.
- Rhodes incluido con su licencia **no comercial** indicada (uso personal del usuario).

## Pruebas

| Suite | Cubre |
|---|---|
| `test_catalogo_instrumentos.py` (12) | catálogo real (los 10, orden, Salamander de referencia, controles, licencia NC), 19 casos de validación, disponibilidad, navegación circular, elección con alternativa, órdenes para sfizz, CLI (`elegir` con rutas con espacios, sin disponibles, catálogo roto, `lista`, `creditos`) |
| `test_enrutador_instrumentos.py` (18) | inicio (solo ajustes), cambio completo con espera y confirmación, líneas ajenas ignoradas, recorrido rápido (solo carga el último), anterior/por id/inválido, volver al actual sin cargar, elegir durante una carga, fallo con recuperación y error visible, `ERROR: Can't load`, sin respuesta, lista vacía; en el enrutador: notas soltadas, preferencia tras la confirmación, pedal reenviado solo si cambió, fallo, sin gestor; preferencia validada |
| `test_medir_instrumentos.py` (11) | RMS conjunto, ganancia (límites, silencio), pedal, lectura de `escuchar-midi.sh` (incluido el pico grabado), **medición en tiempo real sin audio = error** (debe grabar; una pasada sin audio se repite y se anota), flujo completo con render simulado (ganancias, catálogo de salida, pedal que no sostiene = fallo), errores de uso, no mide si el piano está en uso |
| `test_generar_midis_prueba.py` (+6 → 17) | `04-prueba-pedal` (acordes, ventanas, pedal), `anteponer_controles` (SMF válido, tiempos intactos, límites) |
| `test_analizar_wav.py` (+2 → 9) | medición por tramos (`--desde/--hasta`), tramos inválidos |
| `test_teclado_piano.py` (+9 → 55) | F6/F7 sin repetición, panel SONIDO en cada estado (nombre largo partido, solo el error en rojo, sin instrumento tras un fallo), `partir`, título, anchos y CP437, pantalla real 120×33 con el instrumento; **interfaces del teclado** (capacidades reales, sysfs simulado, 7 teclas por dos interfaces) |
| `test_sfizz_jack_ordenes.sh` (17) | sfizz_jack real con instrumento mínimo (seno): calidad 1, `set_volume` medido (−12 dB exactos) y **conservado tras cargar** otra ruta con espacios, `set_cc` que apaga una región, órdenes erróneas, carga fallida y recuperación (y los CC del SFZ restablecidos), `quit`, **parada con SIGTERM en < 5 s sin SIGKILL** |
| `test_lib_pw.sh` (+6) | reintento de arranque de un cliente con systemd y PipeWire simulados: sin fallos, 1 y 2 fallos (arranca), 3 fallos (error, sin más intentos), aviso y registro del intento fallido |
| `test_enrutador_midi.py` (+5 → 28) | cortes de todo el grafo sin contar dos veces el mismo, eventos para el registro, carga del nodo principal; **cortes del registro de PipeWire** (líneas reales, «suppressed», otros relojes, sin doble cuenta con pw-top); texto del registro con su contexto (energía, sin datos) |
| `test_enrutador_instrumentos.py` (+5 → 23), `test_catalogo_instrumentos.py` (12, +3 casos) | pausa durante la carga, progreso para la interfaz, aprendizaje de tiempos, `tiempos_carga` y `carga_s` validados |
| `test_enrutador_integracion.py` (+2 → 4) | enrutador real contando y anotando los cortes del reloj desde un registro de PipeWire |
| `test_piano_en_vivo_integracion.sh` (+22 → 60) | instrumento inicial con ajustes confirmados, calidad 1 y ganancia; cambio a Wurlitzer confirmado, SFZ con espacios y su ganancia; preferencia; **audio real tras el cambio**; instrumento roto → error y vuelta al anterior, preferencia intacta; dos F7 rápidos → una sola carga; FIFO de sfizz eliminado al parar; **parada en < 15 s**; **núcleos de PipeWire y de la reverb** (sesión, parada, `kill -9`); **al rearrancar vuelve el último instrumento** |

## Pendientes

- [x] Prueba del usuario: «se escuchan casi perfecto».
- [x] Consola bloqueada 90 s al salir → corregido (parche 0002, salida inmediata) con prueba de regresión.
- [ ] Clic sutil al inicio de nota: tras la corrección de los cortes, el usuario lo oyó «un poquitito, un par de veces». Próxima sesión: si coincide con una subida de «Cortes», el registro `CORTE` dará su contexto; si «Cortes» no sube, está en el sonido (hipótesis: `note_polyphony=1` corta la voz anterior al repetir nota) y se investigará con renders.
- [x] Cortes con el pedal: contador de todo el grafo, registro con contexto, PipeWire y reverb fijados a los núcleos 2–3.
- [x] Prueba del usuario con el pedal tras el cambio: «¡se escucha espectacular!»; 1 corte en 10 min (antes, ráfagas).
- [x] Contador «Cortes» corregido: cuenta los cortes del reloj desde el registro de PipeWire (`pw-top` no los veía).
- [x] Fuente de alimentación: el apagado por bajo voltaje fue con mi prueba de carga extrema; en uso normal, sin bajo voltaje. El ventilador es externo (no consume de la Pi). Si la interfaz muestra «BAJO VOLTAJE!», revisar la fuente o el cable.
- [x] Teclado del PC: las teclas a partir de la 7.ª llegaban por la segunda interfaz (`event7`) → ahora se leen y capturan todas las interfaces del teclado.
- [x] Confirmación del usuario: «las 8 simultáneas funcionan ahora».
- [ ] Teclado MIDI real (llega la próxima semana): detección, pedal y fuerza con cada instrumento.
- [ ] Arranque automático con systemd → **fase 11** (la 08 pasó a ser la de más sonidos y el menú; la 09, la publicación, y la 10, la configuración), aplazada por decisión del usuario («no necesito eso aún»). El reintento de arranque de clientes ya está en `lib-pw.sh`.

## Checklist

- [x] 10 instrumentos descargados y verificados (SHA-256; Upright KW verificado archivo a archivo)
- [x] Parche 0002 de sfizz_jack (calidad, volumen, controles), compilado ARM64, desplegado con copia de la versión anterior
- [x] Catálogo con ganancias medidas en la Pi y comprobación del pedal
- [x] Medición en tiempo real de cada instrumento en la Pi (con sonido verificado) y de la memoria en cambios sucesivos
- [x] Cambio en caliente (enrutador, motor, interfaz F6/F7) y preferencia
- [x] Validación completa en la Pi (`ejecutar-pruebas.sh`): **14 suites en verde**. Al terminar, la Pi queda limpia: sin unidades, gobernador `ondemand` y preferencias reales intactas.
- [x] Uso real por el usuario: los 10 instrumentos con pedal, «¡se escucha espectacular!»
