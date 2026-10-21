# Créditos

> English: [CREDITS.md](CREDITS.md)

## El proyecto

**Piano Raspberry Pi** convierte una Raspberry Pi 3 en un piano digital autónomo: 22 sonidos seleccionables, menú por
categorías, baja latencia y una interfaz en la consola que se toca con un teclado de computador o un teclado MIDI.

- Creado por **Reinaldo Johnson Espinoza**.
- Desarrollado con la ayuda de **Claude** (Anthropic), un asistente de inteligencia artificial que escribió gran parte
  del código, las pruebas y la documentación siguiendo las ideas, las decisiones y las pruebas de Reinaldo Johnson Espinoza.
- El código y la documentación del proyecto tienen licencia **MIT** ([LICENSE](LICENSE)). Esa licencia no cubre los
  sonidos ni los programas de terceros, que tienen la suya (abajo).

## Programas libres que usa

| Programa | Para qué | Licencia | Sitio |
|---|---|---|---|
| sfizz 1.2.3 | Sintetizador SFZ que hace sonar los instrumentos. El proyecto le aplica dos parches (`tools/build-sfizz/patches/`) y publica el programa compilado con los avisos de licencia de todos sus componentes. | BSD-2-Clause | <https://github.com/sfztools/sfizz> |
| PipeWire, pipewire-jack y WirePlumber | Servidor de audio de baja latencia | MIT | <https://pipewire.org> |
| jalv | Anfitrión LV2 de la reverb | ISC | <https://drobilla.net/software/jalv.html> |
| mda-lv2 (mda Ambience) | Reverb de sala | GPL-3.0-or-later | <https://drobilla.net/software/mda-lv2.html> |
| ALSA (libasound2, alsa-utils) | MIDI: secuenciador y `aplaymidi` | LGPL-2.1 / GPL-2.0 | <https://www.alsa-project.org> |
| Terminus Font | Letra grande de la consola | SIL OFL 1.1 | <https://terminus-font.sourceforge.net> |
| Python 3 | Enrutador MIDI, interfaz y herramientas | PSF | <https://www.python.org> |
| Raspberry Pi OS (Debian 12) | Sistema operativo | Varias, libres | <https://www.raspberrypi.com/software/> |

Los programas del sistema se instalan desde los repositorios de Raspberry Pi OS; el proyecto no los redistribuye, salvo
sfizz compilado, que se publica en las *Releases* con todas sus licencias.

## Sonidos

Las muestras **no están en este repositorio**: cada usuario las descarga de su fuente original
(`tools/pi/descargar-instrumentos.sh`; el Softify, a mano desde Pianobook) y las usa bajo la licencia de su autor. El
nivel, la afinación y el pedal de cada sonido se midieron en este proyecto. En **negrita**, los que tienen alguna
restricción. Si compartes música hecha con un sonido CC BY, cita a su autor.

