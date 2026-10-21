# Fase 09 — Preparar la publicación

## Petición del usuario (2026-10-20)

> «¿Te parece buena idea publicarlo?» · «Y si me gusta la idea de mencionar que se desarrolló con la ayuda de Claude. Y si te basaste en alguna fuente, mencionarlo en los créditos.»

Antes, el usuario pidió los créditos de lo que él armó: «esto creo que no es algo que esté disponible en internet, ¿no? Es customizado».

## Objetivos

Dejar el proyecto listo para publicarlo en GitHub sin datos personales, con licencia, créditos y una guía de instalación que funcione desde cero. **No se publica nada hasta probar la instalación completa siguiendo solo el README.**

## Decisiones del usuario (2026-10-20)

| # | Decisión | Respuesta |
|---|---|---|
| 1 | Nombre en los créditos | **Reinaldo Johnson Espinoza** (su nombre real; su usuario de GitHub, «TestCeL», solo aparece en la dirección del repositorio y puede cambiarlo cuando quiera) |
| 2 | Licencia del código del proyecto | **MIT** |
| 3 | sfizz | **Publicar el programa ya compilado** (con los avisos de copyright de sfizz y sus componentes) **y** las instrucciones/script para compilarlo |
| 4 | Orden de fases | **09 publicación, 10 configuración (salida de audio), 11 arranque automático** |
| 5 | Créditos visibles | **Sí**: una línea al pie del menú F9 («Piano Raspberry Pi — creado por […], con la ayuda de Claude») |
| 6 | Idiomas | **README en español y en inglés, completos** («ojalá dejar esto en ambos idiomas») |
| 7 | Publicación | **En GitHub, al final del todo** («publicar es al final final, no ahora»): después de la fase 10 y de probar la instalación desde cero siguiendo solo el README |
| 8 | PipeWire 1.6 | **No compilarlo**: cuando el repositorio de Raspberry Pi lo traiga y todo lo demás funcione, se actualiza **manteniendo** el ancla y «conectar antes de cortar» como doble protección («dejando blindado todo») |

Créditos: el usuario quiere mencionar que se desarrolló con la ayuda de Claude (Anthropic) y que se citen las fuentes consultadas.

## Funcionalidades previstas

1. **Datos personales fuera**: la IP de la Pi (aparecía en 5 archivos) y el nombre de usuario de la Pi (en 8) dejan de estar fijos. El correo no aparece en ningún archivo.
2. **`dist/` fuera del repositorio** (297 MB de grabaciones y pruebas de fases anteriores).
3. **Repositorio git** (ahora no lo es), con `.gitignore`.
4. **README de portada en español y en inglés**: qué es, hardware, instalación paso a paso, uso y captura.
5. **`LICENSE` (MIT)** y **archivo de créditos** (en los dos idiomas):
   - el proyecto: autor y ayuda de Claude;
   - componentes libres y su licencia: sfizz (BSD-2; los parches parten de su código), PipeWire (MIT), jalv (ISC), mda-lv2 (GPL-3), la fuente Terminus (OFL);
   - los 22 sonidos: autor, licencia y fuente (el Softify se descarga a mano de Pianobook; las muestras nunca van en el repositorio);
   - fuentes consultadas en el proyecto: código de PipeWire y su corrección (commit `f7fdafc2`), código y documentación de sfizz, especificación SFZ, páginas de cada biblioteca de sonidos.
6. **Créditos al pie del menú F9.**
7. **Programa sfizz compilado** con sus avisos de licencia, además del script de compilación (Docker).
8. **Prueba de instalación desde cero** siguiendo solo el README.

## Avance (2026-10-20)

**Datos personales.**
- `piano` usa `$HOME` en lugar de `/home/<usuario>`.
- Las dos pruebas de integración encuentran sus módulos por `PYTHONPATH` en lugar de una ruta fija.
- Los scripts del PC (`preparar-upright-kw.sh`, `preparar-softify.sh`) piden la Pi como argumento o con `PIANO_PI`; sin ella, explican el uso y terminan con el código 2.
- La documentación usa `usuario@ip-de-la-pi`.
- Revisado: no queda la IP, el usuario, rutas del PC ni el correo fuera de `dist/`.

