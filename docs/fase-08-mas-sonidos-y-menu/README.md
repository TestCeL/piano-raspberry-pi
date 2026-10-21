# Fase 08 — Más sonidos y menú por categorías

## Petición del usuario (2026-10-19)

> «¿Qué otros soundfonts me aconsejarías agregar que sean realmente un must have, y qué sería exquisito tener?»

Propuesta: 10 sonidos de categorías que un piano digital suele traer y que faltaban (órganos, clavecín, cuerdas, piano eléctrico FM, mazas, arpa, viento, piano de fieltro). Además, un menú por categorías.

> «Todo, más menú por categorías y poder navegar entre los instrumentos y cargar alguno… con un F9… buscar y seleccionar ahí el que desee. Mantener la barra de carga y mantener el salto secuencial uno a uno.»

Quedan **para después**, como se propuso:
- la división del teclado y las capas (bajo + piano, piano + cuerdas);
- el Hammond por modelado (setBfree), que requeriría la aprobación del usuario para instalar sus dependencias gráficas.

El arranque automático pasa a la **fase 09** y, por decisión del usuario del 2026-10-20, a la **fase 11** (la 09 es la publicación y la 10 la configuración).

## Sonidos añadidos (12; el catálogo pasa de 10 a 22)

| Categoría | id | Nombre | Fuente | Licencia |
|---|---|---|---|---|
| Pianos de cola | softify | Softify (Yamaha S6, suave) | Pianobook (Dore Mark): descargado por el usuario con su cuenta | Pianobook: libre para su música, **no redistribuir** |
| Pianos eléctricos | fm-piano | Piano FM (Yamaha TX81Z) | VCSL (Versilian) | CC0 |
| Órganos | hammond-drawbar | Hammond (drawbars) | FreePats (grabado de setBfree) | CC0 |
| Órganos | hammond-rock | Hammond rock | FreePats (Strix SoundFont Team) | CC0 |
| Órganos | hammond-percusivo | Hammond percusivo | FreePats (Strix SoundFont Team) | CC0 |
| Órganos | iglesia | Órgano de iglesia (tubos, registro fuerte) | VCSL | CC0 |
| Clavecín | clavecin | Clavecín flamenco (8' + 4') | VCSL | CC0 |
| Cuerdas | cuerdas | Cuerdas (ensemble) | VSCO 2 CE (Versilian), ensemble generado | CC0 |
| Cuerdas | arpa | Arpa de concierto | VCSL | CC0 |
| Percusión | vibrafono | Vibráfono (mazas suaves) | VCSL | CC0 |
| Percusión | marimba | Marimba | VCSL | CC0 |
| Viento | saxo | Saxo tenor (con vibrato) | VCSL | CC0 |

- El **piano de fieltro** propuesto (Kawai Felt Piano de Jon Meyer) ya no se ofrece gratis: su autor lo retiró. Se sustituyó por **Softify Piano Vol 1** de Pianobook, que trae versión SFZ propia.
- Celesta, coro y clavinet no se propusieron: no se encontró una versión gratuita con calidad suficiente.

## Descarga y verificación

- `tools/pi/descargar-instrumentos.sh` (en la Pi) admite tres tipos de origen:
  - `tar`: repositorios de sfzinstruments;
  - `txz`: archivos de FreePats, con SHA-256 en el manifiesto;
  - `git`: solo las carpetas necesarias de un repositorio grande, con clon parcial y *sparse checkout* **fijado a un commit**. git verifica cada archivo por su hash, y si la rama cambió, se detiene.

  VCSL entero pesa 3,9 GB y se bajaron 658 MB (7 carpetas, commit `dfcf4a49…`); de VSCO 2, 228 MB (4 carpetas de cuerdas, commit `6dd651d5…`).
