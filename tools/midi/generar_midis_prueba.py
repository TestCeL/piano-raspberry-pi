#!/usr/bin/env python3
"""Genera archivos MIDI (SMF tipo 0) para evaluar el piano: timbre, dinámica, pedal y carga de CPU.

Uso: python3 generar_midis_prueba.py DIRECTORIO_SALIDA
Sin dependencias externas.
"""
import os
import struct
import sys

PPQ = 480                 # ticks por negra
TEMPO_US = 500_000        # 120 BPM
CANAL = 0
CC_SUSTAIN = 64


def vlq(valor):
    """Codifica un entero como cantidad de longitud variable (SMF)."""
    if valor < 0:
        raise ValueError("el delta no puede ser negativo")
    datos = [valor & 0x7F]
    valor >>= 7
    while valor:
        datos.append((valor & 0x7F) | 0x80)
        valor >>= 7
    return bytes(reversed(datos))


class Pista:
    """Acumula eventos con tiempo absoluto en ticks y los serializa ordenados."""

    def __init__(self):
        self.eventos = []  # (tick, orden, bytes)

    def nota(self, tick, nota, vel, dur):
        if not (0 <= nota <= 127 and 1 <= vel <= 127 and dur > 0):
            raise ValueError(f"nota inválida: {nota} vel={vel} dur={dur}")
        self.eventos.append((tick, 1, bytes([0x90 | CANAL, nota, vel])))
        self.eventos.append((tick + dur, 0, bytes([0x80 | CANAL, nota, 0])))

    def pedal(self, tick, abajo):
        self.eventos.append((tick, 0 if not abajo else 2,
                             bytes([0xB0 | CANAL, CC_SUSTAIN, 127 if abajo else 0])))

    def serializar(self):
        cuerpo = bytearray()
        cuerpo += vlq(0) + b"\xFF\x51\x03" + TEMPO_US.to_bytes(3, "big")
        ultimo = 0
        # A igual tick: note-off y pedal arriba primero, luego note-on, luego pedal abajo
        for tick, _, ev in sorted(self.eventos, key=lambda e: (e[0], e[1])):
            cuerpo += vlq(tick - ultimo) + ev
            ultimo = tick
        cuerpo += vlq(PPQ) + b"\xFF\x2F\x00"
        return bytes(cuerpo)


def escribir_smf(ruta, pista):
    cuerpo = pista.serializar()
    with open(ruta, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ))
        f.write(b"MTrk" + struct.pack(">I", len(cuerpo)) + cuerpo)


NEGRA = PPQ
BLANCA = 2 * PPQ
REDONDA = 4 * PPQ
SEGUNDO = 2 * NEGRA       # a 120 BPM


