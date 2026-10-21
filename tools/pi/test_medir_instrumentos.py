"""Pruebas de medir_instrumentos.py: cálculos (RMS conjunto, ganancia, pedal, salida de escuchar-midi) y flujo
completo con un renderizador simulado (escribe WAV de nivel conocido según el instrumento)."""
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
from array import array
from contextlib import redirect_stderr, redirect_stdout

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
if os.path.isdir(os.path.join(AQUI, "..", "midi")):          # en el PC el generador vive en tools/midi
    sys.path.insert(0, os.path.join(AQUI, "..", "midi"))
import medir_instrumentos as mi  # noqa: E402

SR = 2000


def escribir_wav(ruta, tramos):
    """tramos: [(segundos, amplitud)] -> WAV float estéreo con onda cuadrada de esa amplitud (RMS = amplitud)."""
    muestras = array("f")
    for seg, amp in tramos:
        for k in range(int(seg * SR)):
            v = amp if k % 2 else -amp
            muestras.extend((v, v))
    datos = muestras.tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, SR, SR * 8, 8, 32)
    cuerpo = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(datos)) + datos
    with open(ruta, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(cuerpo)) + cuerpo)


def escribir_seno(ruta, f, seg, sr=44100):
    muestras = array("f")
    for k in range(int(seg * sr)):
        v = 0.3 * math.sin(2 * math.pi * f * k / sr)
        muestras.extend((v, v))
    datos = muestras.tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, sr, sr * 8, 8, 32)
    cuerpo = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(datos)) + datos
    with open(ruta, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(cuerpo)) + cuerpo)


def render_simulado(_sfizz_render, inst, midi, wav):
    """Amplitud según el id; 'sinpedal' no sostiene. Comprueba que el MIDI lleva los controles delante."""
    amp = {"salamander": 0.1, "fuerte": 0.4, "sinpedal": 0.05}[inst.id]
    with open(midi, "rb") as f:
        datos = f.read()
    if inst.controles:
        cc, v = inst.controles[0]
        assert datos[22:26] == bytes([0, 0xB0, cc, v]), "faltan los controles iniciales"
    if midi.endswith("-nivel.mid"):
        escribir_wav(wav, [(2.0, amp)])
    elif midi.endswith("-afinacion.mid"):
        f = {"salamander": 440.0, "fuerte": 440.0 * 2 ** (10 / 1200), "sinpedal": 220.0}[inst.id]
        escribir_seno(wav, f, 2.0)
    else:
        sostiene = inst.id != "sinpedal"
        escribir_wav(wav, [(1.0, amp), (3.0, amp * 0.001), (1.0, amp), (3.0, amp * (0.3 if sostiene else 0.001)),
                           (2.5, 0.0)])
    return 0.5