- `tools/instrumentos/preparar-softify.sh` (en el PC): extrae del `.zip` del usuario solo la versión SFZ y el Readme (1,2 GB, 497 archivos, sin la parte de Kontakt) y los copia a la Pi. Después compara **archivo por archivo** el SHA-256 del zip con el de la Pi.
  - Incidencia: la primera verificación falló sin que los archivos fueran distintos. El `sha256sum` de Git Bash en Windows escribe las líneas como `*./archivo`, distinto del de Linux. Ahora las sumas se calculan con Python en ambos lados, y el lado del PC se lee del zip sin extraerlo.
- Todas las descargas y extracciones se hicieron con el piano cerrado, con prioridad baja y en los núcleos 0–1.

## Cuerdas: ensemble generado (`tools/pi/generar_cuerdas.py`)

VSCO 2 trae las secciones por separado. El generador crea `Cuerdas ensemble (piano digital).sfz` junto a ellas, **sin solaparlas**, para no duplicar voces:

| Sección | Teclas |
|---|---|
| contrabajo | La0–Si1 (21–35; la región más grave baja 3 semitonos) |
| chelos | Do2–Si2 (36–47) |
| violas | Do3–Fa#3 (48–54) |
| violines | Sol3–Re6 (55–86) |

Conserva las regiones, las capas de dinámica y las envolventes de cada sección. Los SFZ originales no se tocan.

## Medición (en la Pi, `medir_instrumentos.py`)

En la Pi (ARM64, `sfizz_render` y `sfizz_jack` reales), con cada instrumento como sonará en vivo: controles iniciales y transposición del catálogo. Temperatura máxima en todas las mediciones: 47–51 °C, sin bajo voltaje (vigilancia con `con_vigilancia.sh`).

### Mejoras de la herramienta (`medir_instrumentos.py`)

- **Afinación**: pieza nueva `05-afinacion` (La4). La frecuencia fundamental se estima con **YIN** (`analizar_wav.frecuencia_fundamental`, Python puro) y se da error si se desvía más de ±50 cents.
- **Pedal «no aplica»**: si sin pedal la cola ya suena (por encima de −60 dBFS), el instrumento no se corta al soltar la tecla (arpa, marimba, vibráfono), y eso no es un fallo. Solo es «NO» si se corta y el pedal no lo sostiene.
- **Ganancia limitada por pico**: iguala el RMS al del Salamander, pero sin dejar el pico por encima de −9 dBFS (marca «p»). Afecta al arpa (+3,1 → −1,9 dB) y al Softify.

### Hallazgo: cuatro instrumentos mapeados una octava abajo

La afinación dio −1200 cents en el Piano FM y en los tres Hammond. La causa no era un drawbar de 16' del registro:
- **Energía en 220 y 440 Hz**: domina 220 Hz por 12,7 dB (FM), 11,3 (drawbar), 5,7 (rock) y 1,4 (percusivo). El Salamander y la marimba, en cambio, dan 440 Hz dominante.
- **Frecuencia de cada muestra frente a su tecla**: −12,0 semitonos en todas las muestras medidas de los cuatro, frente a +0,04 en la marimba.

Las muestras están grabadas una octava por debajo de su tecla. **Corrección**: campo `transposicion: 12` en el catálogo, que el enrutador suma a las notas enviadas a sfizz. Cada tecla suena en su altura con la muestra correcta y sin reescalar. La interfaz sigue mostrando la tecla pulsada. Tras la corrección, los cuatro dan entre −1 y +12 cents. La prueba de integración lo comprueba de punta a punta: un La4 tocado en el Hammond, grabado, mide su frecuencia esperada.

### Resultados (offline: 02-acordes-pedal, 04-prueba-pedal, 05-afinacion; tiempo real: 03-arpegios-densos, que satura las 32 voces)