**Repositorio git** (`main`, **sin commits**: se harán cuando el usuario lo indique).
- `.gitignore`: `dist/`, registros, cachés, audio y archivos descargados.
- `.gitattributes`: todo con LF, porque los scripts se ejecutan en la Pi.
- **Identidad local del repositorio**: «Reinaldo Johnson Espinoza» con el correo privado de GitHub. La configuración global del PC tenía un correo del trabajo que habría quedado publicado en el historial; no se modificó, solo se reemplaza en este repositorio.
- Entran 63+ archivos; ninguno de `dist/`, ni cachés, ni audio, ni CRLF.

**Licencia y créditos.**
- `LICENSE` MIT a nombre de Reinaldo Johnson Espinoza.
- `CREDITOS.md` y `CREDITS.md` **se generan desde el catálogo** (`tools/pi/generar_creditos.py`), así la tabla de sonidos nunca queda desactualizada. Contienen:
  - el proyecto, con la ayuda de Claude;
  - los 8 programas libres que usa y su licencia;
  - los 22 sonidos, con las restricciones en negrita;
  - las fuentes consultadas: solo las reales, tomadas de la documentación y de esta sesión.
- Las frases del catálogo se traducen con una tabla. Una frase nueva en español sin traducir hace fallar el generador, para que no se publique un CREDITS.md a medias.
- Créditos al pie del menú F9: «Piano Raspberry Pi · creado por Reinaldo Johnson Espinoza, con la ayuda de Claude (Anthropic)». El menú pasa a 18 filas y sigue cabiendo.

**sfizz para publicar** (`tools/build-sfizz/empaquetar-publicacion.sh`) → `dist/publicacion/piano-rpi-sfizz-1.2.3-arm64.tar.gz`.
- Comprueba las sumas de los programas, que el código fuente es el oficial (SHA-256 de BUILDINFO) y que declara los dos parches.
- Lleva los programas, BUILDINFO, sumas, parches, un LEEME en los dos idiomas y **los 24 avisos de licencia** de sfizz y sus componentes: Apache-2.0, MIT, BSD, Boost y otras.
- El tar se crea en Linux, con los permisos correctos.
- **Probado en la Pi**: sumas correctas, `sfizz_render` arranca y los programas son idénticos byte a byte a los instalados.

## Inventario de la instalación (2026-10-20)

Se revisó toda la documentación de las fases 01–09 y todos los scripts. **Hoy nadie podría reproducir el piano desde cero**: varios pasos se hicieron a mano por SSH y no quedaron escritos.

| Falta | Detalle |
|---|---|
| Copiar las herramientas | `tools/pi/*` y `tools/midi/generar_midis_prueba.py` van a `~/piano/tools`; nunca se documentó cómo |
| Comando `piano` | `/usr/local/bin/piano`: no se documentó la instalación (ahora `sudo install -m 755`) |
| sfizz | Programa compilado en `~/piano/bin` (ya hay paquete de publicación) |
| Reverb mda-lv2 | En esta Pi es una copia suelta en `~/.lv2/mda.lv2`, no un paquete; en una instalación nueva sería `sudo apt install mda-lv2` |
| Salamander | El instrumento por defecto **no está en `descargar-instrumentos.sh`** (FreePats `.tar.xz`, SHA-256 en la fase 04): paso manual |
| Cuerdas | `generar_cuerdas.py ~/piano/instrumentos/vsco2` después de descargar VSCO 2: paso manual |
| Upright KW | Solo existe en `.7z`; el script del PC necesita Docker. Esta Pi tiene `/usr/bin/7z` |
| Softify | Descarga manual con cuenta de Pianobook; el script del PC necesita Git Bash y Python de Windows |
| Pruebas | `test_escuchar_midi_integracion.sh` usa un MIDI de Mutopia descargado a mano (`10-satie-gymnopedie-1.mid`) |
| Tarjeta de sonido | `SINK_PATRON` fijo a la Sound BlasterX G1 en `piano-en-vivo.sh` y `escuchar-midi.sh`: **con otra tarjeta el piano no arranca** (fase 10) |