def escala_dinamicas():
    """Escala de do mayor C2..C7 con velocidad creciente y notas aisladas para oír el decaimiento."""
    p = Pista()
    t = 0
    grados = [0, 2, 4, 5, 7, 9, 11]
    notas = [36 + 12 * o + g for o in range(5) for g in grados] + [96]
    for i, n in enumerate(notas):
        vel = 20 + round(100 * i / (len(notas) - 1))
        p.nota(t, n, vel, NEGRA // 2)
        t += NEGRA // 2
    t += REDONDA
    for vel in (25, 50, 80, 110, 127):          # pp, p, mf, f, ff sobre C4
        p.nota(t, 60, vel, 3 * BLANCA)
        t += 4 * BLANCA
    for n in (24, 36, 84, 96, 108):              # graves y agudos extremos
        p.nota(t, n, 90, 3 * BLANCA)
        t += 4 * BLANCA
    return p


def acordes_pedal():
    """Progresión I–vi–IV–V–I con cambio de pedal sincopado (técnica legato)."""
    p = Pista()
    acordes = [
        (36, [60, 64, 67, 72]),
        (33, [57, 60, 64, 69]),
        (29, [57, 60, 65, 69]),
        (31, [55, 59, 62, 67]),
        (36, [55, 60, 64, 72]),
    ]
    t = 0
    for vuelta, vel in enumerate((60, 95)):
        for bajo, notas in acordes:
            p.pedal(t, False)
            p.nota(t, bajo, vel + 10, BLANCA)
            p.nota(t, bajo + 12, vel, BLANCA)
            for n in notas:
                p.nota(t, n, vel, BLANCA)
            p.pedal(t + NEGRA // 4, True)
            t += REDONDA
    p.pedal(t, False)
    p.pedal(t + REDONDA, False)
    return p


def arpegios_densos():
    """Arpegios de 4 octavas con pedal mantenido por compás: muchas cuerdas resonando a la vez (prueba de carga)."""
    p = Pista()
    acordes = [
        [36, 43, 48, 52, 55, 60, 64, 67, 72, 76, 79, 84],
        [33, 40, 45, 48, 52, 57, 60, 64, 69, 72, 76, 81],
        [29, 36, 41, 45, 48, 53, 57, 60, 65, 69, 72, 77],
        [31, 38, 43, 47, 50, 55, 59, 62, 67, 71, 74, 79],
    ]
    semicorchea = NEGRA // 4
    t = 0
    for _ in range(2):
        for notas in acordes:
            p.pedal(t, False)
            p.pedal(t + semicorchea // 2, True)
            subida = notas + list(reversed(notas[1:-1]))
            for i, n in enumerate(subida):
                vel = 55 + (i % 6) * 8
                p.nota(t + i * semicorchea, n, vel, semicorchea * 2)
            t += len(subida) * semicorchea
    p.pedal(t, False)
    p.nota(t, 36, 100, REDONDA)
    p.nota(t, 48, 100, REDONDA)
    p.nota(t, 60, 100, REDONDA)
    p.pedal(t + REDONDA + BLANCA, False)
    return p


# Ventanas de medición (s) de 04-prueba-pedal: la cola del acorde ya soltado, sin pedal y con pedal.
VENTANA_SIN_PEDAL = (1.5, 3.5)
VENTANA_CON_PEDAL = (5.5, 7.5)
ACORDE_PEDAL = (48, 52, 55, 60)


def prueba_pedal():
    """El mismo acorde dos veces, soltado a los 0,5 s: primero sin pedal (0 s) y después con el pedal abajo
    (4 s). Con pedal debe seguir sonando hasta que el pedal sube (8 s). Comprueba que un instrumento
    responde al CC64 (algunos SFZ lo redirigen para el medio pedal)."""
    p = Pista()
    for n in ACORDE_PEDAL:
        p.nota(0, n, 80, SEGUNDO // 2)
    p.pedal(4 * SEGUNDO, True)
    inicio = 4 * SEGUNDO + SEGUNDO // 10
    for n in ACORDE_PEDAL:
        p.nota(inicio, n, 80, SEGUNDO // 2)
    p.pedal(8 * SEGUNDO, False)
    p.pedal(10 * SEGUNDO, False)        # alarga el archivo: la cola final queda dentro de la medición
    return p


NOTA_AFINACION = 69          # La4
FRECUENCIA_AFINACION = 440.0
VENTANA_AFINACION = (0.4, 1.4)   # s: tramo ya estable de la nota (sin el ataque)


def afinacion():
    """Un La4 de 2 s a fuerza media: comprueba que el instrumento está afinado y en su octava."""
    p = Pista()
    p.nota(0, NOTA_AFINACION, 80, 2 * SEGUNDO)
    p.pedal(3 * SEGUNDO, False)          # alarga el archivo: cola incluida
    return p


def anteponer_controles(smf, controles, canal=CANAL):
    """Devuelve una copia de un SMF tipo 0 con eventos de control (CC, valor) al inicio de la pista (tick 0).
    Sirve para aplicar los controles iniciales de un instrumento (p. ej. apagar un micrófono) a una pieza."""
    if smf[:4] != b"MThd" or smf[14:18] != b"MTrk":
        raise ValueError("no es un SMF de una sola pista")
    if struct.unpack(">H", smf[8:10])[0] != 0:
        raise ValueError("solo SMF tipo 0")
    extra = bytearray()
    for cc, valor in controles:
        if not (0 <= cc <= 127 and 0 <= valor <= 127):
            raise ValueError(f"control inválido: {cc}={valor}")
        extra += vlq(0) + bytes([0xB0 | canal, cc, valor])
    largo = struct.unpack(">I", smf[18:22])[0]
    cuerpo = bytes(extra) + smf[22:22 + largo]
    return smf[:18] + struct.pack(">I", len(cuerpo)) + cuerpo + smf[22 + largo:]


def transponer_smf(smf, semitonos):
    """Copia de un SMF tipo 0 (como los que genera este módulo) con las notas movidas `semitonos`. Las que se
    salen de 0..127 se quitan (su tiempo pasa al evento siguiente)."""
    if not semitonos:
        return smf
    if smf[:4] != b"MThd" or smf[14:18] != b"MTrk" or struct.unpack(">H", smf[8:10])[0] != 0:
        raise ValueError("solo SMF tipo 0 de una pista")
    largo = struct.unpack(">I", smf[18:22])[0]
    datos, i, nuevo, pendiente = smf[22:22 + largo], 0, bytearray(), 0
    while i < len(datos):
        delta = 0
        while True:
            b = datos[i]
            i += 1
            delta = (delta << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        status = datos[i]
        if status == 0xFF:
            n = 3 + datos[i + 2]
            evento = datos[i:i + n]
        elif status & 0xF0 in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
            evento = bytes(datos[i:i + 3])
            n = 3
            if status & 0xF0 in (0x80, 0x90):
                nota = evento[1] + semitonos
                if not 0 <= nota <= 127:
                    pendiente += delta
                    i += n
                    continue
                evento = bytes([status, nota, evento[2]])
        else:
            raise ValueError(f"evento no admitido: {status:#x}")
        nuevo += vlq(delta + pendiente) + evento
        pendiente = 0
        i += n
    return smf[:18] + struct.pack(">I", len(nuevo)) + bytes(nuevo) + smf[22 + largo:]


VOCES_CARGA = (4, 8, 12, 16, 24, 32)
NOTA_GRAVE_CARGA = 28
NOTA_AGUDA_CARGA = 100


def notas_repartidas(n, grave=NOTA_GRAVE_CARGA, aguda=NOTA_AGUDA_CARGA):
    """n notas MIDI distintas repartidas uniformemente entre grave y aguda (incluidas)."""
    if not 1 <= n <= aguda - grave + 1:
        raise ValueError(f"no caben {n} notas distintas entre {grave} y {aguda}")
    if n == 1:
        return [grave]
    return [grave + round(i * (aguda - grave) / (n - 1)) for i in range(n)]


def carga_voces(n, segundos_sostenido=8):
    """n notas distintas pulsadas en 1 s y sostenidas con la tecla (sin pedal): n voces simultáneas."""
    p = Pista()
    paso = NEGRA * 2 // n          # todas las notas entran en 1 s (2 negras a 120 BPM)
    duracion = segundos_sostenido * 2 * NEGRA
    for i, nota in enumerate(notas_repartidas(n)):
        p.nota(i * paso, nota, 80, duracion - i * paso)
    return p


PIEZAS = {
    "01-escala-dinamicas.mid": escala_dinamicas,
    "02-acordes-pedal.mid": acordes_pedal,
    "03-arpegios-densos.mid": arpegios_densos,
    "04-prueba-pedal.mid": prueba_pedal,
    "05-afinacion.mid": afinacion,
}
PIEZAS.update({
    f"20-carga-{n:02d}-voces.mid": (lambda n=n: carga_voces(n)) for n in VOCES_CARGA
})


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    salida = argv[1]
    os.makedirs(salida, exist_ok=True)
    for nombre, generador in PIEZAS.items():
        ruta = os.path.join(salida, nombre)
        escribir_smf(ruta, generador())
        print(ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