| id | Ganancia | Pico final | Pedal | Afinación | B/Q máx / medio | Cortes | RAM | Carga (frío / caliente) |
|---|---|---|---|---|---|---|---|---|
| softify | +1,4 (p) | −9,0 | sí | −6 c | 0,41 / 0,21 | 0 | 239 MB | 3,5 / 0,9 s |
| fm-piano | −1,2 | −12,2 | sí | +1 c | 0,23 / 0,10 | 0 | 57 MB | 0,8 / 0,4 s |
| hammond-drawbar | −10,4 | −15,1 | sí | −1 c | 0,34 / 0,14 | 0 | 29 MB | 0,3 s |
| hammond-rock | −11,3 | −15,2 | sí | +12 c | 0,44 / 0,26 | 0 | 42 MB | 0,5 / 0,4 s |
| hammond-percusivo | −12,7 | −14,6 | sí | 0 c | 0,35 / 0,21 | 0 | 44 MB | 0,4 / 0,3 s |
| iglesia | −9,8 | −18,4 | sí | +1 c | 0,28 / 0,13 | 0 | 89 MB | 0,4 s |
| clavecin | +1,4 | −11,4 | sí | +1 c | 0,81 / 0,53 | 2 | 169 MB | 0,4 s |
| cuerdas | −2,4 | −15,0 | sí | −1 c | 0,34 / 0,17 | 0 | 138 MB | 0,3 s |
| arpa | −1,9 (p) | −9,0 | n/a | +5 c | 0,39 / 0,32 | 0 | 149 MB | 0,5 s |
| vibrafono | +2,6 | −14,2 | n/a | 0 c | 0,41 / 0,31 | 0 | 84 MB | 0,4 s |
| marimba | +2,4 | −10,3 | n/a | +5 c | 0,38 / 0,29 | 0 | 55 MB | 0,5 s |
| saxo | −5,9 | −15,4 | sí | 0 c | 0,23 / 0,11 | 0 | 57 MB | 0,5 / 0,4 s |

**Conclusión: los 12 son tocables en la Pi 3**, todos más livianos que el Salamander (B/Q 0,89 en la misma prueba). Todas las pasadas en tiempo real tuvieron sonido verificado al primer intento. Las ganancias y los tiempos de carga (los de disco en frío, los prudentes) quedan en el catálogo; el enrutador aprende los reales con el uso.

## Menú F9 por categorías

- **F9** abre un menú desplegado arriba, sobre el teclado dibujado (blanco sobre azul):
  - una fila de pestañas con las categorías que tienen instrumentos, en el orden del catálogo, con la elegida `[entre corchetes]`;
  - debajo, hasta 7 instrumentos, con el elegido resaltado y «(suena ahora)» en el actual;
  - si la lista es más larga, se desplaza y el elegido siempre se ve.

  Abre en la categoría y el instrumento que suenan.
- **←/→** cambian de categoría; **↑/↓** recorren los instrumentos (circular, con repetición al mantener); **ENTER** carga el elegido con la misma ventana y barra de progreso de la fase 07; **F9 o ESC** cierran sin cambiar nada. ESC dentro del menú **no** sale del piano.
- **Búsqueda**: con el menú abierto, las letras del teclado del PC escriben un filtro (en vez de tocar notas) y **RETROCESO** borra.
  - Muestra los instrumentos de cualquier categoría cuyo nombre o categoría contiene el texto, sin distinguir mayúsculas ni tildes: «org» encuentra los Órganos y el «Órgano de iglesia».
  - Si nada coincide, ENTER no hace nada.
- Si una nota o el pedal estaban pulsados al abrir el menú, se sueltan con normalidad al soltar la tecla.
- **F6/F7** se mantienen (uno a uno, con la pausa de 0,6 s para recorrer sin cargar cada uno). Desde el menú la carga es inmediata: orden `instrumento ya <id>` del enrutador.
- El enrutador publica la lista de instrumentos disponibles con su categoría (`lista` en su estado); la interfaz no lee el catálogo por su cuenta.
- **Caracteres en pantalla**: las pruebas verifican ahora contra la **tabla Unicode real de la fuente de la consola** de la Pi (`glifos_consola.txt`, 791 caracteres leídos de `Uni2-Terminus32x16.psf.gz`), en lugar de CP437:
  - «Ó» y las flechas `← ↑ → ↓` existen y se usan;
  - `▀ ♪ ►` no existen y no se usan.