Lo que ya trae el sistema (Raspberry Pi OS bookworm): `jalv`, PipeWire 1.2.7 con `pipewire-jack`, `alsa-utils`, `git`, `curl`, `xz-utils`, `python3`, y `console-setup-linux`, que trae la fuente Terminus. Python usa solo la biblioteca estándar.

**Plan.**
1. Un **instalador en la Pi** (`instalar.sh`, ejecutado desde el repositorio clonado). Comprueba las dependencias e indica el `apt install` que falte, sin instalar nada por su cuenta. Después:
   - copia las herramientas;
   - instala sfizz desde el paquete publicado, verificando su SHA-256;
   - instala el comando `piano`;
   - genera los MIDI de prueba;
   - descarga los sonidos.
2. **`descargar-instrumentos.sh` completo**: el Salamander, el Upright KW con `7z` si está disponible, y la generación de las cuerdas.
3. **Softify en la Pi**: un script que lo instala desde el zip copiado a la Pi (Python estándar, `zipfile`), además del de PC.
4. **Pruebas sin archivos manuales**: los MIDI de prueba se generan.
5. **README en los dos idiomas** con esa guía, y la prueba de instalación desde cero.

## Instalador y descargas (2026-10-20)

> «Publicar es al final final, no ahora. Avancemos, incluyendo pruebas.»

**`descargar-instrumentos.sh`, blindado.**
- **Todo fijado** a lo que se midió:
  - los 6 repositorios de GitHub, al commit exacto de las descargas del usuario, sacado de los propios tar.gz con `git get-tar-commit-id` y comprobado dentro de cada archivo descargado;
  - los 5 archivos de FreePats, a su SHA-256.
- **Se añaden el Salamander** (FreePats `.tar.xz`, 412 313 804 bytes) **y el Upright KW** (`.7z`, con `7z` de `p7zip-full`; sin él, se omite con aviso).
- **Después de VSCO 2 se generan las cuerdas** (`generar_cuerdas.py`).
- **Una descarga fallida nunca deja nada a medias**: se extrae en `CARPETA.part` y solo al final reemplaza a la anterior. Un archivo que no cuadra se borra, y uno de GitHub truncado también, para no repetir el fallo; uno de FreePats verificado se conserva, porque el problema sería otro, como el espacio en disco.
- **Reutiliza las descargas existentes**, también las antiguas por rama si llevan el commit fijado: en la Pi del usuario no hay que bajar nada de nuevo.
- Las 5 direcciones se comprobaron (respuesta 200 y tamaños esperados) sin descargar.

**`instalar_softify.py`** instala el Softify en la Pi desde el zip, sin el PC.
- Comprueba que el zip es la versión medida (v1.1, por su SHA-256); `--otra-version` instala otra con aviso.
- Extrae solo SFZ y Readme, rechaza rutas sospechosas, verifica cada archivo y reemplaza al final.
- **Probado con el zip real**: 499 archivos, idénticos a la instalación de la Pi (misma suma de conjunto).
- El script del PC (`tools/instrumentos/preparar-softify.sh`) se mantiene.

**`instalar.sh`** (en `tools/pi`; acceso directo en la raíz del repositorio) hace, en orden:
1. Comprueba los requisitos y la reverb, buscándola donde la busca jalv (`LV2_PATH`). Si falta algo, muestra el `sudo apt install` exacto y **no instala paquetes**.
2. Copia las herramientas a `~/piano/tools`.
3. Instala sfizz desde el paquete publicado: sumas, licencias y **comprobación del parche** con `--helpfull`.
4. Instala el comando `piano`.
5. Genera los MIDI de prueba.
6. Descarga los sonidos (`--sin-sonidos` lo omite).
7. Con `--fuente-consola`, aplica la letra de la consola.

Con `--comprobar` solo informa. Funciona desde el repositorio y desde la copia instalada, para actualizar.
- **Probado con datos reales**: el `--comprobar` del sistema real, y la instalación con el paquete sfizz verdadero en una carpeta temporal (sfizz idéntico al del piano, las mismas 44 herramientas).

**Pruebas sin archivos manuales**: `test_escuchar_midi_integracion.sh` genera sus MIDI (la pieza larga es `01-escala-dinamicas`, de 50 s) en lugar del Satie de Mutopia.

