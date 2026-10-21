# Fase 11 — Arranque automático al encender

## Objetivo

Encender la Raspberry Pi y tocar, sin escribir nada: el piano se abre solo en la pantalla (consola HDMI) y se toca con el teclado conectado a la Pi. Orden de fases decidido por el usuario (fase 09): 09 publicación, 10 salida de audio, 11 arranque automático.

## Decisiones (2026-10-20)

Propuesta en 7 puntos. El usuario respondió «procede» y reinició esperando el arranque automático. Se tomó como aprobación de los puntos 1–4, 6 y 7. El 5 es funcionalidad nueva y queda a la espera de un sí explícito.

1. **La consola (`tty1`) inicia sesión sola** con el usuario del piano, y en esa consola se abre el piano; nunca en una sesión SSH. Se necesita una sesión porque el sonido (PipeWire) funciona dentro de la sesión de un usuario. Consecuencia: quien tenga el teclado de la Pi tiene una sesión abierta con `sudo` (aceptable en casa).
2. **Al encender, esperar hasta 20 s a la tarjeta preferida**, porque WirePlumber la publica unos segundos después de iniciar la sesión. Si no llega, el piano usa otra y lo avisa (fase 10).
3. **Al salir con ESC, volver a la consola** con indicaciones (`piano` para reabrirlo, `sudo poweroff` para apagar). El piano no se reabre solo.
4. **Si el piano no puede arrancar, se muestra el error y queda la consola,** sin reintentar en bucle; siempre se puede entrar por SSH.
5. Apagar la Pi desde el piano (F12 con confirmación): aprobado después, junto con la pantalla de inicio (ver más abajo).
6. **Instalador:** `instalar.sh --arranque-automatico` lo activa; `arranque-automatico.sh quitar` lo deshace. README en español e inglés.
7. **Pruebas** automáticas (sin reiniciar nada) y un reinicio real con el usuario.

## Implementación

- **`arranque-automatico.sh activar | quitar | estado`**, con el mismo patrón que `fuente-consola.sh`:
  - **systemd:** `/etc/systemd/system/getty@tty1.service.d/piano-autologin.conf` (con `sudo`) reemplaza la línea de `agetty` de Debian 12 por la forma de inicio automático de la wiki de Debian: `agetty -o '-p -f -- \\u' --noclear --autologin <usuario> - $TERM`. Se recarga systemd, pero la consola actual no se reinicia (cortaría la sesión que haya en ella): vale desde el próximo encendido.
  - **`~/.profile`:** un bloque marcado al final (`# >>> piano: arranque automático` … `# <<< …`) que solo actúa si `tty` es `/dev/tty1` y no hay `SSH_CONNECTION`. Llama a `piano-al-encender.sh`.
  - Primero se escribe el ajuste de systemd; si `sudo` falla, el perfil no se toca. Activar dos veces no duplica nada. `quitar` deja el perfil byte a byte como estaba y borra la carpeta del ajuste si quedó vacía.
- **`piano-al-encender.sh`:** ejecuta `piano --esperar-tarjeta 20` **una vez**: la espera a la tarjeta la hace `piano-teclado.sh`, para que se vea en la pantalla de inicio. Al terminar imprime «Piano cerrado» o el error, más las indicaciones. Termina siempre con 0 para que el inicio de sesión siga hasta la consola.
- **`salidas_audio.py esperar [--preferencias] [--segundos N]`:**
  - espera la preferida o, sin preferida, alguna USB; las de la Pi no bastan;
  - tolera un PipeWire que aún no responde;
  - devuelve 1 si no llega, y el piano sigue igual.
- **`instalar.sh --arranque-automatico`** (paso 9). Sin la opción, el final indica cómo activarlo.

## Pruebas

- **`test_arranque_automatico.sh`**, 26 comprobaciones (en `ejecutar-pruebas.sh` como «unidad: arranque automático»). `sudo`, `systemctl`, `tty` y `pw-dump` son falsos, y se usan carpetas temporales:
  - el ajuste de tty1 exacto, con `sudo` y la recarga de systemd;
  - el perfil conserva lo que tenía; activar dos veces da un solo bloque y no reescribe el ajuste;
  - **el bloque, ejecutado con `sh` como en el inicio de sesión:** abre el piano en `tty1`; no lo abre por SSH (aunque fuera `tty1`), en otra terminal ni sin terminal;
  - `quitar` deja el perfil idéntico y borra el ajuste;
  - casos límite: perfil sin salto de línea final, sin perfil, sin `sudo` (error sin tocar nada), sin el piano instalado, sin orden;
  - el lanzador: espera a que aparezca la tarjeta, abre el piano una vez, se rinde a los N s y abre igual, y si falla lo dice sin reintentar.