## Créditos de cada sonido en la interfaz (2026-10-20)

> «En la parte inferior izquierda, detalles de cada sonido, en letra pequeña: autor y restricciones o licencia» · «en el menú F9, todo el detalle, y en la pantalla principal solo lo que no quede cortado; que quepa todo en la pantalla»

**Catálogo (`instrumentos.json`).** Dos campos nuevos por sonido:
- **`uso`** (obligatorio, como mucho 40 caracteres): las condiciones en palabras simples.
  - «libre, sin condiciones»: CC0 y dominio público, 14 sonidos.
  - «libre; citar al autor»: CC BY, 5 sonidos.
  - «solo uso no comercial»: Rhodes.
  - «no redistribuir las muestras»: Softify.
  - «gratis; mejor no redistribuir»: Maestro, que no tiene licencia estándar.
- **`restringido`** (opcional, `true` en esos 3 últimos): marca la restricción para resaltarla.

Autor, licencia y fuente quedan limitados a 100 caracteres, para que el menú F9 los muestre siempre enteros. El enrutador publica los cinco datos en la lista de su estado.

**Pantalla principal: panel «SOBRE ESTE SONIDO»**, debajo de ESTADO.
- Ocupa las 7 filas libres del monitor (filas 26–32 de 33) y muestra el sonido que suena.
- **Letra chica:** la consola usa una sola fuente para toda la pantalla, así que no se puede achicar una parte. El panel va en gris tenue y la restricción, si la hay, resaltada en amarillo.
- **Solo datos enteros:**
  - cada dato ocupa de 1 a 3 filas, partido por palabras;
  - la dirección web va sin `https://` y se parte tras cada «/»;
  - el dato que no cabe entero no se muestra;
  - si no caben todos, se quitan por prioridad: primero la fuente, luego el autor, luego la licencia; el uso, nunca.
- Con los 22 sonidos reales se ve todo, salvo la web del Kawai vertical (demasiado larga), que está entera en el menú.

**Menú F9:** debajo de la lista, los cuatro datos **completos** del sonido marcado, una fila cada uno con la web entera; la restricción en amarillo. El menú pasa de 12 a 17 filas y sigue cabiendo en la pantalla.

**Comprobado** dibujando la interfaz real en 120×33 con los datos reales:
- el Rhodes y el Hammond rock, este último con las 7 filas, llegan exactamente a la última fila;
- el menú abierto muestra la web completa del Kawai vertical.

## Cortes en la primera sesión del usuario (2026-10-20)

> «Comenzó con muchos cortes» · «sigue con problema» · «¿algo cambiaste?»

El contador marcó 21 cortes en ~1,5 min con el Osiris. Según el registro del enrutador:
- 2 fueron al arrancar, sin sonido;
- **13 al cambiar la latencia con F4**, de 128 a 1024: cada cambio reconfigura el grafo y produce cortes breves;
- unos 6 mientras se tocaba, al principio con latencia **128** (2,9 ms, el mínimo).

Además, desde la fase 07 el contador cuenta los cortes del reloj, que antes no veía (`pw-top` no los cuenta), así que la cifra parecía mucho peor que antes.

**Experimentos (cadena real, Osiris, latencia 512, G1 como reloj silenciada en el sumidero y restaurada; vigilancia de temperatura y bajo voltaje):**

