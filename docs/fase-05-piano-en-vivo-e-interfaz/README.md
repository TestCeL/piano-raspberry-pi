# Fase 05 — Piano en vivo e interfaz en consola (sin escritorio)

## Objetivos

- Poder **lanzar el piano a mano** y tocarlo con el **teclado de computador conectado a la Pi** mientras llega el teclado MIDI (elección del usuario frente a usar el teclado del PC por SSH: menor latencia, sin depender del WiFi).
- **Interfaz visible sin X** (sin `startx`): pantalla completa en la consola del monitor HDMI.
- Motor en vivo reutilizable para el arranque automático (fase siguiente).

## Componentes (`tools/pi/`, desplegados en `~/piano/tools/` de la Pi)

| Archivo | Función |
|---------|---------|
| `teclado_piano.py` | Lee el teclado por evdev (eventos reales de pulsar/soltar) y lo **captura en exclusiva** (`EVIOCGRAB`) para que lo tecleado no llegue a la consola. Envía MIDI por un puerto ALSA propio (`Teclado Piano:notas`) mediante `libasound` + ctypes, sin dependencias. Interfaz curses a pantalla completa (o una línea de estado). |
| `piano-en-vivo.sh` | Cadena en vivo: `sfizz_jack` (Salamander, interpolación lineal, 32 voces, fijado a los núcleos 2–3) → mda Ambience (−6 dB de margen) → G1. **Conecta solo** cualquier fuente MIDI nueva (teclado del PC ahora, teclado MIDI USB después). Instancia única (`flock`), marca de «listo», limpieza al salir. `-p`: gobernador `performance` durante la sesión, restaurado al salir. `-s`: silencio (pruebas). `-q`: quantum (por defecto 512 = 11,6 ms). |
| `piano-teclado.sh` | Lanza `piano-en-vivo.sh` como unidad de usuario `piano-vivo-cadena`, espera a «listo» y abre la interfaz. ESC cierra todo. |
| `piano` → `/usr/local/bin/piano` | Comando corto: `piano-teclado.sh -p`. |
| `detener-audio.sh` | Detiene todo el audio del proyecto (pruebas y piano en vivo); `--solo-pruebas` respeta el piano en vivo. Si un piano murió sin limpiar, restaura el gobernador desde su marca. |
| `lib-pw.sh` | Funciones comunes (arranque de clientes JACK, enlaces, resúmenes de pw-top), compartidas por `escuchar-midi.sh` y `piano-en-vivo.sh`. |
| `ejecutar-pruebas.sh` | **Validación completa** en la Pi (unidad + integración de flujos reales). Equivalente en este proyecto al `validate-web-flows.py` de las normas generales, que aquí no existe por no haber web. |

### Teclas

```
 W E   T Y U   O P          (sostenidos)
A S D F G H J K L Ñ {       do re mi fa sol la si do re mi fa
Z/X octava   C/V fuerza (16..127 en 8 pasos)   ESPACIO pedal   ESC salir
Flecha arriba/abajo   volumen de la G1 (pasos del 5 %, máx. 100 % = 0 dB; mantener repite)
Flecha derecha/izq.   reverb (mezcla 0..100 %, pasos del 5 %; mantener repite)
RETROCESO             silencio inmediato: apaga notas, suelta pedal, CC123 + CC120
```

Posiciones físicas (códigos evdev), válidas con cualquier distribución de teclado. Se usan flechas para volumen y reverb porque se rotulan igual en todas las distribuciones (`+`/`-` cambian de sitio en el teclado en español) y no chocan con las notas.

### Panel de controles (petición del usuario: «poner los controles en la interfaz, como el volumen y qué tecla usar»)

- **ESTADO** (izquierda): octava, fuerza, pedal, última nota, **volumen** (barra y %; «SILENCIADO» si lo está), **reverb** (barra y %), **sistema** (temperatura, CPU, aviso en rojo de **bajo voltaje** o CPU limitada, o «(hubo bajo voltaje)» si ocurrió desde el arranque).
- **CONTROLES** (derecha): todas las teclas y su función.
- Volumen: `wpctl` sobre la salida por defecto (la G1). WirePlumber aplica el cambio de forma asíncrona, así que la interfaz muestra el valor pedido y lo vuelve a leer cada 2 s (esto refleja también cambios hechos desde fuera). La prueba de integración lo detectó: una lectura inmediata devolvía aún el valor anterior.
- Reverb: `piano-en-vivo.sh` arranca jalv con la entrada estándar en un FIFO abierto en lectura-escritura (`$XDG_RUNTIME_DIR/piano-vivo-fx.ctl`), que nunca ve EOF. La interfaz escribe `mix = 0.40`. La ruta y el valor inicial se publican en `$XDG_RUNTIME_DIR/piano-vivo.estado`.
- Sistema: `/sys/class/thermal`, `/proc/stat` y `vcgencmd get_throttled`, cada 2 s.

### Interfaz en consola

- Teclado dibujado de 11 blancas y 7 negras (las pulsadas, en verde), mapa de las 88 teclas con la ventana actual y las notas sonando, octava, barra de fuerza, estado del pedal y última nota.
- Solo caracteres de **CP437**, presentes en la fuente por defecto de la consola Linux (`▔`, `—` y `Ú` se sustituyeron porque se verían como `?`). Hay una prueba que lo garantiza.
- Monitor HDMI conectado (1920×1080, consola de 240×67): el tamaño mínimo es 94×22. Si la ventana es menor, se muestra un aviso en lugar de dibujar mal.

