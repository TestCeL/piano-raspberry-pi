# Fase 10 — Elegir la tarjeta de sonido (salida de audio)

## Petición del usuario (2026-10-20)

> «¿Qué tal si desenchufo mi tarjeta [de sonido] actual y le conecto otra?» → propuesta en 8 puntos → «sí a todo»

Hasta ahora el piano solo funcionaba con la Sound BlasterX G1: su nombre estaba fijo (`SINK_PATRON`), y con otra tarjeta `piano` no arrancaba. El usuario conectó su audífono **Logitech G432**, que lleva su propia tarjeta USB.

## Tarjetas reales disponibles

| | Logitech G432 | Sound BlasterX G1 |
|---|---|---|
| Formato | S16_LE, estéreo | S16_LE, estéreo |
| Frecuencias | 8, 16, 24, 32, **44,1** y 48 kHz (`/proc/asound/card2/stream0`) | solo **44,1 kHz** |
| USB | Full speed (1.1), endpoint adaptativo | USB 2.0 |
| PipeWire (`node.name`) | `alsa_output.usb-Logitech_G432_Gaming_Headset_000000000000-00.analog-stereo` | `alsa_output.usb-Creative_Technology_Ltd_Sound_BlasterX_G1_00030790-00.analog-stereo` |

Salidas propias de la Pi: auriculares de 3,5 mm (`bcm2835 Headphones`, 8–192 kHz) y HDMI (`vc4-hdmi`, 32–48 kHz). PipeWire da las frecuencias como rango (`EnumFormat`); la lista exacta de una tarjeta USB está en `/proc/asound/cardN/stream0`.

## Decisiones del usuario (todas «sí», 2026-10-20)

1. **Menú F10 «Salida de audio»** con las tarjetas conectadas (USB y salidas de la Pi). Se elige como en F9 y la elección se guarda en las preferencias.
2. **Cambio en caliente**, sin cerrar el piano, con la ventana de pausa: se conecta la nueva antes de soltar la anterior.
3. **Volumen recordado por tarjeta**, y **40 % la primera vez** que se usa una (un audífono nunca hereda de golpe el 80 % de los parlantes).
4. **Si la tarjeta elegida no está al abrir**, se usa otra conectada (USB primero) y se avisa en pantalla, en vez de no arrancar.
5. **Desconectar la tarjeta mientras suena no rompe nada**: el ancla queda siempre en la reverb (el error de PipeWire 1.2.7 no puede tumbarla) y el piano avisa «salida desconectada». Se mide antes cuánta CPU cuesta el ancla.
6. **Las salidas de la Pi** (3,5 mm y HDMI) aparecen con una advertencia de calidad.
7. **Tarjetas sin 44,1 kHz**: el piano usa 48 kHz en esa sesión, automáticamente.
8. **Pruebas con las dos tarjetas reales** (G1 y G432) más las automáticas. Se avisa antes de cada sonido, sobre todo con el audífono puesto.

## Implementación

**`salidas_audio.py`** (nuevo).
- Detecta las salidas a partir de `pw-dump` (nodos `Audio/Sink`):
  - tipo: USB, Pi (3,5 mm), HDMI u otra;
  - nombre visible: «G432 Gaming Headset», «Auriculares de la Pi (3,5 mm)», «HDMI (por la pantalla)»;
  - frecuencias: el rango de PipeWire y, en USB, la lista exacta de `/proc/asound/cardN/stream0`;
  - avisos de calidad.
- Elige la preferida o, si falta, otra (USB primero) con aviso; la frecuencia es 44,1 kHz si la admite y, si no, 48 kHz.
- CLI `elegir` / `lista`. `PIANO_SOLO_SALIDAS` limita las candidatas (pruebas: nunca una tarjeta real).
- **`GestorSalida`**, lógica pura del cambio en caliente:
  - conectar antes de cortar: la anterior se suelta **solo tras confirmar** la nueva;
  - volumen recordado por tarjeta, con tope del 40 % la primera vez;
  - desconexión y reconexión;
  - una tarjeta que necesita 48 kHz no se cambia en caliente: queda elegida para la próxima vez y se avisa.