| Situación (25–40 s tocando acordes con pedal) | Cortes |
|---|---|
| Caché fría (vaciada) / caliente, PipeWire fijado a 2–3 | 0 / 0 |
| Caché fría / caliente, PipeWire sin fijar | 0 / 0 |
| Interfaz real dibujando en el monitor (2 pasadas) / sin dibujar | 0, 0 / 0 |
| Cambiando el **volumen** como al mantener la flecha (≈30 órdenes/s a la G1) | **1** |
| Sin cambios / cambiando la reverb | 0 / 0 |

Se descartaron la caché, la fijación de núcleos, la memoria (sin swap, 527 MB libres; el usuario veía «mucha memoria», que es la caché de disco) y el dibujo en pantalla. El reinicio de CUPS de las 00:00 era la rotación nocturna de registros y no coincidió con los cortes.

**Correcciones (pedidas por el usuario: «aplica»):**
1. **Volumen agrupado**:
   - el primer paso sale al instante;
   - al mantener la flecha, los pasos se ven al instante, pero a la G1 sale como mucho **una orden cada 0,15 s**, siempre con el último valor; antes salía una por paso, ≈30/s de tráfico USB a su mezclador;
   - la relectura periódica no pisa un cambio aún sin enviar, y al salir se envía el pendiente.
2. **Los cortes de un cambio de latencia no se cuentan**: los de los 2 s siguientes a cada F4 se anotan aparte (`CORTE por cambio de latencia (no se cuenta)` en el registro; `xruns_por_latencia` en el estado).
   - Se decide por la **hora del aviso de PipeWire** (`journalctl -o short-unix`), no por la hora en que se lee: el registro puede llegar tarde.
   - Funciona también con `pw-top` (sin registro).
3. **Recomendación al usuario**: latencia 256 o 512 en vez de 128 (con 512, 0 cortes en todas las pruebas). Es su ajuste (F4) y no se cambió.

Incidencia: el experimento del volumen dejó la G1 en 70 % en vez de 80 %. Se detectó al terminar y se restauró. El script restauraba el valor leído al principio de cada pasada, no el de antes de la primera.

## Caída de sfizz con SIGSEGV (error de pipewire-jack 1.2.7) — 2026-10-20

**Cómo apareció.** La validación de las correcciones anteriores quedó colgada en `test_sfizz_jack_ordenes.sh`: sfizz había caído con SIGSEGV (00:55:19) y la prueba esperaba para siempre al escribir en su FIFO, que ya no tenía lector.

**Diagnóstico (volcado de memoria con gdb).**
- La caída ocurre en el hilo de audio: `process` → `Sfizz::renderBlock` → `Synth::renderBlock` → `EffectBus::mixOutputsTo`.
- Falla al acceder a la **primera muestra del búfer de salida** que PipeWire entregó en ese mismo ciclo (1024 muestras). Ese búfer se acababa de escribir al empezar el ciclo, así que otro hilo liberó esa memoria a mitad del ciclo.
- El hilo de órdenes estaba inactivo: las órdenes del parche 0002 no intervienen.

**Causa.**
- En pipewire-jack 1.2.7, cuando un puerto de salida pierde su **último enlace**, `mix_set_io` se encola sin esperar (`pw_data_loop_invoke(…, false)`). Acto seguido, `client_node_port_use_buffers` → `clear_buffers` libera la memoria (`pw_memmap_free`) aunque el hilo de audio del cliente siga escribiendo en ella.
- Está corregido en PipeWire **1.6** (commit `f7fdafc2`, «loop: add method to run a function with the lock», etiquetas 1.5.81 y siguientes): esa operación pasa a hacerse con el bucle de datos bloqueado.
- La Pi tiene `1.2.7-1~bpo12+1+rpt5` (archive.raspberrypi.com), la versión más nueva disponible para ella.

**Pruebas (`tools/pi/experimento_carrera_enlaces.sh`, en silencio, con vigilancia de temperatura):**

