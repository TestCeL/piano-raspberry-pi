"""Integración EN LA RASPBERRY: enrutador_midi.py con ALSA real (sin sonido).
Fuentes simuladas ("Teclado Piano" y un teclado MIDI que aparece en caliente), órdenes por FIFO,
salida verificada con aseqdump, estado JSON, preferencias y cierre limpio."""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import alsa_seq as aseq  # noqa: E402
import enrutador_midi as em  # noqa: E402


def esperar(cond, segundos=8.0, paso=0.1):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(paso)
    return False


@unittest.skipUnless(sys.platform.startswith("linux") and os.path.exists("/dev/snd/seq"), "ALSA real")
class TestEnrutadorReal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.fifo = os.path.join(self.d.name, "ordenes")
        self.estado = os.path.join(self.d.name, "estado.json")
        self.prefs = os.path.join(self.d.name, "prefs.json")
        self.pc = aseq.ClienteSeq("Teclado Piano")
        self.pc_puerto = self.pc.puerto_salida("notas")
        self.router = subprocess.Popen([sys.executable, os.path.join(DIR, "enrutador_midi.py"),
                                        "--ordenes", self.fifo, "--estado", self.estado,
                                        "--preferencias", self.prefs, "--sin-sistema"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.assertTrue(esperar(lambda: os.path.exists(self.estado)), "el enrutador no publicó su estado")
        self.assertTrue(esperar(lambda: any(f["id"] == "Teclado Piano:notas" and f["activa"]
                                            for f in self.leer_estado().get("fuentes", []))))
        self.dump_log = open(os.path.join(self.d.name, "dump.log"), "w+")
        self.proc_dump = subprocess.Popen(["aseqdump", "-p", f"{em.NOMBRE_PROPIO}:1"], stdout=self.dump_log,
                                     stderr=subprocess.STDOUT)
        time.sleep(0.5)
        self.midi = None

    def tearDown(self):
        for p in (self.proc_dump, self.router):
            if p and p.poll() is None:
                p.terminate()
                p.wait(5)
        self.dump_log.close()
        self.pc.cerrar()
        if self.midi:
            self.midi.cerrar()
        self.d.cleanup()

    def leer_estado(self):
        try:
            with open(self.estado) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def orden(self, texto):
        with open(self.fifo, "w") as f:
            f.write(texto + "\n")
        time.sleep(0.3)

    def texto_dump(self):
        self.dump_log.flush()
        self.dump_log.seek(0)
        return self.dump_log.read()

    def test_flujo_completo(self):
        self.orden("transponer =2")
        self.orden("curva dura")
        self.pc.enviar(("on", 60, 80), self.pc_puerto)
        self.assertTrue(esperar(lambda: re.search(r"Note on\s+0, note 62, velocity 80", self.texto_dump())),
                        "transposición +2 y sin curva para el teclado de computador:\n" + self.texto_dump())
        self.assertTrue(esperar(lambda: self.leer_estado().get("sonando") == [62]))

        # Teclado MIDI que aparece en caliente: se conecta solo (auto_nuevas) y se le aplica la curva
        self.midi = aseq.ClienteSeq("Prueba MIDI")
        mp = self.midi.puerto_salida("salida")
        self.assertTrue(esperar(lambda: any(f["id"] == "Prueba MIDI:salida" and f["activa"] and f["conectada"]
                                            for f in self.leer_estado().get("fuentes", []))),
                        f"no se detectó el teclado nuevo: {self.leer_estado()}")
        time.sleep(0.3)
        self.midi.enviar(("on", 64, 64), mp)
        v = em.curva_fuerza(64, "dura")
        self.assertTrue(esperar(lambda: re.search(rf"Note on\s+0, note 66, velocity {v}\b", self.texto_dump())),
                        "curva dura en el teclado MIDI:\n" + self.texto_dump())

        # Desactivar el teclado MIDI: suelta su nota y deja de pasar lo que toque
        self.orden("fuente off Prueba MIDI:salida")
        self.assertTrue(esperar(lambda: re.search(r"Note off\s+0, note 66", self.texto_dump())))
        self.midi.enviar(("on", 67, 100), mp)
        time.sleep(0.5)
        self.assertNotIn("note 69", self.texto_dump(), "una fuente desactivada no debe sonar")

        # Pedal y note off del teclado de computador
        self.pc.enviar(("cc", 64, 127), self.pc_puerto)
        self.assertTrue(esperar(lambda: self.leer_estado().get("pedal") is True))
        self.pc.enviar(("off", 60), self.pc_puerto)
        self.assertTrue(esperar(lambda: re.search(r"Note off\s+0, note 62", self.texto_dump())))

        # Pánico
        self.orden("panico")
        self.assertTrue(esperar(lambda: re.search(r"controller 123, value 0", self.texto_dump())
                                and re.search(r"controller 120, value 0", self.texto_dump())))
        self.assertTrue(esperar(lambda: self.leer_estado().get("pedal") is False))

        # Preferencias guardadas
        self.assertTrue(esperar(lambda: em.cargar_preferencias(self.prefs)["curva"] == "dura"))
        p = em.cargar_preferencias(self.prefs)
        self.assertEqual(p["transposicion"], 2)
        self.assertEqual(p["fuentes"].get("Prueba MIDI:salida"), False)

        # Cierre limpio
        self.router.send_signal(signal.SIGTERM)
        self.router.wait(5)
        self.assertEqual(self.router.returncode, 0)
        self.assertFalse(os.path.exists(self.estado), "el estado se borra al salir")
        out = subprocess.run(["aconnect", "-l"], capture_output=True, text=True).stdout
        self.assertNotIn(em.NOMBRE_PROPIO, out)

    def test_preferencias_restauradas_al_arrancar(self):
        self.orden("transponer =-5")
        self.orden("latencia 256")
        self.router.send_signal(signal.SIGTERM)
        self.router.wait(5)
        self.proc_dump.terminate()
        self.router = subprocess.Popen([sys.executable, os.path.join(DIR, "enrutador_midi.py"),
                                        "--ordenes", self.fifo, "--estado", self.estado,
                                        "--preferencias", self.prefs, "--sin-sistema"])
        self.assertTrue(esperar(lambda: self.leer_estado().get("transposicion") == -5))
        self.assertEqual(self.leer_estado().get("latencia"), 256)
        r = subprocess.run([sys.executable, os.path.join(DIR, "enrutador_midi.py"), "--pref", "latencia",
                            "--preferencias", self.prefs, "--sin-sistema"], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "256")


@unittest.skipUnless(sys.platform.startswith("linux") and os.path.exists("/dev/snd/seq"), "ALSA real")
class TestPausaDuranteLaCarga(unittest.TestCase):
    """Enrutador real con un sfizz simulado (su FIFO de órdenes y su salida): mientras «carga» un instrumento no
    pasa ninguna nota a la salida MIDI; al confirmarse la carga vuelven a pasar."""

    def test_no_pasan_notas_mientras_carga(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "inst")
            for i in ("a", "b"):
                os.makedirs(os.path.join(base, i))
                open(os.path.join(base, i, f"{i}.sfz"), "w").close()
            catalogo = os.path.join(d, "cat.json")
            with open(catalogo, "w") as f:
                json.dump({"instrumentos": [
                    {"id": i, "nombre": f"Piano {i.upper()}", "tipo": "cola", "sfz": f"{i}/{i}.sfz", "ganancia_db": 0,
                     "carga_s": 5, "autor": "x", "licencia": "l", "uso": "u", "fuente": "f"} for i in ("a", "b")]}, f)
            ctl_sfizz = os.path.join(d, "sfizz.ctl")
            os.mkfifo(ctl_sfizz)
            lector = os.open(ctl_sfizz, os.O_RDWR | os.O_NONBLOCK)      # hace de sfizz: recibe las órdenes
            salida_sfizz = os.path.join(d, "sfizz.log")
            open(salida_sfizz, "w").close()
            estado = os.path.join(d, "estado.json")
            pc = aseq.ClienteSeq("Teclado Piano")
            pc_puerto = pc.puerto_salida("notas")
            router = subprocess.Popen(
                [sys.executable, os.path.join(DIR, "enrutador_midi.py"), "--ordenes", os.path.join(d, "ordenes"),
                 "--estado", estado, "--preferencias", os.path.join(d, "prefs.json"), "--sin-sistema",
                 "--ctl-sintetizador", ctl_sfizz, "--instrumento-inicial", "a", "--catalogo", catalogo,
                 "--base-instrumentos", base, "--salida-sintetizador", f"tail -n +1 -F '{salida_sfizz}'"],
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            dump_log = open(os.path.join(d, "dump.log"), "w+")
            dump = None
            try:
                def leer():
                    try:
                        with open(estado) as f:
                            return json.load(f)
                    except (OSError, ValueError):
                        return {}

                def inst():
                    return leer().get("instrumento") or {}

                def sfizz_dice(texto):
                    with open(salida_sfizz, "a") as f:
                        f.write(texto + "\n")

                def ordenes_recibidas():
                    try:
                        return os.read(lector, 65536).decode()
                    except BlockingIOError:
                        return ""

                def volcado():
                    dump_log.flush()
                    dump_log.seek(0)
                    return dump_log.read()

                self.assertTrue(esperar(lambda: inst().get("estado") == "cargando"), "no aplicó los ajustes iniciales")
                self.assertIn("set_volume 0", ordenes_recibidas())
                sfizz_dice("> Volume set: 0 dB")
                self.assertTrue(esperar(lambda: inst().get("estado") == "listo"))
                self.assertTrue(esperar(lambda: any(f["id"] == "Teclado Piano:notas" and f["activa"]
                                                    for f in leer().get("fuentes", []))))
                dump = subprocess.Popen(["aseqdump", "-p", f"{em.NOMBRE_PROPIO}:1"], stdout=dump_log,
                                        stderr=subprocess.STDOUT)
                time.sleep(0.5)
                pc.enviar(("on", 60, 80), pc_puerto)
                self.assertTrue(esperar(lambda: re.search(r"Note on\s+0, note 60", volcado())), "antes suena")
                pc.enviar(("off", 60), pc_puerto)

                with open(os.path.join(d, "ordenes"), "w") as f:
                    f.write("instrumento b\n")
                self.assertTrue(esperar(lambda: (inst().get("carga") or {}).get("id") == "b"),
                                f"no empezó la carga: {inst()}")
                self.assertIn('load_instrument "', ordenes_recibidas())
                carga = inst()["carga"]
                self.assertEqual((carga["nombre"], carga["estimado_s"]), ("Piano B", 5.0))
                self.assertLess(abs(carga["inicio"] - time.time()), 5, "inicio en hora de reloj (para la barra)")
                pc.enviar(("on", 62, 80), pc_puerto)
                pc.enviar(("cc", 64, 127), pc_puerto)
                time.sleep(0.8)
                self.assertNotIn("note 62", volcado(), "con el piano en pausa no pasa ninguna nota")
                self.assertNotIn("controller 64, value 127", volcado(), "ni el pedal")
                self.assertEqual(leer().get("sonando"), [])
                self.assertTrue(leer().get("pedal"), "el pedal sí se registra")

                sfizz_dice(f"> Instrument loaded: {os.path.join(base, 'b', 'b.sfz')}")
                sfizz_dice("> Volume set: 0 dB")
                self.assertTrue(esperar(lambda: inst().get("estado") == "listo" and inst().get("carga") is None))
                self.assertTrue(esperar(lambda: re.search(r"controller 64, value 127", volcado())),
                                "al terminar se envía el pedal real")
                pc.enviar(("on", 64, 80), pc_puerto)
                self.assertTrue(esperar(lambda: re.search(r"Note on\s+0, note 64", volcado())), "y vuelve a sonar")
                self.assertNotIn("note 62", volcado(), "la nota tocada en pausa no aparece después")
                self.assertTrue(esperar(lambda: "b" in em.cargar_preferencias(
                    os.path.join(d, "prefs.json")).get("tiempos_carga", {})), "tiempo de carga aprendido y guardado")
            finally:
                for proc in (dump, router):
                    if proc and proc.poll() is None:
                        proc.terminate()
                        proc.wait(5)
                dump_log.close()
                pc.cerrar()
                os.close(lector)


@unittest.skipUnless(sys.platform.startswith("linux") and os.path.exists("/dev/snd/seq"), "ALSA real")
class TestCortesDelRegistroReal(unittest.TestCase):
    """El enrutador real cuenta y anota los cortes del reloj leyendo un registro de PipeWire (aquí simulado con las
    líneas reales de la sesión del usuario, que pw-top no contaba)."""

    def test_cuenta_y_anota_los_cortes_del_reloj(self):
        g1 = "alsa_output.usb-Creative_Technology_Ltd_Sound_BlasterX_G1_00030790-00.analog-stereo"
        with tempfile.TemporaryDirectory() as d:
            lineas = os.path.join(d, "pipewire.log")
            with open(lineas, "w") as f:
                f.write(f"pw.node: ({g1}-69) graph xrun not-triggered (0 suppressed)\n"
                        f"pw.node: ({g1}-69) xrun state:0x7f97905008 pending:2/4 status:triggered\n"
                        "pw.node: (Dummy-Driver-30) graph xrun not-triggered (3 suppressed)\n"
                        f"pw.node: ({g1}-69) graph xrun not-triggered (7 suppressed)\n")
            estado = os.path.join(d, "estado.json")
            salida = open(os.path.join(d, "salida.log"), "w+")
            router = subprocess.Popen(
                [sys.executable, os.path.join(DIR, "enrutador_midi.py"), "--ordenes", os.path.join(d, "ordenes"),
                 "--estado", estado, "--preferencias", os.path.join(d, "prefs.json"), "--sin-sistema",
                 "--nodo-xruns", "nodo-que-no-existe", "--nodo-xruns", g1,
                 "--registro-pipewire", f"sleep 1; cat '{lineas}'; sleep 60"],
                stdout=salida, stderr=subprocess.STDOUT)
            try:
                def xruns():
                    try:
                        with open(estado) as f:
                            return json.load(f).get("xruns")
                    except (OSError, ValueError):
                        return None
                self.assertTrue(esperar(lambda: xruns() == 9, 10), f"cortes en el estado: {xruns()}")
            finally:
                router.terminate()
                router.wait(5)
            salida.seek(0)
            texto = salida.read()
            salida.close()
            self.assertEqual(texto.count("CORTE +"), 2, texto)
            self.assertIn("CORTE +8 (total 9) | nodos: " + g1, texto)
            self.assertNotIn("Dummy-Driver", texto, "otro reloj no cuenta")
            self.assertFalse(subprocess.run(["pgrep", "-f", f"^cat {lineas}"], capture_output=True).stdout,
                             "al salir, el enrutador termina también su lector del registro")


if __name__ == "__main__":
    unittest.main()