**Enrutador.**
- Preferencias `salida` y `volumen_salidas`, validadas.
- Orden `salida <node.name>`; pausa (no envía notas) mientras cambia; estado `salida` para la interfaz.
- Ejecuta los efectos:
  - enlaza y suelta con `pw-link`;
  - comprueba 0,4 s después: deja tiempo a PipeWire y la pausa se ve;
  - aplica y lee el volumen con `wpctl <id>`.
- Vigilancia cada segundo: si cambian los puertos, vuelve a leer las salidas.
- Guarda el volumen de la tarjeta activa cada 5 s y al cerrar.
- El vigilante de cortes cambia al nodo de la tarjeta nueva, y los cortes del cambio o de la desconexión no se cuentan.

**Interfaz.**
- F10 con el menú «SALIDA DE AUDIO» (tipo, «suena ahora», aviso de la marcada).
- Fila «Salida» en el panel SONIDO, con aviso o error en rojo.
- Ventanas «Cambiando la salida de audio» y «Salida de audio desconectada»; esta última no tapa el F10.
- El volumen va a la tarjeta del piano por su id (antes, a la «predeterminada» del sistema) y se relee al cambiar de tarjeta.
- La latencia se calcula con la frecuencia de la sesión. La ayuda incluye «Salida F10», y la pantalla mínima pasa a 33 filas (justo el monitor).

**Scripts.**
- `piano-en-vivo.sh`, `escuchar-midi.sh` e `instalar.sh` sin nombre fijo de tarjeta.
- **El ancla queda siempre en la reverb**, con sonido o en silencio. **CPU medida: 1,0 % de un núcleo** (0,25 % del total), frente a sfizz en reposo 2,9 % y la reverb 1,5 %.
- Las variables de prueba se pasan al enrutador con `--setenv`, porque `systemd-run` no hereda el entorno.

**Pruebas.**
- `test_salidas_audio.py`, **25 pruebas**:
  - detección con el `pw-dump` real de la Pi, más la G1 y una tarjeta solo de 48 kHz;
  - tasas exactas de `/proc`, elección y alternativas;
  - puertos (incluido un fallo encontrado: `monitor_FL` antes que `playback_FL`) y `pw-link -l`;
  - todo el ciclo del `GestorSalida`.
- `test_enrutador_midi.py`, 5 nuevas: preferencias, orden, pausa, estado y cambio de nodo vigilado.
- `test_teclado_piano.py`, 8 nuevas: menú, intérprete, fila, ventanas, filas del menú, volumen de la tarjeta activa, latencia a 48 kHz y alto.
- `test_instalar.sh`: tarjetas USB a la vista o aviso, con `pw-dump` falso.
- **`test_salidas_integracion.sh`, 22 comprobaciones con dos salidas virtuales de PipeWire** (silencio absoluto):
  - arranque sin la preferida;
  - enlaces y volumen de la primera vez;
  - cambio en caliente;
  - volumen recordado;
  - **desconexión sin caídas y reconexión automática con su volumen**;
  - cierre limpio sin SIGSEGV.