- **`test_salidas_audio.py`**, +6: `lista_para_tocar`, espera con reloj falso (aparece, PipeWire arrancando, se rinde a tiempo, sin preferida) y la línea de órdenes.
- **`test_instalar.sh`**, +4: sin la opción no se activa (y dice cómo); con ella sí; el bloque apunta al lanzador instalado; `--help`.
- En la Pi, antes de activar: **26/26**, instalador en verde, y la configuración real sin tocar. Un fallo en la primera pasada era de la propia prueba: `$(head -c …)` recorta el salto de línea final.

## Prueba real (2026-10-20)

- Activado en la Pi con `arranque-automatico.sh activar`, guardando antes una copia en `~/.profile.antes-fase11`. `systemd-analyze verify` sin errores.
- Un primer reinicio del usuario (21:07) todavía pidió contraseña: fue **antes** de activar (21:17).
- **Reinicio a las 21:19: «entró directo».** Del registro:

| Desde el encendido | Qué pasa |
|---|---|
| 12,1 s | la consola tty1 inicia sesión sola |
| 18,2 s | arrancan PipeWire y WirePlumber (con la sesión) |
| 23,5 s | salida elegida: la G1 (44,1 kHz), su preferida |
| 39,7 s | **piano listo** (Osiris, ~16 s de carga) y la G1 a su volumen recordado (85 %) |

Sin bajo voltaje (`throttled=0x0`).

## Pantalla de inicio estilo DOS y F12 para apagar (2026-10-20)

**Petición del usuario:** «Sería bonito tener una ventana de inicio mientras se carga el piano, así como los antiguos juegos de DOS». Se propusieron 4 puntos y, junto con el punto 5 (F12), el usuario respondió «¡excelente! procede»:
1. pantalla completa con fondo azul, marco doble, el título en letras de bloques, un teclado dibujado y el crédito del proyecto;
2. barra de progreso real por etapas;
3. también al abrir con `piano` a mano;
4. sin sonido de bienvenida.

**Pantalla de inicio (`pantalla_inicio.py`):**
- **Caracteres:** solo los que tiene la fuente de la consola (`glifos_consola.txt`): marcos `╔═╗║`, `█`, `░`, `■`, `→` y `·`. Faltan los medios bloques y `✓`: el teclado se dibuja con celdas de color y la barra con `█`/`░`, como en DOS.
- **Progreso:** lo publican `piano-teclado.sh` y `piano-en-vivo.sh` en `$XDG_RUNTIME_DIR/piano-vivo.progreso`, una línea por etapa: `segundos<TAB>etapa<TAB>detalle`. Las etapas son tarjeta, inicio, salida, sonido, reverb, enrutador y listo. Es un archivo y no el registro del sistema, para tener un contrato explícito y probable.
- **Estimación de la barra:**
  - el sonido, por lo que tardó la vez anterior (`tiempos_carga` de las preferencias; si no, el `carga_s` del catálogo);
  - preparar 1 s, reverb 3,5 s y enrutador 1 s, medidos al encender: 0,2, 3,5 y 0,8 s;
  - el tramo en curso avanza como la ventana de carga de F6/F7 (`progreso_carga`) y no llega al 100 % hasta «listo».
  - La espera de la tarjeta al encender no mueve la barra: no se sabe cuánto durará.
- **Tamaños:** completa en el monitor (120×33), compacta sin letras de bloques, y una sola línea en ventanas diminutas.
- **Teclado:** descarta lo tecleado mientras carga (`flushinp`), para que no llegue a la consola después.
- **Cierre:** termina sola con «listo» (tras mostrar el 100 % un instante) o con SIGTERM, que envía `piano-teclado.sh` si el piano falla, y entonces se muestra el error. Tiene un máximo de 150 s.

**`piano-teclado.sh`:**
- abre la pantalla solo en una terminal de verdad, con la entrada en `/dev/tty`, porque en segundo plano bash le daría `/dev/null`. `PIANO_SIN_PANTALLA_INICIO=1` la desactiva;
- nueva opción `--esperar-tarjeta S`: la espera a la tarjeta pasó del lanzador del encendido a este script, para que se vea en la pantalla de inicio. `piano-al-encender.sh` ahora llama a `piano --esperar-tarjeta 20`.

