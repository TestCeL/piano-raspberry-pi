"""Pruebas de pantalla_inicio.py (fase 11): lectura del progreso, etapas, barra, composición en cada tamaño y la
pantalla real en una pseudoterminal (solo en Linux)."""
import os
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pantalla_inicio as pi  # noqa: E402
import teclado_piano as tp  # noqa: E402

ES_LINUX = sys.platform.startswith("linux")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "glifos_consola.txt")) as _f:
    GLIFOS = {chr(int(c, 16)) for c in _f.read().split()} | {" "}
G1 = "alsa_output.usb-Creative_Technology_Ltd_Sound_BlasterX_G1_00030790-00.analog-stereo"


def ev(*lineas):
    return pi.leer_progreso("\n".join("\t".join(str(x) for x in l) for l in lineas))


NOMBRES = {"osiris": "Osiris (vertical)"}


def resumir(eventos, ahora):
    return pi.resumen(eventos, ahora, nombre_salida=lambda n: "Sound BlasterX G1" if n == G1 else n,
                      nombre_sonido=lambda i: NOMBRES.get(i, i), estimado=lambda i: 12.0)


class TestProgreso(unittest.TestCase):
    def test_leer_progreso(self):
        texto = f"100.5\tinicio\n101.0\tsalida\t{G1}\t44100\nbasura\n102\t\n103.25\tsonido\tosiris\n104\tlist"
        self.assertEqual(pi.leer_progreso(texto), [(100.5, "inicio", []), (101.0, "salida", [G1, "44100"]),
                                                   (103.25, "sonido", ["osiris"]), (104.0, "list", [])],
                         "las líneas mal formadas (o vacías) se ignoran; una a medio escribir no rompe nada")
        self.assertEqual(pi.leer_progreso(""), [])

    def test_antes_de_empezar(self):
        r = resumir([], 0)
        self.assertEqual((r["fraccion"], r["mensaje"], r["listo"]), (0.0, "Encendiendo...", False))
        self.assertEqual([e for _, e, _ in r["etapas"]], ["pendiente"] * 4)

    def test_esperando_la_tarjeta_al_encender(self):
        r = resumir(ev((10, "tarjeta", "esperando")), 15)
        self.assertEqual(r["mensaje"], "Esperando la tarjeta de sonido...")
        self.assertEqual(r["etapas"][0], ("Tarjeta de sonido", "actual", "esperando..."))
        self.assertEqual(r["fraccion"], 0.0, "la espera de la tarjeta no avanza la barra (no se sabe cuánto dura)")

    def test_cargando_el_sonido(self):
        e = ev((10, "tarjeta", "esperando"), (13, "tarjeta", "lista", "Sound BlasterX G1"), (13.1, "inicio"),
               (13.3, "salida", G1, 44100), (13.5, "sonido", "osiris"))
        r = resumir(e, 19.5)
        self.assertEqual(r["mensaje"], "Cargando el sonido: Osiris (vertical)...")
        self.assertEqual(r["etapas"], [("Tarjeta de sonido", "hecha", "Sound BlasterX G1"),
                                       ("Sonido", "actual", "Osiris (vertical)"),
                                       ("Reverb de sala", "pendiente", ""), ("Teclado y MIDI", "pendiente", "")])
        # preparar (1) hecho + 6 de 12 s del sonido: (1 + 6) / (1 + 12 + 3,5 + 1) = 0,4
        self.assertAlmostEqual(r["fraccion"], 7 / 17.5, places=3)

    def test_la_barra_nunca_llega_al_100_sin_listo(self):
        e = ev((0, "inicio"), (0, "sonido", "osiris"))
        r = resumir(e, 500)
        self.assertLess(r["fraccion"], 1.0, "un sonido que tarda más de lo previsto no llena la barra")
        r2 = resumir(e + ev((5, "reverb"), (8, "enrutador")), 8.5)
        self.assertGreater(r2["fraccion"], r["fraccion"] - 0.5)
        self.assertEqual(r2["mensaje"], "Conectando el teclado...")
        self.assertEqual([x for _, x, _ in r2["etapas"]], ["hecha", "hecha", "hecha", "actual"])

    def test_listo(self):
        e = ev((0, "inicio"), (0.2, "salida", G1, 44100), (0.3, "sonido", "osiris"), (12, "reverb"),
               (15.5, "enrutador"), (16.3, "listo"))
        r = resumir(e, 16.4)
        self.assertEqual((r["fraccion"], r["mensaje"], r["listo"]), (1.0, "¡Listo para tocar!", True))
        self.assertEqual([x for _, x, _ in r["etapas"]], ["hecha"] * 4)

    def test_modo_silencio_y_tarjeta_que_no_llego(self):
        r = resumir(ev((0, "tarjeta", "no", 20), (20, "inicio"), (20.1, "salida", "", 44100)), 20.2)
        self.assertEqual(r["etapas"][0], ("Tarjeta de sonido", "hecha", "ninguna (modo silencio)"))
        r2 = resumir(ev((0, "tarjeta", "no", 20)), 20)
        self.assertEqual(r2["etapas"][0][1], "actual", "sin tarjeta preferida, sigue hasta que el motor elige otra")

    def test_estimados_y_nombres_desde_el_catalogo(self):
        d = tempfile.mkdtemp()
        prefs = os.path.join(d, "p.json")
        with open(prefs, "w") as f:
            f.write('{"tiempos_carga": {"osiris": 11.81, "malo": true}}')
        viejo = os.environ.get("PIANO_PREFERENCIAS")
        os.environ["PIANO_PREFERENCIAS"] = prefs
        try:
            nombre, estimado = pi.nombres_y_estimados()
        finally:
            if viejo is None:
                os.environ.pop("PIANO_PREFERENCIAS")
            else:
                os.environ["PIANO_PREFERENCIAS"] = viejo
        self.assertEqual(estimado("osiris"), 11.81, "lo que tardó la última vez")
        self.assertEqual(nombre("no-existe"), "no-existe")
        self.assertEqual(estimado("no-existe"), pi.ESTIMADO_SONIDO_DEFECTO)
        self.assertNotEqual(nombre("osiris"), "osiris", "del catálogo, el nombre visible")