- **Todo pasó a la primera** en la Pi nueva. Dentro de la validación completa, en cambio, la prueba de integración falló dos veces seguidas en el «tope de la primera vez» (vio 0,33 en vez de 1,0). **Era la prueba, no el piano.**
  - **Causa:** WirePlumber recuerda el volumen de las salidas virtuales por su nombre (`~/.local/state/wireplumber/restore-stream`) y lo **reaplica cuando la salida se activa**, al enlazarla el piano. El 0,33 venía de la ejecución anterior, y fijar el 100 % al crearla no servía.
  - **El piano hizo lo correcto:** aplicó el tope a un 33 %, que ya estaba por debajo del 40 %, y lo recordó.
  - **Corrección:** la prueba deja las dos salidas al 100 % al terminar y espera a que WirePlumber lo guarde. Así cada ejecución empieza igual, y con nombres fijos el archivo de WirePlumber no crece (8 líneas). **Cuatro ejecuciones seguidas en verde.**
  - Además, la reconexión ahora **distingue** quién restaura el volumen: justo antes de desconectar se pone 0,70 (WirePlumber lo recuerda; el piano, que lo lee cada 5 s, no). Al reconectar queda en 0,55: **lo restauró el piano**.
  - Con las tarjetas reales, WirePlumber usa otro mecanismo (`default-routes`), y el piano aplica su volumen al menos ~1 s después de detectarlas: la reconexión probada lo confirma.

## Hallazgo: WirePlumber 0.4.13 cae al desenchufar una tarjeta recién liberada

La validación completa pasó (21/21), pero al terminar no había salida predeterminada («Translate ID error: '-1'»). **WirePlumber había caído con SIGSEGV 12 veces**, siempre unos 4 s después de terminar `test_salidas_integracion.sh`. systemd lo levanta solo, pero al volver recrea los nodos de las tarjetas (con otros ids).

**Aislamiento** (salidas virtuales, silencio con `/dev/zero`; reinicios de WirePlumber contados con `NRestarts`):

| Caso | Reinicios |
|---|---|
| 1–4: crear y borrar una salida (con cambio de volumen, dos seguidas, con el nombre de la prueba), sin nada enlazado | +0 cada uno |
| 5, 5b, 7: enlazada a algo que suena, se suelta y **se borra a los 2 s** | **+1 cada uno** |
| 6: se borra **mientras está enlazada** | +0 |
| 8: se suelta, **se espera a que esté suspendida** y se borra | +0 |
| 9: como 5, con `session.suspend-timeout-seconds=0` | +0 |
| 3 ensayos: se suelta, **se suspende de inmediato** (`pw-cli send-command <id> Suspend {}`) y se borra 1 s después | +0 en los 3 |
| (control accidental: los mismos 3 con la orden mal escrita, sin suspender) | +1 en los 3 |

**Causa.** Cuando una salida queda libre («idle»), `suspend-node.lua` de WirePlumber 0.4.13 programa su suspensión para 5 s después. Al cumplirse, llama a `node:send_command("Suspend")` **sin comprobar que el nodo siga existiendo**. Si en ese rato la salida desapareció (se desenchufó la tarjeta), cae. La 0.4.14 es igual; la 0.4.17 comprueba `Feature.Proxy.BOUND` antes de suspender. Debian 12 trae la 0.4.13.

**En uso real:**
- **Disparador:** algo muy natural, cambiar de tarjeta con F10 y desenchufar la anterior en menos de 5 s (o cerrar el piano y desenchufar).
- **Consecuencias** (experimento con el piano abierto y `systemctl --user restart wireplumber`, sin notas):
  - PipeWire **deshace los enlaces de la reverb a la tarjeta y al ancla**: son nodos que configura WirePlumber. Los enlaces entre clientes JACK (sfizz → reverb) sobreviven.
  - El puente MIDI se recrea.
  - El enrutador seguía en «lista»: **el piano quedaba mudo sin avisar**. Su firma de puertos solo miraba nombres, que no cambian, y además se quedaba con el id viejo de la tarjeta, al que iban las teclas de volumen.
  - En 4 reinicios seguidos, al cuarto **el piano se cerró solo**. El puerto MIDI faltaba un instante, `enlazar` falló y el bucle salió con error. No fue la reverb: no hubo ningún SIGSEGV.