| Sonido | Categoría | Autor | Licencia | Uso | Fuente |
|---|---|---|---|---|---|
| Salamander (Yamaha C5) | Pianos de cola | Alexander Holm | CC BY 3.0 | libre; citar al autor | <https://sfzinstruments.github.io/pianos/salamander> |
| Headroom (Yamaha C3) | Pianos de cola | Bengt Nilsson (SFZ: kinwie) | CC BY 4.0 | libre; citar al autor | <https://sfzinstruments.github.io/pianos/headroom_piano> |
| Maestro (Yamaha CF-3) | Pianos de cola | Mats Helgesson (SFZ: kinwie) | Libre, con permiso del autor | **gratis; mejor no redistribuir** | <https://sfzinstruments.github.io/pianos/maestro_concert_grand_piano> |
| Splendid (Steinway) | Pianos de cola | Akai (SFZ: kinwie; resonancia y medio pedal: P. Eastman) | Dominio público | libre, sin condiciones | <https://sfzinstruments.github.io/pianos/splendid_grand_piano> |
| Softify (Yamaha S6, suave) | Pianos de cola | Dore Mark (Pianobook) | Pianobook: libre para tu música; no redistribuir las muestras | **no redistribuir las muestras** | <https://www.pianobook.co.uk/packs/softify-piano-vol-1/> |
| Kawai vertical (Upright KW) | Pianos verticales | FreePats (grabación: Gonzalo y Roberto) | CC0 | libre, sin condiciones | <http://freepats.zenvoid.org/Piano/acoustic-grand-piano.html#UprightKW> |
| Osiris (vertical) | Pianos verticales | Karoryfer Samples | CC0 | libre, sin condiciones | <https://github.com/sfzinstruments/Osiris_Piano> |
| Rhodes Mark I (jRhodes3d) | Pianos eléctricos | Jeff Learman | Muestras CC BY-NC 4.0 (uso no comercial); SFZ CC0 | **solo uso no comercial** | <https://github.com/sfzinstruments/jlearman.jRhodes3d> |
| Wurlitzer EP200 | Pianos eléctricos | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 | libre; citar al autor | <https://github.com/sfzinstruments/GregSullivan.E-Pianos> |
| Yamaha CP80 | Pianos eléctricos | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 | libre; citar al autor | <https://github.com/sfzinstruments/GregSullivan.E-Pianos> |
| Hohner Pianet T | Pianos eléctricos | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 | libre; citar al autor | <https://github.com/sfzinstruments/GregSullivan.E-Pianos> |
| Piano FM (Yamaha TX81Z) | Pianos eléctricos | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |
| Hammond (drawbars) | Órganos | FreePats (Roberto), grabado de setBfree | CC0 | libre, sin condiciones | <http://freepats.zenvoid.org/Organ/electric-organ.html> |
| Hammond rock | Órganos | Strix SoundFont Team (FreePats), grabado de setBfree | CC0 | libre, sin condiciones | <http://freepats.zenvoid.org/Organ/electric-organ.html> |
| Hammond percusivo | Órganos | Strix SoundFont Team (FreePats), grabado de setBfree | CC0 | libre, sin condiciones | <http://freepats.zenvoid.org/Organ/electric-organ.html> |
| Órgano de iglesia | Órganos | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |
| Clavecín flamenco | Clavecín | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |
| Cuerdas (ensemble) | Cuerdas | Versilian Studios (VSCO 2 CE); ensemble generado (generar_cuerdas.py) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vsco-community/> |
| Arpa de concierto | Cuerdas | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |
| Vibráfono | Percusión | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |
| Marimba | Percusión | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |
| Saxo tenor | Viento | Versilian Studios (VCSL) | CC0 | libre, sin condiciones | <https://versilian-studios.com/vcsl/> |

## Fuentes consultadas

- **PipeWire**: código fuente de pipewire-jack (versiones 1.2.7, 1.4.9 y la rama principal) y la corrección `f7fdafc2`
  («loop: add method to run a function with the lock»), para diagnosticar y evitar una caída de sfizz.
  <https://gitlab.freedesktop.org/pipewire/pipewire>
- **sfizz**: su código fuente (cliente JACK y sintetizador), base de los parches. <https://github.com/sfztools/sfizz>
- **Formato SFZ** (referencia para el ensemble de cuerdas generado): <https://sfzformat.com>
- **Bibliotecas de sonidos**: las páginas de la tabla de arriba y sus repositorios, VCSL
  (<https://github.com/sgossner/VCSL>) y VSCO 2 CE (<https://github.com/sgossner/VSCO-2-CE>).
- **Alternativas evaluadas** (fases 01–03): Pianoteq (<https://www.modartt.com>), Socalabs Piano
  (<https://github.com/FigBug/Piano>), la conversación de Zynthian sobre pianos por modelado físico
  (<https://discourse.zynthian.org/t/free-and-open-source-digital-waveguide-piano-physical-model/8588>) y los plugins
  mda (<https://drobilla.net/software/mda-lv2.html>).
- **Música de prueba**: Fantaisie-Impromptu, op. 66, de Chopin, del Mutopia Project (<https://www.mutopiaproject.org>);
  solo para las pruebas de escucha, no se incluye.
