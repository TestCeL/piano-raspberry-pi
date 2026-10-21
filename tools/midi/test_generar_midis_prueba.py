"""Pruebas del generador de MIDIs: estructura SMF válida, notas balanceadas, pedal y rangos correctos."""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generar_midis_prueba as g  # noqa: E402


def leer_vlq(datos, i):
    valor = 0
    while True:
        b = datos[i]
        i += 1
        valor = (valor << 7) | (b & 0x7F)
        if not b & 0x80:
            return valor, i


def parsear_smf(ruta):
    """Devuelve (cabecera, eventos[(tick, status, d1, d2)], meta[(tick, tipo)])."""
    with open(ruta, "rb") as f:
        datos = f.read()
    assert datos[:4] == b"MThd"
    longitud, formato, pistas, ppq = struct.unpack(">IHHH", datos[4:14])
    assert datos[14:18] == b"MTrk"
    (largo_pista,) = struct.unpack(">I", datos[18:22])
    cuerpo = datos[22:22 + largo_pista]
    assert len(cuerpo) == largo_pista, "longitud de pista inconsistente"
    i, tick, eventos, meta = 0, 0, [], []
    while i < len(cuerpo):
        delta, i = leer_vlq(cuerpo, i)
        tick += delta
        status = cuerpo[i]
        if status == 0xFF:
            tipo, largo = cuerpo[i + 1], cuerpo[i + 2]
            meta.append((tick, tipo))
            i += 3 + largo
        else:
            eventos.append((tick, status, cuerpo[i + 1], cuerpo[i + 2]))
            i += 3
    return (longitud, formato, pistas, ppq), eventos, meta


class TestVLQ(unittest.TestCase):
    def test_valores_conocidos(self):
        # Ejemplos de la especificación SMF
        self.assertEqual(g.vlq(0), b"\x00")
        self.assertEqual(g.vlq(0x40), b"\x40")
        self.assertEqual(g.vlq(0x7F), b"\x7F")
        self.assertEqual(g.vlq(0x80), b"\x81\x00")
        self.assertEqual(g.vlq(0x2000), b"\xC0\x00")
        self.assertEqual(g.vlq(0x3FFF), b"\xFF\x7F")
        self.assertEqual(g.vlq(0x0FFFFFFF), b"\xFF\xFF\xFF\x7F")

    def test_negativo(self):
        with self.assertRaises(ValueError):
            g.vlq(-1)


class TestPista(unittest.TestCase):
    def test_nota_invalida(self):
        p = g.Pista()
        for args in ((128, 64, 10), (60, 0, 10), (60, 128, 10), (60, 64, 0)):
            with self.assertRaises(ValueError):
                p.nota(0, *args)

    def test_orden_noteoff_antes_que_noteon_en_mismo_tick(self):
        p = g.Pista()
        p.nota(0, 60, 100, 480)
        p.nota(480, 60, 100, 480)   # misma nota re-pulsada justo al soltarse
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "x.mid")
            g.escribir_smf(ruta, p)
            _, eventos, _ = parsear_smf(ruta)
        en_480 = [e for e in eventos if e[0] == 480]
        self.assertEqual(en_480[0][1] & 0xF0, 0x80, "el note-off debe ir antes del note-on")
        self.assertEqual(en_480[1][1] & 0xF0, 0x90)