| Situación (sfizz tocando notas solapadas; un grabador se enlaza y desenlaza de sus salidas) | Resultado |
|---|---|
| Sin ancla: las salidas pasan de 1 a 0 enlaces; ninguna orden por la entrada | **SIGSEGV en el ciclo 140** (87 s), mismo rastro |
| Con un ancla (grabador nulo enlazado todo el tiempo) | 319 ciclos en 200 s, sin fallo |
| Con el ancla real de `lib-pw.sh` (`iniciar_ancla`) | 209 ciclos en 120 s, sin fallo |

**Quién lo provocaba.** Solo las pruebas y las herramientas de medición, que enlazaban y quitaban grabadores en salidas sin ningún otro enlace:
- `test_sfizz_jack_ordenes.sh`: 4 grabaciones por pasada;
- `escuchar-midi.sh -s -r`, que usa `medir_instrumentos.py --tiempo-real`: una por pieza;
- `piano-en-vivo.sh -s`, que usa la prueba de integración: la reverb sin enlaces y grabadores que van y vienen.

En el uso real, los enlaces sfizz → reverb → G1 no cambian mientras se toca, y el registro no muestra ninguna caída tocando. Las 5 caídas de `piano-vivo-fx` del registro (19/10 y 20/10 a las 00:07) son otra cosa: el fallo de arranque de jalv («Failed to connect to audio system»), que termina con SIGSEGV al salir y ya se reintenta desde la fase 07.

**Corrección (sin tocar PipeWire ni sfizz):**
1. **Conectar antes de cortar**: `redirigir` / `redirigir_par` en `lib-pw.sh` enlazan primero el destino nuevo y después quitan los demás. Si no pueden enlazar, terminan con error sin haber quitado nada.
   - Sustituyen a `desconectar_todo`, que se elimina: dejaba las salidas sin enlaces con el cliente sonando.
2. **Ancla**: `iniciar_ancla` / `detener_ancla`, un grabador nulo (`pw-record` a `/dev/null`) que en silencio es el único destino de las salidas.
   - Se detiene **después** de los clientes.
   - No hereda el bloqueo de instancia única del piano.
3. Usan las dos cosas:
   - `piano-en-vivo.sh`: sfizz → reverb y reverb → G1; en silencio, el ancla `piano-ancla-vivo`, que el bucle principal vigila;
   - `escuchar-midi.sh`: el ancla `piano-ancla-prueba-<pid>`;
   - `test_sfizz_jack_ordenes.sh`.
4. `detener-audio.sh` detiene las anclas huérfanas **después** de las unidades y comprueba que no quede ninguna.
5. `test_sfizz_jack_ordenes.sh` ya no se cuelga:
   - cada orden al FIFO tiene un límite de 3 s;
   - si sfizz termina, la prueba informa la causa del registro y se aborta.

**Decisiones.**
- No se parcheó sfizz para que renderizara en un búfer propio y copiara al final: solo acortaría la ventana, porque la carrera está en pipewire-jack.
- La corrección de raíz es PipeWire ≥ 1.6. Para la Pi habría que compilarlo o usar otro repositorio, y eso es un cambio crítico del sistema que requiere la aprobación del usuario. No se hizo.

**Silencio intermitente en la primera validación.**
- En la primera validación completa tras el cambio, las grabaciones de `test_sfizz_jack_ordenes.sh` salieron mudas: pico −999, sfizz vivo y todas las órdenes confirmadas.
- Al repetirla, sola y justo después de la suite de `escuchar-midi`, pasó entera, y la grabación con ancla da −17,5 dBFS. El ancla no silencia.
- No se pudo reconstruir la causa desde el registro. Ya se había visto algo parecido en la medición en tiempo real, que por eso reintenta una vez cuando graba silencio.
- La prueba creaba el enlace MIDI con `|| true`, así que un fallo ahí pasaba inadvertido. Ahora lo verifica, y si la nota de referencia no suena lo informa como tal, con los enlaces del nodo y su estado en PipeWire.