## Decisiones tomadas

- MIDI por **secuenciador ALSA con ctypes**, en lugar de instalar `python3-rtmidi` o cargar el módulo `snd-virmidi`: sin software ni cambios del sistema.
- **Captura exclusiva del teclado**: imprescindible, porque `tty1` tiene una sesión con autologin y lo tecleado se ejecutaría allí.
- El gobernador `performance` **no es permanente**: solo con `piano -p` y durante la sesión (el usuario autorizó pruebas temporales; dejarlo permanente queda pendiente de su aprobación).
- Conexión MIDI automática por sondeo (1 s) del puente ALSA de PipeWire: sirve para el teclado del PC y para futuros teclados USB sin configurar nada.

## Pruebas (todas en verde: `bash ~/piano/tools/ejecutar-pruebas.sh` → «VALIDACIÓN COMPLETA: TODO PASA»)

| Suite | Cubre |
|-------|-------|
| `test_teclado_piano.py` (39) | Lógica de teclas (incluido soltar tras cambiar de octava, repetición automática, límites, pedal, ESC apaga todo, **flechas con repetición, pánico**), formato binario `snd_seq_event_t` (28 bytes) e `input_event` (24 bytes), lectura parcial evdev, geometría del teclado, mapa de 88 teclas, bucle con ESC/fin y **reparto volumen/reverb/MIDI**, **Controles** (volumen: pasos, límites, silenciado, sin wpctl, WirePlumber lento, fallo de `set-volume`; reverb por FIFO real y sin lector; estado; temperatura/CPU/bajo voltaje), **paneles** (contenido, avisos, anchos, CP437), interfaz curses real en pseudoterminal con los paneles |
| `test_teclado_alsa_integracion.sh` (7) | Cliente ALSA real, puerto visible en PipeWire, **secuencia MIDI exacta** recibida por `aseqdump`, sin notas duplicadas por repetición, cierre del cliente |
| `test_piano_en_vivo_integracion.sh` (30) | Arranque y «listo», gobernador y marca, enlaces sfizz→reverb, silencio verificado, afinidad 2–3, instancia única, **conexión MIDI automática + audio real en la salida** (pico −31,7 dBFS, sin recorte), **estado publicado, reverb aplicada por jalv (`mix = 0.450000`), volumen real de la G1 cambiado y restaurado**, parada ordenada (incluidos estado y FIFO), recuperación tras `kill -9` |
| Suites anteriores | generador de MIDIs, puertos, análisis WAV, lib-pw, reproducción de prueba |

### Incidencias resueltas durante la fase

- La prueba ALSA buscaba el puerto con `aconnect -o`; un puerto del que se **lee** aparece con `aconnect -i`.
- El `sleep` del bucle de vigilancia heredaba el descriptor del bloqueo: un rearranque inmediato lo encontraba tomado. Se cierra el descriptor en ese proceso hijo (`sleep 1 8>&-`).
- Volumen asíncrono de WirePlumber (ver panel de controles).
- `detener-audio.sh` ahora también detiene un `piano-en-vivo.sh` lanzado a mano (fuera de su unidad), con SIGTERM para que haga su propia limpieza. Lo puso en evidencia un huérfano creado por un comando de depuración (`cd … && script &` envía ambas órdenes a segundo plano).

## Uso

En la consola de la Pi (monitor + teclado), simplemente:

```
piano
```

- Comando instalado **solo en la Pi**, en `/usr/local/bin/piano` (fuente: `tools/pi/piano`). Esa ruta ya está en el PATH de todas las sesiones, también la de autologin de `tty1`, así que no hace falta `source`. El usuario pidió explícitamente no instalar nada en su PC.
- Incluye `-p` (CPU en `performance` solo durante la sesión, restaurada al salir). Admite opciones adicionales, p. ej. `piano -q 256` (menos latencia).
- Se eliminó el enlace provisional `~/.local/bin/piano` (y la carpeta vacía), para que no hubiera dos comandos `piano` distintos.

Detener todo el audio en cualquier momento: `~/piano/tools/detener-audio.sh` (por SSH: `ssh usuario@ip-de-la-pi ~/piano/tools/detener-audio.sh`).

## Pendientes

- [x] Prueba de uso del usuario en la consola real (monitor HDMI): funcionó; pidió aprovechar el espacio y elegir el teclado MIDI → **fase 06**.
- [ ] Teclado MIDI USB (cuando llegue): verificar la detección (ahora la hace el enrutador de la fase 06).
- [ ] Arranque automático con systemd (fase 11; la 07 y la 08 pasaron a ser las de instrumentos, la 09 la publicación y la 10 la configuración).
- [ ] ¿Gobernador `performance` permanente? (decisión del usuario).

## Checklist

- [x] Programa de teclado con captura exclusiva y MIDI ALSA sin dependencias
- [x] Interfaz curses a pantalla completa, compatible con la consola sin X
- [x] Motor en vivo con conexión MIDI automática, instancia única y limpieza
- [x] Comando `piano`
- [x] Funciones comunes en `lib-pw.sh` (sin duplicación) y regresión verificada
- [x] Validación completa en la Pi: 8 suites en verde
- [ ] Uso real por el usuario