**Defectos encontrados por las pruebas y corregidos:**
- Un tar de GitHub truncado se quedaba guardado y hacía fallar cada nuevo intento.
- Un zip con solo el Readme y Kontakt se «instalaba» como Softify.
- El instalador no reconocía la reverb real. Su manifiesto usa el prefijo `mda:Ambience`, y la prueba usaba la dirección completa; ahora la prueba usa un manifiesto como el real.
- La comprobación del parche usaba `--help`, que en abseil no lista opciones, y una tubería con `grep -q`, que con `pipefail` falla por SIGPIPE cuando la ayuda es larga. Ahora se usa `--helpfull` y se guarda la salida antes de buscar. El sfizz falso de la prueba imita las dos cosas, y una versión con la tubería vieja hace fallar la prueba.

**README (español e inglés, completos)**:
- qué es, qué hace falta, instalación paso a paso, teclas, pruebas, compilación de sfizz, limitaciones conocidas y licencia;
- **cifras medidas**: más de 400 pruebas (236 métodos de Python con 911 aserciones, y unas 187 comprobaciones de integración); unos 5 GB para los sonidos (6 GB con el Softify); unos 2,4 GB de descarga;
- **los comandos de compilación de sfizz se ejecutaron tal como están escritos** y dieron programas idénticos byte a byte a los publicados (compilación reproducible);
- enlaces y anclas comprobados.

## Prueba de instalación desde cero (2026-10-20, en curso)

> «Dejé una SD nueva en mi compu. ¿Me armas la SD de cero?»

**La SD.**
- MicroSD de 58,2 GB en el PC: el disco 4, **confirmado por el usuario** antes de borrarlo. Los discos internos quedaron identificados y no se tocaron.
- **Raspberry Pi OS Lite 64 bits Bookworm** (imagen oficial del 2026-10-06, SHA-256 verificado), grabado con Raspberry Pi Imager (CLI, con permiso de administrador aceptado por el usuario).
- Primer arranque, con la misma estructura que el de Imager:
  - nombre `piano`, usuario `piano`;
  - SSH solo con la clave del PC;
  - el Wi-Fi de la casa con la clave **cifrada** (PSK de 64 hex, calculada en la Pi anterior y nunca mostrada);
  - teclado `es`, y la zona horaria y el país del Wi-Fi del usuario.
- Verificado tras grabar: particiones, imagen «2026-10-06 Lite» y el script de primer arranque idéntico byte a byte. Después se borraron del PC los archivos con datos sensibles.
- **La tarjeta original del usuario quedó guardada aparte, intacta.** Su Pi se apagó de forma ordenada antes del cambio.