**Riesgo residual.** Al cerrar el piano se detiene la reverb antes que sfizz, así que sfizz pierde su enlace una vez por cierre. No hay ninguna caída registrada en ninguna sesión, y sería inocua porque el piano ya se está cerrando. La prueba de integración ahora cuenta cualquier SIGSEGV de sfizz o de la reverb durante toda la prueba, incluidos los cierres.

## Pruebas

| Suite | Novedades de la fase |
|---|---|
| `test_catalogo_instrumentos.py` | los 22 sonidos agrupados por categoría (orden de F6/F7 = orden del menú), categorías y nombres, licencias (NC del Rhodes, «no redistribuir» del Softify), `carga_s` y `transposicion` validados, octava corregida en los 4 instrumentos medidos |
| `test_generar_cuerdas.py` (8) | análisis SFZ (comentarios, valores con espacios, herencia de cabeceras), franjas sin solaparse, capas/envolventes/rutas conservadas, `key=` convertido, grave extendido, resumen con las franjas finales, errores |
| `test_analizar_wav.py` | frecuencia fundamental YIN: seno, segundo armónico dominante (no confunde la octava), estéreo, resolución en cents, silencio y tramo corto |
| `test_generar_midis_prueba.py` | `05-afinacion`, `transponer_smf` (tiempos intactos, notas fuera de rango quitadas sin perder el tiempo) |
| `test_medir_instrumentos.py` | cents, afinación en el flujo completo (incluida una octava abajo = fallo), pedal «no aplica», ganancia limitada por pico |
| `test_enrutador_instrumentos.py` | carga inmediata `instrumento ya`, lista para el menú, transposición del instrumento (la interfaz ve la tecla; a sfizz va desplazada; fuera de rango no se envía) |
| `test_teclado_piano.py` | menú: apertura en el instrumento actual, navegación circular, ENTER/ESC/F9, búsqueda sin tildes y por categoría, sin resultados, límite del filtro; intérprete: las letras no tocan con el menú abierto, ESC no sale del piano, teclas y pedal pulsados antes se sueltan, repeticiones; filas del menú (pestañas, elegido, desplazamiento, anchos); dibujo real en pseudoterminal 120×33; **caracteres verificados contra la fuente real de la consola** |
| `test_teclado_piano.py` (volumen) | pasos agrupados al mantener la flecha (una orden por intervalo con el valor final), la relectura no pisa un cambio pendiente, el pendiente se envía al salir |
| `test_enrutador_midi.py` (cortes) | cortes de un cambio de latencia anotados aparte, por la hora del aviso (aunque se lea tarde), también con pw-top |
| `test_piano_en_vivo_integracion.sh` | carga inmediata del Hammond y **La4 grabado a la frecuencia esperada** (octava corregida, de punta a punta); al rearrancar vuelve el último instrumento |
| `test_catalogo_instrumentos.py` (créditos) | `uso` de los 22 sonidos: CC0 y dominio público → «libre, sin condiciones», CC BY → «citar al autor»; exactamente 3 `restringido`; validación: `uso` obligatorio y no vacío, largos máximos, `restringido` solo `true`/`false`; `creditos` muestra el uso y la marca |
| `test_enrutador_instrumentos.py` (créditos) | la lista publicada lleva autor, licencia, uso, restricción y fuente de cada sonido |
| `test_teclado_piano.py` (créditos) | `partir_entero` (nunca recorta; web partida tras «/»); panel: filas exactas del Rhodes, lo que no cabe entero no se muestra, prioridad al faltar filas (7 → 0), datos que faltan, solo `true` resalta; menú: detalle completo del marcado, alto fijo sin créditos, sin resaltar si no hay restricción; **los 22 sonidos reales: todo lo que se ve está entero y el uso siempre se ve; en el menú, los cuatro datos enteros dentro del ancho**; espacio: 7 filas libres en 33 y menú de 17 filas; dibujo real en pseudoterminal (panel abajo a la izquierda y menú con la web completa) |
| `test_piano_en_vivo_integracion.sh` (créditos) | el enrutador real publica los créditos de los 23 sonidos del catálogo de prueba, del catálogo a la interfaz |
| `test_lib_pw.sh` (enlaces) | `redirigir`: enlaza antes de quitar (orden de operaciones), conserva el destino ya enlazado, varios destinos, error sin quitar nada si no puede enlazar, error si no puede quitar; `redirigir_par` estéreo, fuente mono y destino mono; ancla: aísla de la G1, nombre de nodo, se detiene con `detener_ancla`, mono, error sin puertos. **Invariante vigilada en cada desenlace: ninguna salida se queda sin enlaces.** Una variante «cortar antes de conectar» hace fallar 6 comprobaciones. |
| `test_sfizz_jack_ordenes.sh` | salidas enlazadas solo al ancla; no se cuelga si sfizz cae: informa la causa y se aborta; el enlace MIDI se verifica (antes un fallo pasaba en silencio: `\|\| true`); si la nota de referencia no suena, lo dice así y muestra los enlaces del nodo y su estado en PipeWire |
| `test_piano_en_vivo_integracion.sh` (ancla) | en silencio la reverb va solo al ancla; el ancla se detiene al parar y, tras `kill -9`, la recupera `detener-audio.sh`; **ni sfizz ni la reverb caen con SIGSEGV en toda la prueba** (sin contar los arranques fallidos de jalv, que se reintentan) |

