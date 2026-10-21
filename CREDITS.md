# Credits

> Español: [CREDITOS.md](CREDITOS.md)

## The project

**Piano Raspberry Pi** turns a Raspberry Pi 3 into a standalone digital piano: 22 selectable sounds, a menu by
category, low latency and a console interface played with a computer keyboard or a MIDI keyboard.

- Created by **Reinaldo Johnson Espinoza**.
- Developed with the help of **Claude** (Anthropic), an artificial intelligence assistant that wrote much of the code,
  tests and documentation following Reinaldo Johnson Espinoza's ideas, decisions and testing.
- The project's code and documentation are licensed under the **MIT** license ([LICENSE](LICENSE)). That license does
  not cover the sounds or the third-party programs, which have their own (below).

## Free software it uses

| Program | Purpose | License | Website |
|---|---|---|---|
| sfizz 1.2.3 | SFZ synthesizer that plays the instruments. The project applies two patches (`tools/build-sfizz/patches/`) and publishes the compiled program with the license notices of all its components. | BSD-2-Clause | <https://github.com/sfztools/sfizz> |
| PipeWire, pipewire-jack and WirePlumber | Low-latency audio server | MIT | <https://pipewire.org> |
| jalv | LV2 host for the reverb | ISC | <https://drobilla.net/software/jalv.html> |
| mda-lv2 (mda Ambience) | Room reverb | GPL-3.0-or-later | <https://drobilla.net/software/mda-lv2.html> |
| ALSA (libasound2, alsa-utils) | MIDI: sequencer and `aplaymidi` | LGPL-2.1 / GPL-2.0 | <https://www.alsa-project.org> |
| Terminus Font | Large console font | SIL OFL 1.1 | <https://terminus-font.sourceforge.net> |
| Python 3 | MIDI router, interface and tools | PSF | <https://www.python.org> |
| Raspberry Pi OS (Debian 12) | Operating system | Various, free | <https://www.raspberrypi.com/software/> |

System programs are installed from the Raspberry Pi OS repositories; the project does not redistribute them, except
the compiled sfizz, published in the *Releases* with all its licenses.

## Sounds

The samples are **not in this repository**: each user downloads them from their original source
(`tools/pi/descargar-instrumentos.sh`; Softify, manually from Pianobook) and uses them under their author's license.
The level, tuning and pedal of each sound were measured in this project. In **bold**, those with a restriction. If
you share music made with a CC BY sound, credit its author.

| Sound | Category | Author | License | Use | Source |
|---|---|---|---|---|---|
| Salamander (Yamaha C5) | Grand pianos | Alexander Holm | CC BY 3.0 | free; credit the author | <https://sfzinstruments.github.io/pianos/salamander> |
| Headroom (Yamaha C3) | Grand pianos | Bengt Nilsson (SFZ: kinwie) | CC BY 4.0 | free; credit the author | <https://sfzinstruments.github.io/pianos/headroom_piano> |
| Maestro (Yamaha CF-3) | Grand pianos | Mats Helgesson (SFZ: kinwie) | Free, with the author's permission | **free of charge; better not redistribute** | <https://sfzinstruments.github.io/pianos/maestro_concert_grand_piano> |
| Splendid (Steinway) | Grand pianos | Akai (SFZ: kinwie; resonance and half pedal: P. Eastman) | Public domain | free, no conditions | <https://sfzinstruments.github.io/pianos/splendid_grand_piano> |
| Softify (Yamaha S6, soft) | Grand pianos | Dore Mark (Pianobook) | Pianobook: free for your music; do not redistribute the samples | **do not redistribute the samples** | <https://www.pianobook.co.uk/packs/softify-piano-vol-1/> |
| Kawai upright (Upright KW) | Upright pianos | FreePats (recording: Gonzalo and Roberto) | CC0 | free, no conditions | <http://freepats.zenvoid.org/Piano/acoustic-grand-piano.html#UprightKW> |
| Osiris (upright) | Upright pianos | Karoryfer Samples | CC0 | free, no conditions | <https://github.com/sfzinstruments/Osiris_Piano> |
| Rhodes Mark I (jRhodes3d) | Electric pianos | Jeff Learman | Samples CC BY-NC 4.0 (non-commercial use); SFZ CC0 | **non-commercial use only** | <https://github.com/sfzinstruments/jlearman.jRhodes3d> |
| Wurlitzer EP200 | Electric pianos | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 | free; credit the author | <https://github.com/sfzinstruments/GregSullivan.E-Pianos> |
| Yamaha CP80 | Electric pianos | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 | free; credit the author | <https://github.com/sfzinstruments/GregSullivan.E-Pianos> |
| Hohner Pianet T | Electric pianos | Greg Sullivan (SFZ: kinwie) | CC BY 3.0 | free; credit the author | <https://github.com/sfzinstruments/GregSullivan.E-Pianos> |
| FM piano (Yamaha TX81Z) | Electric pianos | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |
| Hammond (drawbars) | Organs | FreePats (Roberto), recorded from setBfree | CC0 | free, no conditions | <http://freepats.zenvoid.org/Organ/electric-organ.html> |
| Hammond rock | Organs | Strix SoundFont Team (FreePats), recorded from setBfree | CC0 | free, no conditions | <http://freepats.zenvoid.org/Organ/electric-organ.html> |
| Hammond percussive | Organs | Strix SoundFont Team (FreePats), recorded from setBfree | CC0 | free, no conditions | <http://freepats.zenvoid.org/Organ/electric-organ.html> |
| Church organ | Organs | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |
| Flemish harpsichord | Harpsichord | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |
| Strings (ensemble) | Strings | Versilian Studios (VSCO 2 CE); ensemble generated by this project (generar_cuerdas.py) | CC0 | free, no conditions | <https://versilian-studios.com/vsco-community/> |
| Concert harp | Strings | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |
| Vibraphone | Percussion | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |
| Marimba | Percussion | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |
| Tenor saxophone | Wind | Versilian Studios (VCSL) | CC0 | free, no conditions | <https://versilian-studios.com/vcsl/> |

## Sources consulted

- **PipeWire**: pipewire-jack source code (versions 1.2.7, 1.4.9 and the main branch) and the fix `f7fdafc2`
  ("loop: add method to run a function with the lock"), to diagnose and avoid a sfizz crash.
  <https://gitlab.freedesktop.org/pipewire/pipewire>
- **sfizz**: its source code (JACK client and synthesizer), basis of the patches. <https://github.com/sfztools/sfizz>
- **SFZ format** (reference for the generated string ensemble): <https://sfzformat.com>
- **Sound libraries**: the pages in the table above and their repositories, VCSL
  (<https://github.com/sgossner/VCSL>) and VSCO 2 CE (<https://github.com/sgossner/VSCO-2-CE>).
- **Alternatives evaluated** (phases 01–03): Pianoteq (<https://www.modartt.com>), Socalabs Piano
  (<https://github.com/FigBug/Piano>), the Zynthian discussion on physically modelled pianos
  (<https://discourse.zynthian.org/t/free-and-open-source-digital-waveguide-piano-physical-model/8588>) and the mda
  plugins (<https://drobilla.net/software/mda-lv2.html>).
- **Test music**: Chopin's Fantaisie-Impromptu, op. 66, from the Mutopia Project (<https://www.mutopiaproject.org>);
  only for listening tests, not included.