class TestCalculos(unittest.TestCase):
    def test_combinar_rms(self):
        self.assertAlmostEqual(mi.combinar_rms([-20.0, -20.0]), -20.0)
        self.assertAlmostEqual(mi.combinar_rms([-20.0, -math.inf]), -20.0 - 10 * math.log10(2))
        self.assertEqual(mi.combinar_rms([-math.inf, -math.inf]), -math.inf)

    def test_cents(self):
        self.assertAlmostEqual(mi.cents(880.0), 1200)
        self.assertAlmostEqual(mi.cents(440.0), 0)
        self.assertIsNone(mi.cents(None))

    def test_ganancia_limitada_por_pico(self):
        self.assertEqual(mi.ganancia_para(-31.0, -34.4, pico=-7.1), -1.9, "arpa: el pico manda (-9 dBFS)")
        self.assertEqual(mi.ganancia_para(-31.0, -37.04, pico=-20.0), 6.0, "con pico bajo, manda el RMS")
        self.assertEqual(mi.ganancia_para(-31.0, -37.04, pico=-math.inf), 6.0)

    def test_ganancia(self):
        self.assertEqual(mi.ganancia_para(-31.0, -37.04), 6.0)
        self.assertEqual(mi.ganancia_para(-31.0, -21.96), -9.0)
        self.assertEqual(mi.ganancia_para(-31.0, -31.0), 0.0)
        self.assertEqual(mi.ganancia_para(-10.0, -90.0), mi.cat.GANANCIA_MAX, "se limita al rango del catálogo")
        with self.assertRaises(ValueError):
            mi.ganancia_para(-31.0, -math.inf)

    def test_pedal(self):
        self.assertEqual(mi.evaluar_pedal(-60.0, -20.0), ("sí", 40.0))
        self.assertEqual(mi.evaluar_pedal(-30.0, -25.0), ("no aplica", 5.0),
                         "sin pedal la cola ya suena: no se corta al soltar (arpa, marimba)")
        self.assertEqual(mi.evaluar_pedal(-80.0, -75.0), ("NO", 5.0), "se corta y el pedal no lo sostiene")
        self.assertEqual(mi.evaluar_pedal(-60.0, -math.inf), ("NO", -math.inf))
        self.assertEqual(mi.evaluar_pedal(-math.inf, -40.0), ("sí", math.inf))

    def test_resumen_de_escuchar_midi(self):
        texto = ("== Iniciando piano-prueba: taskset ...\n   listo en 7 s (Instrument loaded: /x.sfz)\n"
                 "== ▶ x-carga\n   31 s\n   piano-prueba     B/Q máx 0.71, medio 0.42, xruns 3\n"
                 "   nivel: duración 31.6 s, 44100 Hz, 2 canal(es)\n"
                 "   nivel: canal 1: pico -10.7 dBFS, RMS -26.7 dBFS, muestras >= 0 dBFS: 0\n"
                 "   nivel: canal 2: pico -9.5 dBFS, RMS -27.2 dBFS, muestras >= 0 dBFS: 0\n")
        self.assertEqual(mi.resumen_escuchar(texto),
                         {"bq_max": 0.71, "bq_medio": 0.42, "xruns": 3, "carga_s": 7, "pico": -9.5})
        self.assertEqual(mi.resumen_escuchar("nada"),
                         {"bq_max": None, "bq_medio": None, "xruns": None, "carga_s": None, "pico": None})
        silencio = "   nivel: canal 1: pico -inf dBFS, RMS -inf dBFS, muestras >= 0 dBFS: 0\n"
        self.assertEqual(mi.resumen_escuchar(silencio)["pico"], -math.inf)
        self.assertIsNone(mi.resumen_escuchar("   piano-prueba-fx  B/Q máx 0.1, medio 0.1, xruns 0\n")["xruns"],
                          "no confunde el nodo del efecto con el del piano")


class TestTiempoRealSinAudio(unittest.TestCase):
    """Una medición en tiempo real sin sonido grabado no vale (caso real: B/Q 0,02 en un piano completo)."""

    def setUp(self):
        self.original = mi.subprocess.run
        self.salidas = []
        self.pasadas = []
        prueba = self

        class Proceso:
            def __init__(self, texto):
                self.returncode, self.stdout, self.stderr = 0, texto, ""

        def falso(args, **kw):
            if args and args[0] == "bash":
                prueba.assertIn("-r", args, "la medición en tiempo real debe grabar la salida")
                prueba.pasadas.append(args[args.index("-r") + 1])
                return Proceso(prueba.salidas.pop(0))
            return Proceso("")
        mi.subprocess.run = falso
        self.dir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.dir.name, "m"))
        mi.gen.escribir_smf(os.path.join(self.dir.name, "m", mi.PIEZA_CARGA), mi.gen.arpegios_densos())
        self.inst = mi.cat.validar({"instrumentos": [
            {"id": "x", "nombre": "x", "tipo": "cola", "sfz": "x.sfz", "ganancia_db": 0, "autor": "a",
             "licencia": "l", "uso": "u", "fuente": "f"}]}, self.dir.name)[0]

    def tearDown(self):
        mi.subprocess.run = self.original
        self.dir.cleanup()

    SILENCIO = "   nivel: canal 1: pico -inf dBFS, RMS -inf dBFS, muestras >= 0 dBFS: 0\n"
    AUDIO = "   nivel: canal 1: pico -11.0 dBFS, RMS -27.0 dBFS, muestras >= 0 dBFS: 0\n"

    def medir(self, *niveles):
        self.salidas = [("   listo en 1 s (Instrument loaded: x)\n"
                         "   piano-prueba     B/Q máx 0.02, medio 0.01, xruns 0\n" + n) for n in niveles]
        return mi.medir_tiempo_real(self.inst, os.path.join(self.dir.name, "m"), self.dir.name)

    def test_silencio_repetido_es_error(self):
        r = self.medir(self.SILENCIO, self.SILENCIO)
        self.assertIn("sin audio", r["error"])
        self.assertEqual((r["intentos"], len(r["salidas_sin_audio"])), (2, 2))
        self.assertIn("sin audio", self.medir("", "")["error"], "sin análisis de la grabación tampoco vale")

    def test_con_audio_es_valida(self):
        r = self.medir(self.AUDIO)
        self.assertNotIn("error", r)
        self.assertEqual((r["pico"], r["xruns"], r["intentos"]), (-11.0, 0, 1))
        self.assertNotIn("salidas_sin_audio", r)

    def test_una_pasada_sin_audio_se_repite_y_se_anota(self):
        r = self.medir(self.SILENCIO, self.AUDIO)
        self.assertNotIn("error", r)
        self.assertEqual((r["pico"], r["intentos"]), (-11.0, 2))
        self.assertEqual(len(r["salidas_sin_audio"]), 1, "se guarda la pasada fallida para diagnosticarla")
        self.assertEqual(len(set(self.pasadas)), 2, "cada pasada graba en su propia carpeta")


