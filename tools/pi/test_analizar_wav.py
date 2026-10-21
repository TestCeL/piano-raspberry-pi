"""Pruebas de analizar_wav.py con archivos WAV sintéticos de nivel conocido."""
import io
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from array import array
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analizar_wav as a  # noqa: E402


def wav_float(ruta, canales, frames, sr=44100, extensible=False, tam_data=None):
    datos = array("f", [x for fr in frames for x in fr]).tobytes()
    if extensible:
        guid_float = struct.pack("<H", 3) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        fmt = struct.pack("<HHIIHH", 0xFFFE, canales, sr, sr * 4 * canales, 4 * canales, 32)
        fmt += struct.pack("<HHI", 22, 32, 3) + guid_float
    else:
        fmt = struct.pack("<HHIIHH", 3, canales, sr, sr * 4 * canales, 4 * canales, 32)
    declarado = len(datos) if tam_data is None else tam_data
    cuerpo = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", declarado) + datos
    with open(ruta, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(cuerpo)) + cuerpo)


def wav_pcm16(ruta, canales, frames, sr=44100):
    with wave.open(ruta, "wb") as w:
        w.setnchannels(canales)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(array("h", [int(x) for fr in frames for x in fr]).tobytes())


class TestAnalizarWav(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def ruta(self, nombre):
        return os.path.join(self.dir.name, nombre)

    def test_float_estereo_pico_rms_y_sobrecargas(self):
        r = self.ruta("f.wav")
        wav_float(r, 2, [(0.5, -1.5), (-0.25, 0.1), (0.0, 1.0)])
        sr, ch, m = a.leer_wav(r)
        self.assertEqual((sr, ch), (44100, 2))
        izq, der = a.medir(m[0]), a.medir(m[1])
        self.assertAlmostEqual(izq["pico"], 0.5)
        self.assertEqual(izq["sobre_0dbfs"], 0)
        self.assertAlmostEqual(der["pico"], 1.5)
        self.assertEqual(der["sobre_0dbfs"], 2, "−1.5 y 1.0 alcanzan o superan 0 dBFS")
        self.assertAlmostEqual(izq["rms"], math.sqrt((0.25 + 0.0625) / 3), places=6)

    def test_float_extensible(self):
        r = self.ruta("e.wav")
        wav_float(r, 2, [(0.25, 0.75)], extensible=True)
        _, _, m = a.leer_wav(r)
        self.assertAlmostEqual(a.medir(m[1])["pico"], 0.75)

    def test_cabecera_sin_cerrar(self):
        for declarado in (0, 0xFFFFFFFF):
            with self.subTest(declarado=declarado):
                r = self.ruta(f"u{declarado}.wav")
                wav_float(r, 1, [(0.1,), (0.9,)], tam_data=declarado)
                _, _, m = a.leer_wav(r)
                self.assertEqual(len(m[0]), 2)
                self.assertAlmostEqual(a.medir(m[0])["pico"], 0.9, places=6)

    def test_pcm16(self):
        r = self.ruta("p.wav")
        wav_pcm16(r, 1, [(16384,), (-32768,)])
        _, _, m = a.leer_wav(r)
        med = a.medir(m[0])
        self.assertAlmostEqual(med["pico"], 1.0)
        self.assertEqual(med["sobre_0dbfs"], 1)

    def test_dbfs(self):
        self.assertAlmostEqual(a.dbfs(1.0), 0.0)
        self.assertAlmostEqual(a.dbfs(0.5), -6.0206, places=3)
        self.assertEqual(a.dbfs(0.0), -math.inf)

    def test_no_es_wav(self):
        r = self.ruta("x.wav")
        with open(r, "wb") as f:
            f.write(b"hola mundo, esto no es un wav")
        with self.assertRaises(ValueError):
            a.leer_wav(r)

    def test_tramo_mide_solo_la_ventana(self):
        r = self.ruta("t.wav")
        sr = 1000
        # 1 s a 0.5, 1 s a 0.05, 1 s de silencio
        wav_float(r, 2, [(0.5, -0.5)] * sr + [(0.05, 0.05)] * sr + [(0.0, 0.0)] * sr, sr=sr)
        completo = a.niveles(r)
        self.assertAlmostEqual(completo[0][0], a.dbfs(0.5), places=3)
        cola = a.niveles(r, 1.0, 2.0)
        self.assertEqual(len(cola), 2)
        self.assertAlmostEqual(cola[0][0], a.dbfs(0.05), places=3)
        self.assertAlmostEqual(cola[0][1], a.dbfs(0.05), places=3)
        silencio = a.niveles(r, 2.0, None)
        self.assertEqual(silencio[1][:2], (-math.inf, -math.inf))
        self.assertEqual(a.niveles(r, None, 1.0)[1][0], a.dbfs(0.5))

    def test_tramo_invalido(self):
        r = self.ruta("t.wav")
        wav_float(r, 1, [(0.1,)] * 100, sr=100)        # 1 s
        for desde, hasta in ((0.5, 0.5), (0.8, 0.2), (0.0, 1.5), (-0.1, 0.5)):
            with self.subTest(desde=desde, hasta=hasta), self.assertRaises(ValueError):
                a.niveles(r, desde, hasta)
        salida = io.StringIO()
        with redirect_stdout(salida):
            self.assertEqual(a.main([r, "--desde", "0.2", "--hasta", "0.6"]), 0)
            self.assertEqual(a.main([r, "--desde", "2"]), 2)
        self.assertIn("tramo 0.20..0.60 s", salida.getvalue())

    def test_frecuencia_fundamental(self):
        sr = 44100
        def tono(f, armonicos=((1, 1.0),), seg=0.5):
            return [sum(a * math.sin(2 * math.pi * f * n * k / sr) for n, a in armonicos) for k in range(int(seg * sr))]
        f = a.frecuencia_fundamental([tono(440)], sr, 0.05)
        self.assertAlmostEqual(f, 440, delta=1.0)
        # Segundo armónico más fuerte que la fundamental (como un piano grave): no debe dar la octava
        f = a.frecuencia_fundamental([tono(110, ((1, 0.4), (2, 1.0), (3, 0.6)))], sr, 0.05)
        self.assertAlmostEqual(f, 110, delta=1.0)
        izquierda, derecha = tono(261.63), tono(261.63)
        self.assertAlmostEqual(a.frecuencia_fundamental([izquierda, derecha], sr, 0.05), 261.63, delta=1.0)
        self.assertAlmostEqual(1200 * math.log2(a.frecuencia_fundamental([tono(446.4)], sr, 0.05) / 440), 25, delta=3,
                               msg="resolución suficiente para medir cents")
        self.assertIsNone(a.frecuencia_fundamental([[0.0] * sr], sr, 0.05), "silencio: sin frecuencia")
        self.assertIsNone(a.frecuencia_fundamental([tono(440, seg=0.02)], sr, 0.0), "tramo demasiado corto")

    def test_main_umbral(self):
        r = self.ruta("m.wav")
        wav_float(r, 1, [(0.5,), (0.89,)])          # pico ≈ −1.0 dBFS
        with redirect_stdout(io.StringIO()):
            self.assertEqual(a.main([r, "--max-dbfs", "-0.5"]), 0)
            self.assertEqual(a.main([r, "--max-dbfs", "-3"]), 1)
            self.assertEqual(a.main([r]), 0)


if __name__ == "__main__":
    unittest.main()