class TestComposicion(unittest.TestCase):
    def r(self):
        e = ev((0, "inicio"), (0.2, "salida", G1, 44100), (0.3, "sonido", "osiris"))
        return resumir(e, 6.3)

    def textos(self, salida):
        return "\n".join(t for _, _, t, _ in salida)

    def comprobar_dentro(self, salida, ancho, alto):
        for y, x, texto, _ in salida:
            self.assertTrue(0 <= y < alto and 0 <= x and x + len(texto) <= ancho, (y, x, texto))
            self.assertFalse({ch for ch in texto if ch not in GLIFOS}, texto)

    def test_pantalla_completa_en_el_monitor(self):
        salida = pi.componer(120, 33, self.r())
        self.comprobar_dentro(salida, 120, 33)
        t = self.textos(salida)
        for fragmento in ("╔", "╝", "R A S P B E R R Y   P I", "Cargando el sonido: Osiris (vertical)...", "█",
                          "░", "■ Tarjeta de sonido", "Sound BlasterX G1", "→ Sonido", "· Reverb de sala",
                          tp.CREDITO_PROYECTO, "│  │"):
            self.assertIn(fragmento, t)
        self.assertEqual(len([1 for _, _, _, e in salida if e == "titulo"]), 5, "el título en 5 filas de bloques")
        self.assertTrue(any(e == "negra" for _, _, _, e in salida), "un teclado dibujado, con teclas negras")

    def test_tamanos_mas_chicos(self):
        for ancho, alto in ((80, 24), (60, 16), (40, 10)):
            salida = pi.componer(ancho, alto, self.r())
            self.comprobar_dentro(salida, ancho, alto)
            t = self.textos(salida)
            self.assertIn("PIANO RASPBERRY PI", t, f"{ancho}x{alto}: compacta, sin letras de bloques")
            self.assertIn("Cargando el sonido", t)
        minima = pi.componer(20, 5, self.r())
        self.assertEqual(len(minima), 1, "ventana diminuta: una línea")
        self.comprobar_dentro(minima, 20, 5)

    def test_titulo_y_teclado(self):
        filas = pi.titulo_bloques()
        self.assertEqual(len(filas), 5)
        self.assertEqual(len({len(f) for f in filas}), 1, "todas las filas del mismo ancho")
        dibujo = pi.teclado_dibujo()
        self.assertEqual(len(dibujo), 4)
        negras = [x for x, _, e in dibujo[0] if e == "negra"]
        self.assertEqual(len(negras), 10, "dos octavas: 10 teclas negras")
        self.assertEqual(sum(1 for segs in dibujo[2:] for _, _, e in segs if e == "negra"), 0,
                         "abajo, solo las blancas")