class TestFlujo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.dir.name, "inst")
        self.cat = os.path.join(self.dir.name, "cat.json")
        datos = {"instrumentos": [
            {"id": i, "nombre": i, "tipo": "cola", "sfz": f"{i}/{i}.sfz", "ganancia_db": 0,
             "controles": ({"77": 0} if i == "fuerte" else {}), "autor": "a", "licencia": "l", "uso": "u", "fuente": "f"}
            for i in ("salamander", "fuerte", "sinpedal")]}
        with open(self.cat, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        for i in ("salamander", "fuerte", "sinpedal"):
            os.makedirs(os.path.join(self.base, i))
            open(os.path.join(self.base, i, f"{i}.sfz"), "w").close()
        self.original = mi.render
        mi.render = render_simulado

    def tearDown(self):
        mi.render = self.original
        self.dir.cleanup()

    def correr(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = mi.main(["--catalogo", self.cat, "--base", self.base, *args])
        return rc, out.getvalue(), err.getvalue()

    def test_mide_iguala_y_detecta_pedal(self):
        res = os.path.join(self.dir.name, "r.json")
        salida = os.path.join(self.dir.name, "nuevo.json")
        rc, out, _ = self.correr("--json", res, "--catalogo-salida", salida)
        self.assertEqual(rc, 1, "un instrumento que no sostiene con el pedal es un fallo")
        with open(res, encoding="utf-8") as f:
            r = json.load(f)
        self.assertAlmostEqual(r["salamander"]["rms"], 20 * math.log10(0.1), places=2)
        self.assertEqual(r["fuerte"]["ganancia_db"], -12.0)          # 0.4 frente a 0.1
        self.assertEqual(r["sinpedal"]["ganancia_db"], 6.0)          # 0.05 frente a 0.1
        self.assertTrue(r["fuerte"]["pedal_ok"])
        self.assertFalse(r["sinpedal"]["pedal_ok"])
        self.assertAlmostEqual(r["salamander"]["afinacion_cents"], 0, delta=3)
        self.assertAlmostEqual(r["fuerte"]["afinacion_cents"], 10, delta=3)
        self.assertTrue(r["fuerte"]["afinacion_ok"])
        self.assertAlmostEqual(r["sinpedal"]["afinacion_cents"], -1200, delta=5, msg="una octava abajo")
        self.assertFalse(r["sinpedal"]["afinacion_ok"])
        self.assertIn("-1200c!", [l for l in out.splitlines() if l.startswith("sinpedal")][0])
        self.assertIn("NO", [l for l in out.splitlines() if l.startswith("sinpedal")][0])
        with open(salida, encoding="utf-8") as f:
            nuevo = {d["id"]: d["ganancia_db"] for d in json.load(f)["instrumentos"]}
        self.assertEqual(nuevo, {"salamander": 0, "fuerte": -12.0, "sinpedal": 6.0})

    def test_solo_los_pedidos_mas_la_referencia(self):
        res = os.path.join(self.dir.name, "r.json")
        rc, out, _ = self.correr("fuerte", "--json", res)
        self.assertEqual(rc, 0)
        with open(res, encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)), ["fuerte", "salamander"])

    def test_errores_de_uso(self):
        rc, _, err = self.correr("noexiste")
        self.assertEqual(rc, 2)
        self.assertIn("noexiste", err)
        os.remove(os.path.join(self.base, "salamander", "salamander.sfz"))
        rc, _, err = self.correr("fuerte")
        self.assertEqual(rc, 2)
        self.assertIn("referencia", err)

    def test_no_mide_en_tiempo_real_si_el_piano_esta_en_uso(self):
        original = mi.piano_en_uso
        mi.piano_en_uso = lambda: True
        try:
            rc, _, err = self.correr("--tiempo-real")
        finally:
            mi.piano_en_uso = original
        self.assertEqual(rc, 4)
        self.assertIn("en uso", err)


if __name__ == "__main__":
    unittest.main()