**Se siguió solo el README** (el `git clone` se simuló con los 77 archivos que entrarían en el repositorio). Hallazgos:

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | Lite no trae PipeWire, WirePlumber, git ni jalv. El `apt install` del README no bastaba; el instalador lo detectó y dio el comando exacto (`pipewire-bin pipewire-jack wireplumber`) | README: `apt install` completo para Lite |
| 2 | Recién instalado, PipeWire queda habilitado pero **sin arrancar** hasta volver a iniciar sesión: `piano` habría fallado | El instalador (paso 6) arranca PipeWire si no está en marcha y comprueba que se vea la G1 (si no, avisa). El nombre de la tarjeta se lee de `piano-en-vivo.sh`. 6 comprobaciones nuevas con `systemctl`/`pw-link` falsos |
| 3 | El README suponía `~/Downloads`, que no existe sin escritorio | README: descarga con `curl -LO` en la carpeta de inicio |
| 4 | `test_piano_en_vivo_integracion.sh` exigía 23 sonidos publicados, es decir, el Softify instalado, que es opcional | Cuenta los sonidos instalados |
| 5 | jalv instala bibliotecas gráficas (GTK3 y Qt5): incluye sus versiones con ventana. Instalación de 167 s | Solo se anota: no se puede evitar con el paquete de Debian |
| — | La reverb del paquete de Debian queda en `/usr/lib/lv2/mda.lv2` | Ya cubierta por la comprobación del instalador |
| 6 | **La descarga del Salamander se colgó 70 min a 0 KB/s**: `curl` no tenía límite ante una conexión colgada (el usuario: «¿más de 1 hora de descargas?»). Los reintentos internos de `curl`, además, empiezan de cero | `descargar-instrumentos.sh`: si baja de 10 KB/s durante 60 s, corta; **reintentos propios que reanudan** el `.part` (`-C -`). Si el servidor no admite reanudar, el siguiente intento empieza de cero; sin avance dos veces, se descarta el parcial; al agotar los intentos, el parcial se conserva para la próxima ejecución. git (VCSL, VSCO 2): `http.lowSpeedLimit/Time`, reintentos del clon y `reset --hard` al commit fijado, que completa lo que falte. **10 comprobaciones nuevas**: servidor HTTP local que se cuelga, con y sin rangos y siempre colgado, un parcial anterior, y un `git` falso con cortes. Se probó en vivo: el Salamander continuó desde 122 MB |
| 8 | «Para actualizar: `git pull` y `bash instalar.sh`» **reinstalaba los 22 sonidos cada vez**: los extraía de nuevo y volvía a clonar VCSL y VSCO 2, unos 10 min inútiles | `descargar-instrumentos.sh` salta lo ya instalado desde el mismo origen fijado, según el manifiesto y si la carpeta existe; `--forzar` reinstala. **3 comprobaciones nuevas** (38 en total), y las pruebas que verifican la reinstalación la piden con `--forzar`. En la Pi nueva, la actualización tardó **1 s** |
| 10 | **En el sistema Lite el piano no podía funcionar.** Raspberry Pi OS Lite trae `Storage=volatile` en `journald.conf` (el registro solo en memoria, para gastar menos la SD), y así `journalctl --user` no encuentra nada («No journal files were found»). Los scripts leían con él las confirmaciones de sfizz (arranque y cambio de sonido) y los cortes de PipeWire. La validación falló en las dos suites de integración que arrancan sfizz («no terminó de cargar en 180 s») | Todas las lecturas pasan a `journalctl --user-unit=X`, que lee el registro del sistema y funciona en memoria y en disco; la comprobación de caídas usa `_UID`. El instalador comprueba de verdad que el registro se puede leer (servicio de prueba con una marca) y, si no, da el comando (`usermod -aG systemd-journal`). **3 comprobaciones nuevas**: lectura real, registro ilegible simulado y una que impide volver a usar `journalctl --user` |
| 9 | El Wi-Fi USB (RTL8188EUS) rinde 0,75–1,1 MB/s con señal del 100 %; el cable, 8,2 MB/s (enlace 100 Mb/s dúplex completo, 0 errores, 0 % de pérdida) | Solo se anota: no es del proyecto. Con cable, lo que faltaba bajó en minutos |
| 7 | Los servicios de usuario (`systemd-run --user`) **mueren cuando se cierra la última sesión SSH** (sin *linger*): una descarga lanzada así se cortó sin dejar error | La prueba usa `nohup setsid`. README: si se corta la sesión, volver a ejecutar el instalador (las descargas continúan). A tener en cuenta en la fase 11 (arranque automático) |

## Publicación (2026-10-20)

Tras las fases 10 y 11 y con todo probado («al final final»), el usuario aprobó 7 puntos: repositorio público `piano-raspberry-pi`; quitar un dato personal de la fase 01; subirlo sin instalar nada; un solo primer commit; Release v1.0 con sfizz; la foto después; y activar en GitHub «Block command line pushes that expose my email».

**Antes de publicar:**
- **Revisión de datos sensibles:** ninguna contraseña, correo, IP ni ruta del PC. Una mención a un servicio propio del usuario en la fase 01 se dejó genérica. Los README pasaron a tener las direcciones reales (clon y descarga de la Release).
- **Identidad del repositorio:** «Reinaldo Johnson Espinoza» con su correo privado de GitHub (`84028549+TestCeL@…`). La configuración global del PC, con el correo del trabajo, no se tocó.
- **Archivos:** 88; `dist/`, sonidos y registros, fuera. Los scripts, con permiso de ejecución en git (31).