@unittest.skipUnless(ES_LINUX, "curses en pseudoterminal")
class TestPantallaReal(unittest.TestCase):
    """La pantalla de verdad en una pseudoterminal: dibuja, termina sola con «listo» y con SIGTERM."""

    def correr(self, lineas_progreso, maximo=10, sigterm_tras=None):
        import fcntl
        import pty
        import signal
        import termios
        d = tempfile.mkdtemp()
        progreso = os.path.join(d, "progreso")
        with open(progreso, "w") as f:
            f.write("".join("\t".join(str(x) for x in l) + "\n" for l in lineas_progreso))
        pid, maestro = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 33, 120, 0, 0))
                os.environ["TERM"] = "xterm"
                os._exit(pi.main(["--progreso", progreso, "--listo", os.path.join(d, "no-hay"),
                                  "--maximo", str(maximo)]))
            except SystemExit as e:
                os._exit(e.code or 0)
            except Exception as e:   # noqa: BLE001
                os.write(2, repr(e).encode())
                os._exit(3)
        import select
        t0 = time.monotonic()
        salida, enviado = b"", False
        while True:
            if sigterm_tras is not None and not enviado and time.monotonic() - t0 > sigterm_tras:
                os.kill(pid, signal.SIGTERM)
                enviado = True
            # Sin cambios en pantalla, curses no escribe nada: se espera con plazo para poder enviar la señal a tiempo
            if not select.select([maestro], [], [], 0.1)[0]:
                continue
            try:
                bloque = os.read(maestro, 65536)
            except OSError:
                break
            if not bloque:
                break
            salida += bloque
        _, estado = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(estado), salida.decode("utf-8", "replace"), time.monotonic() - t0

    def test_dibuja_y_termina_sola_al_estar_listo(self):
        ahora = time.time()
        codigo, texto, dur = self.correr([(ahora, "inicio"), (ahora, "salida", G1, 44100), (ahora, "sonido", "osiris"),
                                          (ahora, "reverb"), (ahora, "enrutador"), (ahora, "listo")])
        self.assertEqual(codigo, 0, texto[-400:])
        for fragmento in ("R A S P B E R R Y", "Listo para tocar", "100 %", "Reinaldo Johnson Espinoza"):
            self.assertIn(fragmento, texto)
        self.assertLess(dur, 5, "con «listo» termina sola enseguida")

    def test_sigterm_la_cierra(self):
        codigo, texto, dur = self.correr([(time.time(), "inicio")], maximo=60, sigterm_tras=1.5)
        self.assertEqual(codigo, 0, texto[-400:])
        self.assertIn("Preparando el piano", texto)
        self.assertLess(dur, 10, "SIGTERM (el piano falló) la cierra")

    def test_tiempo_maximo(self):
        codigo, _, dur = self.correr([(time.time(), "inicio")], maximo=1)
        self.assertEqual(codigo, 0)
        self.assertLess(dur, 6, "si nadie la cierra, termina sola al tiempo máximo")


if __name__ == "__main__":
    unittest.main()