class TestPiezas(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.assertEqual(g.main(["x", self.dir.name]), 0)

    def tearDown(self):
        self.dir.cleanup()

    def test_todas_las_piezas_son_smf_validos_y_balanceados(self):
        for nombre in g.PIEZAS:
            with self.subTest(pieza=nombre):
                (longitud, formato, pistas, ppq), eventos, meta = parsear_smf(
                    os.path.join(self.dir.name, nombre))
                self.assertEqual((longitud, formato, pistas, ppq), (6, 0, 1, g.PPQ))
                self.assertEqual(meta[0], (0, 0x51), "el tempo debe ir al inicio")
                self.assertEqual(meta[-1][1], 0x2F, "debe terminar con End of Track")
                activas = {}
                for tick, status, d1, d2 in eventos:
                    tipo = status & 0xF0
                    self.assertEqual(status & 0x0F, g.CANAL)
                    if tipo == 0x90:
                        self.assertTrue(21 <= d1 <= 108, f"nota fuera del rango del piano: {d1}")
                        self.assertTrue(1 <= d2 <= 127)
                        activas[d1] = activas.get(d1, 0) + 1
                    elif tipo == 0x80:
                        self.assertGreater(activas.get(d1, 0), 0, f"note-off sin note-on: {d1}")
                        activas[d1] -= 1
                    elif tipo == 0xB0:
                        self.assertEqual(d1, g.CC_SUSTAIN)
                        self.assertIn(d2, (0, 127))
                    else:
                        self.fail(f"evento inesperado {status:#x}")
                self.assertTrue(all(v == 0 for v in activas.values()), "quedan notas colgadas")

    def test_pedal_termina_levantado(self):
        for nombre in ("02-acordes-pedal.mid", "03-arpegios-densos.mid"):
            with self.subTest(pieza=nombre):
                _, eventos, _ = parsear_smf(os.path.join(self.dir.name, nombre))
                pedales = [e for e in eventos if e[1] & 0xF0 == 0xB0]
                self.assertTrue(pedales, "la pieza debe usar pedal")
                self.assertEqual(pedales[-1][3], 0, "el pedal debe acabar arriba")

    def test_arpegios_generan_alta_polifonia(self):
        _, eventos, _ = parsear_smf(os.path.join(self.dir.name, "03-arpegios-densos.mid"))
        # Cuerdas sostenidas por el pedal: las teclas que siguen pulsadas cuando baja el pedal
        # más las que se pulsan mientras está abajo (igual que en un piano real).
        max_bajo_pedal, actuales, pulsadas, pedal = 0, set(), set(), False
        for _, status, d1, d2 in eventos:
            tipo = status & 0xF0
            if tipo == 0xB0:
                pedal = d2 >= 64
                actuales = set(pulsadas) if pedal else set()
            elif tipo == 0x90:
                pulsadas.add(d1)
                if pedal:
                    actuales.add(d1)
            elif tipo == 0x80:
                pulsadas.discard(d1)
            max_bajo_pedal = max(max_bajo_pedal, len(actuales))
        self.assertGreaterEqual(max_bajo_pedal, 12)


class TestPruebaPedal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.dir.name, "p.mid")
        g.escribir_smf(self.ruta, g.prueba_pedal())
        _, self.eventos, self.meta = parsear_smf(self.ruta)

    def tearDown(self):
        self.dir.cleanup()

    def segundos(self, tick):
        return tick / g.SEGUNDO

    def test_acorde_sin_pedal_y_con_pedal(self):
        ons = [(self.segundos(t), d1) for t, st, d1, _ in self.eventos if st & 0xF0 == 0x90]
        self.assertEqual(sorted(n for t, n in ons if t < 1), list(g.ACORDE_PEDAL))
        self.assertEqual(sorted(n for t, n in ons if 4 < t < 5), list(g.ACORDE_PEDAL))
        offs = sorted({self.segundos(t) for t, st, *_ in self.eventos if st & 0xF0 == 0x80})
        self.assertEqual(offs, [0.5, 4.6], "ambos acordes se sueltan medio segundo después")

    def test_pedal_abajo_durante_la_segunda_ventana_y_arriba_en_la_primera(self):
        pedales = [(self.segundos(t), d2) for t, st, d1, d2 in self.eventos if st & 0xF0 == 0xB0]
        self.assertTrue(all(cc == g.CC_SUSTAIN for _, st, cc, _ in self.eventos if st & 0xF0 == 0xB0))
        def pedal_en(t):
            v = 0
            for tp, valor in pedales:
                if tp <= t:
                    v = valor
            return v
        sin, con = g.VENTANA_SIN_PEDAL, g.VENTANA_CON_PEDAL
        for t in (sin[0], (sin[0] + sin[1]) / 2, sin[1]):
            self.assertEqual(pedal_en(t), 0)
        for t in (con[0], (con[0] + con[1]) / 2, con[1]):
            self.assertEqual(pedal_en(t), 127)
        self.assertGreater(sin[0], 0.5 + 0.5, "la ventana sin pedal empieza después de la caída inicial")
        self.assertGreater(con[0], 4.6 + 0.5, "la ventana con pedal empieza después de soltar las teclas")
        self.assertEqual(pedales[-1][1], 0, "el pedal termina arriba")

    def test_el_archivo_cubre_las_ventanas(self):
        fin = self.segundos(self.meta[-1][0])
        self.assertGreater(fin, g.VENTANA_CON_PEDAL[1] + 1)