## Pendientes

- [ ] Prueba del usuario: los 12 sonidos nuevos y el menú F9 (aviso previo: auriculares).
- [ ] División del teclado y capas (más adelante, a pedido).
- [ ] Teclado MIDI (llega la próxima semana).
- [ ] Arranque automático → fase 11 (orden decidido por el usuario el 2026-10-20: 09 publicación, 10 configuración, 11 arranque automático).
- [ ] PipeWire ≥ 1.6, que corrige de raíz la caída de pipewire-jack: necesita la decisión del usuario, porque implica compilarlo o usar otro repositorio. Hasta entonces la protegen el ancla y «conectar antes de cortar».
- [ ] Clic sutil al empezar algunas notas: comprobar si el contador de cortes sube (a pedido).

## Checklist

- [x] Descarga verificada de los 12 sonidos (commit fijado / SHA-256 / archivo por archivo)
- [x] Ensemble de cuerdas generado
- [x] Medición: nivel, pico, pedal, afinación, tiempo real, tiempo de carga (y corrección de la octava de 4 instrumentos)
- [x] Menú F9 (categorías, navegación, búsqueda), barra de carga y F6/F7 se mantienen
- [x] Pruebas y validación completa en la Pi: **15 suites en verde** (47 °C máx., sin bajo voltaje; la Pi queda limpia)
- [x] Cortes de la primera sesión: volumen agrupado y cortes por cambio de latencia anotados aparte
- [x] Créditos de cada sonido: panel abajo a la izquierda (solo datos enteros) y detalle completo en el menú F9. Validación completa: **15 suites en verde** (2026-10-20; 60 °C máx., sin bajo voltaje; G1 al 80 %)
- [ ] Créditos del proyecto (lo que armó el usuario): falta saber con qué nombre y dónde los quiere
- [x] Caída de sfizz (SIGSEGV de pipewire-jack 1.2.7) diagnosticada, reproducida y evitada (ancla y «conectar antes de cortar»); las pruebas ya no se cuelgan si sfizz cae
- [x] Validación completa tras estas correcciones: **15 suites en verde** (2026-10-20 03:03; 61 °C máx., sin bajo voltaje). Ningún SIGSEGV durante las validaciones: los únicos del registro son los dos experimentos provocados a propósito. G1 al 80 %, sin silenciar, y la Pi queda limpia.