**F12 (punto 5):**
- **Interfaz:** abre «¿Apagar la Raspberry Pi?». Solo S apaga; N, ESC o F12 otra vez cancelan. Mientras pregunta no suena nada, la repetición de una tecla no confirma y las notas que ya sonaban se sueltan al levantar la tecla. Con un menú abierto no pregunta. Al confirmar, suelta todo y la interfaz termina con el código 10.
- **`piano-teclado.sh`:** primero cierra el piano, que suelta y suspende la tarjeta y restaura el gobernador, y después ejecuta `sudo -n systemctl poweroff`. Sin `sudo` muestra un error con la orden manual.
- **Ayuda:** en la fila «Salir» (`ESC        F12 apagar la Pi`), sin filas nuevas: la pantalla mínima sigue en 33 filas, justo el monitor.

**Pruebas:**
- **`test_pantalla_inicio.py`**, 14:
  - lectura del progreso, que tolera líneas a medio escribir;
  - cada etapa y su mensaje; la barra (cuentas exactas; nunca llega al 100 % sin «listo»); modo silencio y tarjeta que no llegó; nombres y estimados del catálogo y las preferencias;
  - la composición en 120×33 y en tamaños menores, todo dentro de la pantalla y con caracteres de la fuente; el título y el teclado;
  - **en una pseudoterminal real:** dibuja y termina sola con «listo», SIGTERM la cierra al instante, y respeta el tiempo máximo.
- **`test_piano_teclado.sh`**, 18, con systemd, motor, interfaz y `sudo` falsos: nunca apaga la Pi.
  - opciones pasadas al motor, y el progreso;
  - `--esperar-tarjeta`: espera y lo publica antes de «inicio», sin pasarlo al motor;
  - **F12: cierra el piano y después apaga**; sin `sudo`, error;
  - errores del motor y de la interfaz; reinicio si ya estaba en marcha;
  - **en una pseudoterminal (`script`, 120×33):** la pantalla se dibuja, deja paso a la interfaz y no queda viva; y la variable que la desactiva.
- **`test_teclado_piano.py`**, +8: F12 en el intérprete, en el bucle y en la pantalla real.
- **`test_teclado_alsa_integracion.sh`**, +1: F12 + S con el teclado simulado termina con el código 10.
- **`test_arranque_automatico.sh`:** el lanzador pasa `--esperar-tarjeta 20` (o `PIANO_ESPERA_TARJETA`).

**Dos fallos de las propias pruebas, corregidos:**
- **SIGTERM:** la prueba enviaba la señal tarde. Se quedaba bloqueada leyendo de la terminal, porque curses no escribe nada si la pantalla no cambia; ahora espera con `select` y la pantalla se cierra al instante.
- **`script`:** crea su terminal de 80×24 y salía la versión compacta; ahora usa `stty rows 33 cols 120`, como el monitor.

**Prueba del usuario en el monitor (2026-10-20, 21:47):** reinició la Pi (lo que cortó una validación en curso, que hay que repetir).
- **Encendido:** la pantalla de inicio se vio durante la carga. Progreso registrado: tarjeta «esperando» → G1 lista en 0,75 s → inicio → salida G1 a 44,1 kHz → sonido Osiris → listo.
- **F12:** N canceló, y S apagó la Pi de verdad («lo apagué, funcionó todo»).

## Pendientes

- [x] El usuario ve la pantalla de inicio en el monitor y prueba F12 (N cancela; S apaga de verdad): «funcionó perfecto»
- [x] Validación completa (2026-10-20, 21:55, con el piano cerrado con ESC). Resultado:
  - **24/24 suites**, 3 de ellas nuevas en esta fase;
  - 0 caídas de WirePlumber, sin restos, arranque automático activo;
  - 46,7 °C y sin bajo voltaje;
  - las herramientas de la Pi, idénticas a las del repositorio.

## Checklist

- [x] Propuesta y decisiones del usuario
- [x] `arranque-automatico.sh` (activar, quitar, estado) y `piano-al-encender.sh`
- [x] `salidas_audio.py esperar` (hasta 20 s a la tarjeta)
- [x] `instalar.sh --arranque-automatico`
- [x] Pruebas: 26 del arranque, +6 unitarias, +4 del instalador; en `ejecutar-pruebas.sh`
- [x] Activado en la Pi y probado con un reinicio real: piano listo a los 40 s del encendido
- [x] README en español e inglés
- [x] Pantalla de inicio estilo DOS (`pantalla_inicio.py`), con el progreso publicado por etapas
- [x] F12: apagar con confirmación (interfaz + `piano-teclado.sh`)
- [x] Pruebas: pantalla de inicio (14), lanzador (18), F12 (+9), arranque (actualizado)
- [x] Prueba del usuario en el monitor (pantalla de inicio y F12, también el apagado real)
- [x] Validación completa: 24/24