class TestAfinacion(unittest.TestCase):
    def test_un_la4_que_cubre_la_ventana(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "a.mid")
            g.escribir_smf(ruta, g.afinacion())
            _, eventos, meta = parsear_smf(ruta)
        notas = [(t, d1) for t, st, d1, _ in eventos if st & 0xF0 == 0x90]
        self.assertEqual(notas, [(0, g.NOTA_AFINACION)])
        off = next(t for t, st, *_ in eventos if st & 0xF0 == 0x80)
        self.assertGreater(off / g.SEGUNDO, g.VENTANA_AFINACION[1], "la nota sigue pulsada en toda la ventana")
        self.assertEqual(g.FRECUENCIA_AFINACION, 440.0 * 2 ** ((g.NOTA_AFINACION - 69) / 12))


class TestTransponer(unittest.TestCase):
    def test_mueve_las_notas_y_conserva_tiempos(self):
        with tempfile.TemporaryDirectory() as d:
            o, n = os.path.join(d, "o.mid"), os.path.join(d, "n.mid")
            g.escribir_smf(o, g.acordes_pedal())
            with open(o, "rb") as f:
                datos = f.read()
            with open(n, "wb") as f:
                f.write(g.transponer_smf(g.anteponer_controles(datos, [(77, 0)]), 12))
            _, ev_o, meta_o = parsear_smf(o)
            _, ev_n, meta_n = parsear_smf(n)
        self.assertEqual(ev_n[0], (0, 0xB0, 77, 0), "los controles no cambian")
        esperado = [(t, st, d1 + 12 if st & 0xF0 in (0x80, 0x90) else d1, d2) for t, st, d1, d2 in ev_o]
        self.assertEqual(ev_n[1:], esperado)
        self.assertEqual(meta_n, meta_o)

    def test_fuera_de_rango_se_quita_sin_perder_el_tiempo(self):
        p = g.Pista()
        p.nota(0, 120, 80, 100)
        p.nota(200, 60, 80, 100)
        with tempfile.TemporaryDirectory() as d:
            o, n = os.path.join(d, "o.mid"), os.path.join(d, "n.mid")
            g.escribir_smf(o, p)
            with open(o, "rb") as f:
                datos = f.read()
            with open(n, "wb") as f:
                f.write(g.transponer_smf(datos, 12))
            _, ev, _ = parsear_smf(n)
        self.assertEqual([(t, d1) for t, st, d1, _ in ev], [(200, 72), (300, 72)],
                         "la nota 120+12 desaparece y la siguiente conserva su tiempo absoluto")

    def test_cero_y_formato(self):
        self.assertEqual(g.transponer_smf(b"x", 0), b"x")
        with self.assertRaises(ValueError):
            g.transponer_smf(b"no es midi" * 3, 12)


