# Piano Raspberry Pi

> English: [README.en.md](README.en.md)

Convierte una **Raspberry Pi 3** en un **piano digital autónomo**:
- **22 sonidos**: pianos de cola, verticales y eléctricos, órganos, clavecín, cuerdas, arpa, percusión y saxo;
- **menú por categorías** (F9) con búsqueda;
- **baja latencia**, reverb de sala e interfaz a pantalla completa en la consola;
- **se toca con un teclado de computador** (hasta 8 teclas a la vez) **o con un teclado MIDI**.

Creado por **Reinaldo Johnson Espinoza**, con la ayuda de **Claude** (Anthropic). Créditos completos: [CREDITOS.md](CREDITOS.md).

<!-- Captura de pantalla: pendiente -->

## Qué incluye

- **Sonidos libres** de sus autores originales (Salamander, Splendid, Rhodes, Wurlitzer, Hammond, VCSL, VSCO 2 y otros), con el nivel, la afinación y el pedal **medidos** para que todos suenen parejos.
- **Cambio de sonido en caliente**:
  - F6/F7 recorre los sonidos uno a uno, y F9 abre el menú por categorías;
  - mientras carga, una ventana con barra de progreso pausa el piano, para que no se cuelgue por seguir tocando.
- **Tarjeta de sonido a elección (F10)**, cambiable en caliente y con el volumen recordado por tarjeta (la primera vez, como mucho al 40 %, para no sorprender con un audífono). Si se desconecta mientras suena, no se cae nada: avisa y vuelve sola al reconectarla.
- **Créditos visibles** de cada sonido (autor, licencia y condiciones de uso) en la pantalla y en el menú.
- **Controles en pantalla**: volumen, reverb, transposición, curva de fuerza, latencia, entradas MIDI y un contador de cortes de audio.
- **Más de 400 pruebas automáticas** (`ejecutar-pruebas.sh`), entre ellas pruebas reales de audio en silencio.

## Qué necesitas

| | |
|---|---|
| Computador | **Raspberry Pi 3 Model B** (1 GB) con **Raspberry Pi OS de 64 bits (Bookworm)**, Lite (sin escritorio, la recomendada y probada desde cero) o con escritorio |
| Alimentación | La **fuente oficial de 5,1 V / 2,5 A**: con fuentes débiles hay bajo voltaje y cortes |
| Tarjeta de sonido | **Cualquier tarjeta de sonido USB** (probado con la Sound BlasterX G1 y el audífono Logitech G432). También sirven la salida de auriculares de la Pi y el HDMI, con menos calidad. Se elige con **F10** |
| Teclado | Un teclado USB de computador; opcionalmente, un teclado MIDI USB |
| Pantalla | Monitor HDMI (pensado para 1080p) |
| Recomendado | Ventilación: con la carga del piano, la Pi 3 se calienta |
| Espacio | Unos **5 GB** libres para los sonidos (6 GB con el Softify) |

## Instalación

Todo se hace **en la Raspberry Pi** (directamente o por SSH).

1. **Programas necesarios**. La versión Lite no trae PipeWire ni git; la de escritorio ya trae parte. El instalador comprueba todo y dice qué falta.
   ```bash
   sudo apt update
   sudo apt install git jalv mda-lv2 p7zip-full pipewire-bin pipewire-jack wireplumber
   ```
2. **Descargar el proyecto**:
   ```bash
   cd ~
   git clone https://github.com/TestCeL/piano-raspberry-pi.git piano-raspberry-pi
   ```
