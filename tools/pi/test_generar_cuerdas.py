"""Pruebas del generador del ensemble de cuerdas (SFZ sintéticos con la estructura de VSCO 2 CE)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generar_cuerdas as gc  # noqa: E402

VIOLIN = """<control>
default_path=Strings\\Violin Section\\susVib\\
<global>
ampeg_attack=0.001
ampeg_release=0.8 // comentario
<group> //grupo
<region>
sample=VlnEns_susVib_A2_v1.wav
lokey=55
hikey=57
pitch_keycenter=57
lovel=0
hivel=62
<region> sample=VlnEns_susVib_A2_v2.wav lokey=55 hikey=57 pitch_keycenter=57 lovel=63
<region> sample=VlnEns_susVib_C6_v1.wav lokey=80 hikey=86 pitch_keycenter=84
"""
CELLO = """<control> default_path=Strings\\Cello Section\\susvib\\
<global> ampeg_release=1.2 volume=-2
<region> sample=CelloEns_C2.wav lokey=36 hikey=40 pitch_keycenter=36
<region> sample=CelloEns_C4.wav lokey=58 hikey=77 pitch_keycenter=60
"""
BAJO = """<control> default_path=Strings/Solo Contrabass/SusVib/
<region> sample=Contrabass C1 largo.wav key=c1
<region> sample=Contrabass E1.wav lokey=25 hikey=60 pitch_keycenter=28
"""


class TestAnalisis(unittest.TestCase):
    def test_notas(self):
        self.assertEqual([gc.nota_midi(v) for v in ("60", "c4", "a0", "c#4", "db4", "c-1")], [60, 60, 21, 61, 61, 0])
        with self.assertRaises(ValueError):
            gc.nota_midi("h4")

    def test_tokens_comentarios_y_valores_con_espacios(self):
        b = gc.analizar("<region> sample=Mi muestra 1.wav lokey=60 // nota\n<group> volume=-3")
        self.assertEqual(b, [("region", {"sample": "Mi muestra 1.wav", "lokey": "60"}), ("group", {"volume": "-3"})])

    def test_regiones_heredan_cabeceras_y_ruta(self):
        regs = gc.regiones(gc.analizar(VIOLIN))
        self.assertEqual(len(regs), 3)
        ruta, o = regs[0]
        self.assertEqual(ruta, "Strings/Violin Section/susVib/")
        self.assertEqual((o["ampeg_attack"], o["ampeg_release"], o["hivel"]), ("0.001", "0.8", "62"))


class TestGenerar(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        for nombre, texto in (("v.sfz", VIOLIN), ("c.sfz", CELLO), ("b.sfz", BAJO)):
            with open(os.path.join(self.d.name, nombre), "w", encoding="utf-8") as f:
                f.write(texto)
        self.secciones = (("b.sfz", 21, 35), ("c.sfz", 36, 54), ("v.sfz", 55, 108))

    def tearDown(self):
        self.d.cleanup()

    def regiones_generadas(self):
        texto = gc.generar(self.d.name, self.secciones)
        return gc.regiones(gc.analizar(texto)), texto

    def test_franjas_sin_solaparse(self):
        regs, _ = self.regiones_generadas()
        franjas = sorted((int(o["lokey"]), int(o["hikey"])) for _, o in regs)
        for (a1, b1), (a2, b2) in zip(franjas, franjas[1:]):
            self.assertTrue(b1 < a2 or (a1, b1) == (a2, b2), f"solape {a1}-{b1} / {a2}-{b2}")
        bajo = [o for r, o in regs if r.startswith("Strings/Solo Contrabass")]
        self.assertTrue(all(int(o["hikey"]) <= 35 for o in bajo), "el contrabajo no pasa de Si1")
        chelo = [o for r, o in regs if "Cello" in r]
        self.assertEqual([(o["lokey"], o["hikey"]) for o in chelo], [("36", "40")],
                         "la región aguda del chelo (58-77) cae fuera de su franja y se descarta")

    def test_conserva_capas_envolventes_y_rutas(self):
        regs, texto = self.regiones_generadas()
        violin = [o for r, o in regs if "Violin" in r]
        self.assertEqual([(o["lovel"], o.get("hivel")) for o in violin[:2]], [("0", "62"), ("63", None)])
        self.assertTrue(all(o["ampeg_release"] == "0.8" for o in violin), "envolvente de su sección")
        chelo = [o for r, o in regs if "Cello" in r][0]
        self.assertEqual((chelo["ampeg_release"], chelo["volume"]), ("1.2", "-2"))
        self.assertIn("<control> default_path=Strings/Solo Contrabass/SusVib/", texto)
        self.assertIn("sample=Contrabass C1 largo.wav", texto, "nombres con espacios intactos")
        self.assertIn("//   b.sfz: teclas 21-35", texto, "el resumen refleja la franja final (con la extensión)")

    def test_key_se_convierte_y_el_grave_se_extiende(self):
        regs, _ = self.regiones_generadas()
        bajo = [o for r, o in regs if r.startswith("Strings/Solo Contrabass")]
        c1 = next(o for o in bajo if o["sample"].startswith("Contrabass C1"))
        self.assertEqual((c1["lokey"], c1["hikey"], c1["pitch_keycenter"]), ("21", "24", "24"),
                         "key=c1 (24) pasa a lokey/hikey/pitch_keycenter y baja hasta La0")
        e1 = next(o for o in bajo if o["sample"].startswith("Contrabass E1"))
        self.assertEqual((e1["lokey"], e1["hikey"]), ("25", "35"))

    def test_seccion_sin_regiones_es_error(self):
        with self.assertRaises(ValueError):
            gc.generar(self.d.name, (("b.sfz", 100, 108),))

    def test_main_escribe_el_archivo(self):
        salida = os.path.join(self.d.name, "x.sfz")
        original = gc.SECCIONES
        gc.SECCIONES = self.secciones
        try:
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                self.assertEqual(gc.main(["x", self.d.name, salida]), 0)
        finally:
            gc.SECCIONES = original
        with open(salida, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("// Ensemble de cuerdas"))


if __name__ == "__main__":
    unittest.main()