**Subida:**
- El usuario creó el repositorio vacío en github.com. `git push` con el gestor de credenciales que ya trae Git para Windows: no se instaló `gh` ni nada más.
- Verificado desde fuera: el repositorio es público, y el autor y el committer llevan el correo noreply.

**Release v1.0** (creada por el usuario en la web, con el texto preparado en español e inglés):
- adjuntos: `piano-rpi-sfizz-1.2.3-arm64.tar.gz` y su `.sha256`;
- verificado: etiqueta `v1.0`, ni borrador ni preliminar; **la dirección de descarga del README trae el archivo con el SHA-256 original** (`799214ab…`).

**Desde la Pi**, siguiendo el README: `git clone` correcto (con los permisos de ejecución), la descarga de la Release verificada y `instalar.sh --comprobar` sin errores.

**Hallazgo tras publicar:** al cerrar esta documentación apareció en la sección de la SD nueva el **nombre de la red Wi-Fi del usuario** y su zona horaria. Ya estaban en el commit publicado: la revisión anterior buscó contraseñas y correos, pero no nombres de red. Se reemplazaron por texto genérico.

## Pendientes

- [ ] Comprobar si sfizz se puede compilar en la propia Pi 3 (1 GB de RAM); la vía principal es el programa compilado (decisión 3).
- [ ] Foto o captura de la pantalla para el README (mejor una foto del monitor, que el usuario tiene a mano).
- [x] Correo privado exacto de GitHub del usuario (Settings → Emails): `84028549+TestCeL@users.noreply.github.com`. Configurado como identidad local del repositorio el 2026-10-20, antes del primer commit; la configuración global del PC no se tocó.

## Checklist

- [x] Decisiones del usuario registradas (2026-10-20)
- [x] Arranque automático movido a la fase 11 en la documentación de las fases 05–08
- [x] Datos personales fuera (configurables) y revisados
- [x] `dist/` fuera; repositorio git con `.gitignore` y `.gitattributes`
- [x] README (español e inglés), con cifras medidas y comandos comprobados (falta la foto)
- [x] `LICENSE` (MIT) y créditos (español e inglés), generados y con pruebas (`test_generar_creditos.py`, en el validador)
- [x] Créditos al pie del menú F9, con pruebas
- [x] sfizz compilado + avisos de licencia, empaquetado y probado en la Pi
- [x] Validación intermedia (2026-10-20, tras datos personales, créditos en F9, `piano` con `$HOME` instalado en la Pi y la suite de créditos): **16 suites en verde** (60 °C máx., sin bajo voltaje; G1 al 80 %)
- [x] Instalador en la Pi, descargas completas y fijadas (Salamander, Upright, cuerdas), Softify en la Pi, pruebas sin archivos manuales; 3 suites nuevas (descarga 25 comprobaciones, Softify 7, instalador 21)
- [x] Validación completa (2026-10-20): **19 suites en verde** (61 °C máx., sin bajo voltaje; G1 al 80 %)
- [x] Prueba de instalación desde cero en otra microSD: Raspberry Pi OS Lite 64 bits Bookworm, siguiendo solo el README. 10 hallazgos, todos corregidos o anotados. Los 22 sonidos se instalaron, incluido el Softify (idéntico al original). **Validación completa en la Pi nueva: 19 suites en verde** (2026-10-20; 47 °C máx., sin bajo voltaje; G1 al 40 %, su valor de fábrica)
- [x] Prueba del usuario tocando en la Pi nueva (consola, usuario `piano`): en las fases 10 y 11, con sus dos tarjetas, el arranque automático y F12
- [x] ~~Volver a la tarjeta original y actualizarla~~: no aplica. El usuario se queda con la SD nueva (2026-10-20); la original queda guardada intacta
- [x] Instalación desde cero probada siguiendo solo el README (ver arriba) y, ya publicado, el clon y la descarga de la Release desde la Pi
- [x] Validación completa en la Pi: 24/24 (fase 11)
- [x] Publicación en GitHub: https://github.com/TestCeL/piano-raspberry-pi, con la Release v1.0 (2026-10-20)
- [ ] Quitar del historial público el nombre de la red Wi-Fi (decisión del usuario pendiente)