**Correcciones** (sin tocar la configuración del sistema):
1. **Suspensión inmediata de la tarjeta que se deja**, lo mismo que haría WirePlumber a los 5 s, pero sin esa ventana:
   - el enrutador, tras un cambio con F10 (efecto `suspender`, 0,3 s después de soltarla, con reintentos);
   - `piano-en-vivo.sh` al cerrar (con la tarjeta activa según el enrutador, que puede haber cambiado con F10);
   - `escuchar-midi.sh` al terminar.

   `salidas_audio.suspender_si_libre` solo actúa si la salida está «idle» (nadie la usa). `pw-cli` termina con código 0 aunque falle, así que el error se busca en lo que imprime.
2. **Enrutador.** Una sola lectura por segundo, `pw-link -iIl`, con el mismo costo que la anterior (~25 ms):
   - la **firma incluye los ids**: una tarjeta recreada con el mismo nombre se nota, y se toma su id nuevo;
   - **verifica que la reverb siga enlazada a la tarjeta activa**; si no, la vuelve a enlazar como en una reconexión, con su volumen. Tras un intento fallido espera 5 vueltas antes de reintentar, y al lograrlo borra el error.
3. **`piano-en-vivo.sh`.** El bucle rehace los enlaces de la reverb al ancla y el enlace MIDI, buscando de nuevo el puerto del puente: puede volver con otro número. Un fallo pasajero **ya no cierra el piano**. Usa una sola lectura de `pw-link -l`, como antes.
4. **La prueba** espera a que cada salida virtual esté suspendida antes de borrarla.

**Riesgo que queda:** al reiniciarse WirePlumber, las salidas de la reverb se quedan un instante sin enlaces, y el error de pipewire-jack 1.2.7 podría tumbarla. No pasó en **14 reinicios seguidos** con el piano abierto, y en los últimos 10, ya con las correcciones, todo volvió a enlazarse en menos de 3 s. Las caídas de WirePlumber ya no las provoca el piano. Se corrigen del todo con PipeWire 1.6 y WirePlumber 0.5, cuando el repositorio de Raspberry Pi los traiga (decisión 8 de la fase 09).

**Pruebas nuevas:**
- **`test_salidas_audio.py`**, 25 → 38:
  - lectura de `pw-link -iIl` (ids, puertos con espacios, varios orígenes);
  - firma (cambia al recrearse, no con los enlaces) y `enlazada`;
  - `suspender_si_libre` (libre, ocupada, ya suspendida, ausente, errores de `pw-cli` con código 0) y su línea de órdenes (espera a que quede libre; siempre código 0);
  - en el gestor: rehacer enlaces, no actuar sin tarjeta ni a mitad de un cambio, reintento espaciado, y que un error de otra orden no se borre.
- **`test_enrutador_midi.py`**: todos los efectos los ejecuta el enrutador, y rehacer enlaces también pausa.
- **`test_lib_pw.sh`**: `destinos_de` con una lectura ya hecha (sin volver a llamar a `pw-link`), y `ANCLA_ENTRADAS`.
- **`test_salidas_integracion.sh`**, 23 → 34 comprobaciones:
  - la anterior queda suspendida en menos de 2 s, y desenchufarla enseguida no hace caer a WirePlumber;
  - 5b: enlaces perdidos de la tarjeta, del ancla y del MIDI, cada uno rehecho;
  - 5c: **reinicio de WirePlumber con el piano abierto**, tras el que todo vuelve y el piano sigue abierto;
  - al cerrar, la tarjeta queda suspendida y WirePlumber no cayó en toda la prueba.
- **`test_escuchar_midi_integracion.sh`**, sección 6 nueva: **con tarjeta** (sin `-s`) contra una salida virtual. Ese camino no tenía prueba. La cadena va solo a la elegida, al terminar la tarjeta queda suspendida y desenchufarla no hace caer a WirePlumber.
- **Verificadas con mutaciones** (la prueba debe fallar si se quita cada corrección):
  - sin la verificación del enrutador: falla 5b (tarjeta) y 5c;
  - sin rehacer el ancla: falla 5b (ancla);
  - sin suspender al cambiar: falla 3, y **WirePlumber cae** al desenchufar la anterior, cosa que la prueba detecta;
  - sin suspender al cerrar y sin esperar al borrar: falla 6, con la caída detectada.