class TestAnteponerControles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_inserta_controles_al_inicio_y_conserva_la_pieza(self):
        original = os.path.join(self.dir.name, "o.mid")
        g.escribir_smf(original, g.acordes_pedal())
        with open(original, "rb") as f:
            datos = f.read()
        nuevo = os.path.join(self.dir.name, "n.mid")
        with open(nuevo, "wb") as f:
            f.write(g.anteponer_controles(datos, [(77, 0), (101, 0)]))
        _, ev_o, meta_o = parsear_smf(original)
        _, ev_n, meta_n = parsear_smf(nuevo)       # valida longitudes y estructura
        self.assertEqual(ev_n[:2], [(0, 0xB0 | g.CANAL, 77, 0), (0, 0xB0 | g.CANAL, 101, 0)])
        self.assertEqual(ev_n[2:], ev_o, "el resto de la pieza no cambia (ni sus tiempos)")
        self.assertEqual(meta_n, meta_o)

    def test_sin_controles_devuelve_lo_mismo(self):
        ruta = os.path.join(self.dir.name, "o.mid")
        g.escribir_smf(ruta, g.prueba_pedal())
        with open(ruta, "rb") as f:
            datos = f.read()
        self.assertEqual(g.anteponer_controles(datos, []), datos)

    def test_rechaza_valores_y_formatos_invalidos(self):
        ruta = os.path.join(self.dir.name, "o.mid")
        g.escribir_smf(ruta, g.prueba_pedal())
        with open(ruta, "rb") as f:
            datos = f.read()
        for malo in ([(128, 0)], [(7, 128)], [(-1, 0)]):
            with self.assertRaises(ValueError):
                g.anteponer_controles(datos, malo)
        with self.assertRaises(ValueError):
            g.anteponer_controles(b"no es midi" * 3, [])
        tipo1 = datos[:8] + struct.pack(">H", 1) + datos[10:]
        with self.assertRaises(ValueError):
            g.anteponer_controles(tipo1, [])


class TestCarga(unittest.TestCase):
    def test_notas_repartidas_extremos_y_distintas(self):
        for n in g.VOCES_CARGA:
            with self.subTest(n=n):
                notas = g.notas_repartidas(n)
                self.assertEqual(len(notas), n)
                self.assertEqual(len(set(notas)), n, "las notas deben ser distintas (una voz cada una)")
                self.assertEqual(notas[0], g.NOTA_GRAVE_CARGA)
                self.assertEqual(notas[-1], g.NOTA_AGUDA_CARGA)
                self.assertEqual(notas, sorted(notas))

    def test_notas_repartidas_limites(self):
        self.assertEqual(g.notas_repartidas(1), [g.NOTA_GRAVE_CARGA])
        with self.assertRaises(ValueError):
            g.notas_repartidas(0)
        with self.assertRaises(ValueError):
            g.notas_repartidas(g.NOTA_AGUDA_CARGA - g.NOTA_GRAVE_CARGA + 2)

    def test_carga_mantiene_n_voces_simultaneas_sin_pedal(self):
        with tempfile.TemporaryDirectory() as d:
            for n in g.VOCES_CARGA:
                with self.subTest(n=n):
                    ruta = os.path.join(d, f"c{n}.mid")
                    g.escribir_smf(ruta, g.carga_voces(n))
                    _, eventos, _ = parsear_smf(ruta)
                    self.assertFalse([e for e in eventos if e[1] & 0xF0 == 0xB0], "sin pedal")
                    activas, maximo, tick_max = set(), 0, None
                    for tick, status, d1, _ in eventos:
                        if status & 0xF0 == 0x90:
                            activas.add(d1)
                        elif status & 0xF0 == 0x80:
                            activas.discard(d1)
                        if len(activas) > maximo:
                            maximo, tick_max = len(activas), tick
                    self.assertEqual(maximo, n)
                    self.assertLess(tick_max, 2 * g.NEGRA, "todas las voces deben entrar en el primer segundo")
                    note_offs = {e[0] for e in eventos if e[1] & 0xF0 == 0x80}
                    self.assertEqual(note_offs, {8 * 2 * g.NEGRA}, "todas se sueltan juntas a los 8 s")

    def test_main_genera_archivos_de_carga(self):
        with tempfile.TemporaryDirectory() as d:
            g.main(["x", d])
            for n in g.VOCES_CARGA:
                self.assertTrue(os.path.isfile(os.path.join(d, f"20-carga-{n:02d}-voces.mid")))
            self.assertTrue(os.path.isfile(os.path.join(d, "04-prueba-pedal.mid")))


if __name__ == "__main__":
    unittest.main()