3. **Descargar sfizz ya compilado**: el archivo `piano-rpi-sfizz-1.2.3-arm64.tar.gz` de la sección *Releases* de este repositorio. Es el sintetizador, con los parches del proyecto y sus licencias. En la Pi, sin navegador:
   ```bash
   cd ~
   curl -LO https://github.com/TestCeL/piano-raspberry-pi/releases/download/v1.0/piano-rpi-sfizz-1.2.3-arm64.tar.gz
   ```
   Para compilarlo tú, ver [Compilar sfizz](#compilar-sfizz).
4. **Instalar**:
   ```bash
   cd ~/piano-raspberry-pi
   bash instalar.sh --sfizz ~/piano-rpi-sfizz-1.2.3-arm64.tar.gz
   ```
   - Copia las herramientas a `~/piano`, instala sfizz (comprobando sus sumas) y el comando `piano`.
   - Arranca PipeWire si acabas de instalarlo y muestra las tarjetas de sonido USB a la vista.
   - Descarga y **verifica** los sonidos (unos 2,4 GB; tarda). Si se corta la conexión, la red o la sesión SSH, vuelve a ejecutar la misma orden: **las descargas continúan donde quedaron**.
   - Con `--fuente-consola`, además pone una letra grande en la consola, adecuada para 1080p (se puede revertir con `bash ~/piano/tools/fuente-consola.sh revertir`).
   - Con `--arranque-automatico`, **el piano se abre solo al encender la Pi**, en la pantalla y sin escribir nada (unos 40 s en una Pi 3). La consola inicia sesión sola, porque el sonido funciona dentro de la sesión de un usuario. Nunca se abre por SSH. Al salir con ESC queda la consola: `piano` lo vuelve a abrir y `sudo poweroff` apaga. Se quita con `bash ~/piano/tools/arranque-automatico.sh quitar`.
   - Con `--comprobar`, solo revisa los requisitos.
5. **Softify (opcional)**: su licencia no permite redistribuirlo, así que se descarga a mano.
   - Crea una cuenta gratuita en [Pianobook](https://www.pianobook.co.uk/packs/softify-piano-vol-1/) y descarga el zip.
   - Cópialo a la Pi y ejecuta:
     ```bash
     python3 ~/piano/tools/instalar_softify.py "Softify Piano Vol 1 v1.1.zip"
     ```

Para **actualizar**, ejecuta `git pull` y vuelve a ejecutar `bash instalar.sh`. Sin `--sfizz` se conserva el sfizz instalado, y las preferencias no se tocan.

## Uso

```bash
piano            # abre el piano con el último sonido elegido; ESC para salir
piano -q 256     # con otra latencia (también se cambia con F4)
```

| Tecla | Acción |
|---|---|
| A S D F G H J K L Ñ { | Notas (teclas blancas) |
| W E · T Y U · O P | Sostenidos (teclas negras) |
| Z / X | Octava abajo / arriba |
| C / V | Fuerza menos / más |
| ESPACIO | Pedal (mantener) |
| F6 / F7 | Sonido anterior / siguiente |
| F9 | Menú de sonidos por categoría (←/→ categoría, ↑/↓ elegir, ENTER cargar, letras para buscar) |
| F10 | Tarjeta de sonido (↑/↓ elegir, ENTER usar) |
| ↑ / ↓ | Volumen |
| → / ← | Reverb |
| F1 / F2 | Transposición |
| F3 | Curva de fuerza: suave / normal / dura |
| F4 | Latencia: 128 / 256 / 512 / 1024 (recomendado 256 o 512) |
| TAB / ENTER | Elegir y activar las entradas MIDI |
| F5 | Conectar solas las entradas nuevas: sí / no |
| RETROCESO | Silencio (corta todas las notas) |
| ESC | Salir |
| F12 | Apagar la Raspberry Pi (pregunta: S sí, N no). Desenchúfala cuando se apague la luz verde |

Mientras carga se ve una **pantalla de inicio** al estilo de los juegos de DOS: el título en letras de bloques, un teclado dibujado y una barra de progreso por etapas (tarjeta de sonido, sonido, reverb, teclado). La barra estima cada sonido por lo que tardó la vez anterior.

Las teclas funcionan por **posición física**, así que sirve cualquier distribución de teclado. El piano guarda tus preferencias (sonido, latencia, reverb…) en `~/.config/piano/preferencias.json`.

## Pruebas

```bash
bash ~/piano/tools/ejecutar-pruebas.sh
```

Todo se prueba **en silencio**: nunca suena por la tarjeta. Si el piano está abierto, no se ejecutan, porque lo detendrían.

## Compilar sfizz

En un PC con Docker y emulación arm64 (QEMU/binfmt; Docker Desktop la trae). Desde la carpeta del repositorio:

```bash
docker build --platform linux/arm64 --build-arg PLATAFORMA=linux/arm64 -t sfizz-builder:bookworm-arm64 tools/build-sfizz
docker volume create sfizz-work-arm64
docker run --rm --platform linux/arm64 -v sfizz-work-arm64:/work -v "$PWD/dist/sfizz-1.2.3-arm64:/out" sfizz-builder:bookworm-arm64
```

- Descarga el código oficial de sfizz 1.2.3 (verifica su SHA-256), aplica los parches de [`tools/build-sfizz/patches/`](tools/build-sfizz/patches/README.md) y deja `sfizz_jack`, `sfizz_render`, `BUILDINFO` y `SHA256SUMS` en `dist/sfizz-1.2.3-arm64/`.
- La primera vez tarda bastante, porque compila emulando arm64.
- El resultado es **reproducible**: da exactamente los mismos programas que el paquete publicado.
- En Git Bash de Windows, antepón `MSYS_NO_PATHCONV=1` y usa una ruta de Windows en `-v`.
- El paquete para publicar se arma con `bash tools/build-sfizz/empaquetar-publicacion.sh`.

## Limitaciones conocidas

- **Tarjeta de sonido**: el piano trabaja a 44,1 kHz; con una tarjeta que no lo admita usa 48 kHz, pero pasar a ella en caliente no es posible: se usa al volver a abrir el piano.
- **Teclado MIDI**: está soportado, pero aún no se ha probado con un teclado MIDI real.
- **PipeWire 1.2.7** tiene un error que puede hacer caer un cliente de audio cuando una salida pierde su último enlace. El proyecto lo evita: conecta antes de cortar, y la reverb siempre tiene enlazada un «ancla». Está corregido en PipeWire 1.6.
- **WirePlumber 0.4.13** (el de Debian 12) cae si una tarjeta se desenchufa durante los 5 s que espera antes de suspenderla. El piano la suspende en cuanto la deja (al cambiar con F10 y al cerrarse). Si WirePlumber se reinicia de todos modos, el piano rehace solo sus enlaces en unos segundos. La versión 0.4.17 ya lo corrige.
- **Raspberry Pi 3**: hasta 32 voces por sonido; con latencia 128 pueden aparecer cortes.
- **Arranque automático**: si está activado, cualquiera con el teclado de la Pi tiene una sesión abierta (con `sudo`). En casa no suele importar; si te importa, no lo actives.

## Documentación

El desarrollo está documentado por fases, en español, en [`docs/`](docs/): objetivos, decisiones, mediciones, pruebas y problemas resueltos.

## Licencia

El código y la documentación del proyecto tienen licencia **MIT** ([LICENSE](LICENSE)). Los **sonidos no están incluidos**: cada uno se descarga de su fuente y tiene su propia licencia. Las de los sonidos y las de los programas de terceros están en [CREDITOS.md](CREDITOS.md).