- **De paso se descartó** que sfizz o jalv se enlacen solos a la tarjeta predeterminada: arrancados sin enlazar, a los 8 s no tenían ningún enlace. Así `escuchar-midi.sh` no duplica la salida cuando F10 apunta a otra tarjeta.

## Pendientes

- [x] Prueba del usuario con las dos tarjetas reales (2026-10-20, 20:41–20:48, piano real con clavecín):
  - **Arranque:** sin tarjeta en las preferencias, eligió la G432 (primera USB) a 44,1 kHz y al 40 % de la primera vez. Quedó listo en 6 s.
  - **F10, G432 → G1, en caliente:** la G1 también al 40 % la primera vez. **La G432 quedó suspendida 1 s después del cambio** (registro: «suspendida (quedó libre)»).
  - **Desenchufar la G432 recién dejada** (20:45:27, 34 s después del cambio): el piano siguió sonando por la G1, **0 caídas de WirePlumber**, y no hizo falta reiniciarlo.
  - **Volumen por tarjeta:** el usuario subió la G432 al 100 % y la G1 al 85 %. Se recordaron así, en las preferencias y en WirePlumber; que la G432 vuelva al 100 % es lo previsto.
  - **Omitido a decisión del usuario** («saltémonos eso»): volver a la G432, desenchufar la tarjeta en uso, y cerrar y desenchufar. Esos casos los cubren las pruebas automáticas con salidas virtuales (secciones 5, 5b, 5c y 6). Desenchufar la G1 en uso se probó con la tarjeta real antes de estas correcciones.
  - **Al terminar, la Pi aún no veía la G432:** ninguna conexión USB nueva desde las 20:45:27.
- [x] Validación completa con las correcciones de WirePlumber (2026-10-20): **21/21**, 0 caídas de WirePlumber, sin restos. Una primera pasada también dio 21/21, pero se repitió porque coincidió con un experimento lanzado por error.

## Checklist

- [x] Tarjetas reales inspeccionadas (G432: 44,1 kHz disponible)
- [x] Detección y elección de salidas (`salidas_audio.py`), con pruebas
- [x] Enrutador: orden de cambio de salida, volumen por tarjeta, desconexión y reconexión, cortes de la tarjeta activa
- [x] Interfaz: F10, fila «Salida», ventanas de cambio y de desconexión
- [x] `piano-en-vivo.sh` / `escuchar-midi.sh` / `instalar.sh` sin nombre fijo; ancla siempre en la reverb (CPU medida: 1 % de un núcleo)
- [x] Prueba de integración con salidas virtuales (silenciosa): 22 comprobaciones
- [x] README en español e inglés (F10, tarjetas, limitación de 48 kHz en caliente)
- [x] Caída de WirePlumber 0.4.13 aislada (suspend-node.lua sin comprobar que el nodo exista) y evitada: suspensión inmediata de la tarjeta que se deja (F10, cierre, `escuchar-midi.sh`)
- [x] El piano se rehace solo si WirePlumber se reinicia: firma con ids, enlaces a la tarjeta (enrutador), al ancla y MIDI (bucle), sin cerrarse ante un fallo pasajero
- [x] Pruebas: unitarias (+15), integración 34 comprobaciones (reinicio de WirePlumber incluido), `escuchar-midi` con tarjeta; verificadas con mutaciones
- [x] README: limitación de WirePlumber 0.4.13 y el ancla «siempre» (no solo en silencio)
- [x] Prueba del usuario con la G1 y el G432: arranque, F10 en caliente, suspensión inmediata y desenchufe sin caídas. El resto lo omitió el usuario: lo cubren las pruebas automáticas
- [x] Validación completa: 21/21, sin caídas de WirePlumber
