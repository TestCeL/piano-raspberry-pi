"""Pruebas de teclado_piano.py (lógica, formato binario, controles, geometría, paneles, bucle e interfaz).
Las pruebas que requieren Linux (evdev de 64 bits, FIFOs, curses en pty) se omiten en otras plataformas."""
import ctypes
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teclado_piano as tp  # noqa: E402

A, W, S, J, K, L, P, APOS = 30, 17, 31, 36, 37, 38, 25, 40
ES_LINUX = sys.platform.startswith("linux")
# Caracteres que tiene de verdad la fuente de la consola de la Pi (Uni2-Terminus32x16, leída de su tabla Unicode):
# es lo que se puede dibujar en el monitor (p. ej. «Ó» y las flechas sí; «▀», «♪» o «►» no).
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "glifos_consola.txt")) as _f:
    CP437 = {chr(int(c, 16)) for c in _f.read().split()} | {" "}


class TestInterprete(unittest.TestCase):
    def setUp(self):
        self.i = tp.Interprete(octava=4, fuerza=80)

    def test_pulsar_y_soltar(self):
        self.assertEqual(self.i.evento(A, 1), [("on", 60, 80)])
        self.assertEqual(self.i.evento(A, 0), [("off", 60)])
        self.assertEqual(self.i.evento(W, 1), [("on", 61, 80)])
        self.assertEqual(self.i.evento(APOS, 1), [("on", 77, 80)])

    def test_repeticion_automatica_y_doble_pulsacion_ignoradas(self):
        self.i.evento(A, 1)
        self.assertEqual(self.i.evento(A, 2), [])
        self.assertEqual(self.i.evento(A, 1), [])
        self.assertEqual(self.i.evento(A, 0), [("off", 60)])
        self.assertEqual(self.i.evento(A, 0), [], "soltar sin pulsar no envía nada")

    def test_soltar_tras_cambiar_de_octava_apaga_la_nota_original(self):
        self.i.evento(A, 1)
        self.i.evento(tp.KEY_X, 1)
        self.assertEqual(self.i.octava, 5)
        self.assertEqual(self.i.evento(A, 0), [("off", 60)])
        self.assertEqual(self.i.evento(A, 1), [("on", 72, 80)])

    def test_limites_de_octava(self):
        for _ in range(20):
            self.i.evento(tp.KEY_X, 1)
        self.assertEqual(self.i.octava, tp.OCTAVA_MAX)
        for _ in range(20):
            self.i.evento(tp.KEY_Z, 1)
        self.assertEqual(self.i.octava, tp.OCTAVA_MIN)

    def test_notas_fuera_del_piano_se_ignoran(self):
        i = tp.Interprete(octava=0)
        self.assertEqual(i.evento(A, 1), [])
        self.assertEqual(i.evento(A, 0), [])
        self.assertEqual(i.evento(J, 1), [("on", 23, 80)])
        alto = tp.Interprete(octava=7)
        self.assertEqual(alto.evento(K, 1), [("on", 108, 80)])
        self.assertEqual(alto.evento(L, 1), [])

    def test_fuerza_por_pasos_y_limites(self):
        self.i.evento(tp.KEY_V, 1)
        self.assertEqual(self.i.fuerza, 96)
        for _ in range(10):
            self.i.evento(tp.KEY_V, 1)
        self.assertEqual(self.i.fuerza, 127)
        for _ in range(10):
            self.i.evento(tp.KEY_C, 1)
        self.assertEqual(self.i.fuerza, 16)
        self.assertEqual(self.i.evento(A, 1), [("on", 60, 16)])
        self.assertEqual(tp.Interprete(fuerza=70).fuerza, 64, "se ajusta al paso más cercano")

    def test_pedal(self):
        self.assertEqual(self.i.evento(tp.KEY_SPACE, 1), [("cc", 64, 127)])
        self.assertTrue(self.i.pedal)
        self.assertEqual(self.i.evento(tp.KEY_SPACE, 2), [], "repetición del pedal ignorada")
        self.assertEqual(self.i.evento(tp.KEY_SPACE, 0), [("cc", 64, 0)])
        self.assertFalse(self.i.pedal)

    def test_esc_apaga_todo_y_sale(self):
        self.i.evento(A, 1)
        self.i.evento(S, 1)
        self.i.evento(tp.KEY_SPACE, 1)
        msgs = self.i.evento(tp.KEY_ESC, 1)
        self.assertEqual(msgs[-1], ("salir",))
        self.assertCountEqual(msgs[:-1], [("off", 60), ("off", 62), ("cc", 64, 0)])
        self.assertEqual(self.i.sonando, {})
        self.assertEqual(self.i.apagar_todo(), [], "nada que apagar dos veces")

    def test_teclas_desconocidas(self):
        self.assertEqual(self.i.evento(99, 1), [])
        self.assertEqual(self.i.evento(tp.KEY_X, 0), [], "soltar Z/X/C/V no hace nada")

    def test_estado_y_nombres(self):
        self.assertEqual(tp.nombre_nota(60), "Do4")
        self.assertEqual(tp.nombre_nota(21), "La0")
        self.assertEqual(tp.nombre_nota(108), "Do8")
        self.i.evento(A, 1)
        e = self.i.estado()
        self.assertIn("Octava 4", e)
        self.assertIn("Do4", e)


RHODES = {"id": "rhodes", "nombre": "Rhodes Mark I (jRhodes3d)", "tipo": "electrico", "autor": "Jeff Learman",
          "licencia": "Muestras CC BY-NC 4.0 (uso no comercial); SFZ CC0", "uso": "solo uso no comercial",
          "restringido": True, "fuente": "https://github.com/sfzinstruments/jlearman.jRhodes3d"}
LISTA = [{"id": "salamander", "nombre": "Salamander (Yamaha C5)", "tipo": "cola", "autor": "Alexander Holm",
          "licencia": "CC BY 3.0", "uso": "libre; citar al autor", "restringido": False,
          "fuente": "https://sfzinstruments.github.io/pianos/salamander"},
         {"id": "headroom", "nombre": "Headroom (Yamaha C3)", "tipo": "cola"},
         RHODES,
         {"id": "hammond-drawbar", "nombre": "Hammond (drawbars)", "tipo": "organo"},
         {"id": "iglesia", "nombre": "Órgano de iglesia", "tipo": "organo"},
         {"id": "vibrafono", "nombre": "Vibráfono", "tipo": "percusion"}]
F, LEFT_, RIGHT_, UP_, DOWN_ = 67, 105, 106, 103, 108
Q, R, G_, O_ = 16, 19, 34, 24


class TestMenuInstrumentos(unittest.TestCase):
    def setUp(self):
        self.m = tp.MenuInstrumentos()
        self.m.abrir(LISTA, "rhodes")

    def elegido(self):
        return self.m.visibles()[self.m.idx]["id"]

    def test_abre_en_la_categoria_del_que_suena(self):
        self.assertEqual([c[1] for c in self.m.categorias()],
                         ["Pianos de cola", "Pianos eléctricos", "Órganos", "Percusión"],
                         "solo categorías con instrumentos, en el orden del catálogo")
        self.assertEqual((self.m.cat, self.elegido()), (1, "rhodes"))

    def test_navegacion_circular(self):
        self.m.tecla(RIGHT_)
        self.assertEqual((self.m.cat, self.elegido()), (2, "hammond-drawbar"), "al cambiar de categoría, el primero")
        self.m.tecla(DOWN_)
        self.assertEqual(self.elegido(), "iglesia")
        self.m.tecla(DOWN_)
        self.assertEqual(self.elegido(), "hammond-drawbar", "abajo desde el último vuelve al primero")
        self.m.tecla(UP_)
        self.assertEqual(self.elegido(), "iglesia")
        self.m.tecla(RIGHT_)
        self.m.tecla(RIGHT_)
        self.assertEqual(self.m.cat, 0, "derecha desde la última categoría vuelve a la primera")
        self.m.tecla(LEFT_)
        self.assertEqual(self.m.cat, 3)

    def test_enter_carga_y_cierra(self):
        self.m.tecla(RIGHT_)
        self.m.tecla(DOWN_)
        self.assertEqual(self.m.tecla(tp.KEY_ENTER), [("router", "instrumento ya iglesia")])
        self.assertFalse(self.m.abierto)

    def test_esc_y_f9_cierran_sin_cambiar(self):
        self.assertEqual(self.m.tecla(tp.KEY_ESC), [])
        self.assertFalse(self.m.abierto)
        self.m.abrir(LISTA, "rhodes")
        self.assertEqual(self.m.tecla(F), [])
        self.assertFalse(self.m.abierto)

    def test_busqueda_sin_tildes_y_por_categoria(self):
        for c in (O_, R, G_):                       # "org"
            self.m.tecla(c)
        self.assertEqual(self.m.filtro, "org")
        self.assertEqual([i["id"] for i in self.m.visibles()], ["hammond-drawbar", "iglesia"],
                         "«org» encuentra la categoría Órganos y «Órgano de iglesia»")
        self.m.tecla(DOWN_)
        self.assertEqual(self.m.tecla(tp.KEY_ENTER), [("router", "instrumento ya iglesia")])
        self.m.abrir(LISTA, "rhodes")
        for c in (34, 18):                          # "ge" -> nada... luego borrar
            self.m.tecla(c)
        self.m.tecla(tp.KEY_BACKSPACE)
        self.assertEqual(self.m.filtro, "g")
        self.m.tecla(tp.KEY_BACKSPACE)
        self.assertEqual(self.m.filtro, "")
        self.assertEqual(self.elegido(), "rhodes", "sin filtro vuelve a la categoría")

    def test_busqueda_sin_resultados_y_limite(self):
        for c in (Q, Q, Q):
            self.m.tecla(c)
        self.assertEqual(self.m.visibles(), [])
        self.assertEqual(self.m.tecla(tp.KEY_ENTER), [], "sin resultados, ENTER no hace nada")
        self.assertTrue(self.m.abierto)
        for _ in range(40):
            self.m.tecla(Q)
        self.assertEqual(len(self.m.filtro), tp.MenuInstrumentos.MAX_FILTRO)

    def test_normalizar(self):
        self.assertEqual(tp.normalizar("Órgano de IGLESIA"), "organo de iglesia")
        self.assertEqual(tp.normalizar("Vibráfono"), "vibrafono")


class TestInterpreteConMenu(unittest.TestCase):
    def setUp(self):
        self.i = tp.Interprete(instrumentos=lambda: (LISTA, "salamander"))

    def test_f9_abre_y_las_letras_no_tocan_notas(self):
        self.assertEqual(self.i.evento(F, 1), [])
        self.assertTrue(self.i.menu.abierto)
        self.assertEqual(self.i.evento(A, 1), [], "con el menú abierto, A busca: no suena")
        self.assertEqual(self.i.menu.filtro, "a")
        self.assertEqual(self.i.evento(A, 0), [])
        self.assertEqual(self.i.sonando, {})

    def test_esc_en_el_menu_no_sale_del_piano(self):
        self.i.evento(F, 1)
        self.assertEqual(self.i.evento(tp.KEY_ESC, 1), [])
        self.assertFalse(self.i.menu.abierto)
        self.assertEqual(self.i.evento(tp.KEY_ESC, 2), [], "la repetición de ESC tampoco")
        self.assertEqual(self.i.evento(tp.KEY_ESC, 1)[-1], ("salir",), "con el menú cerrado, ESC sale")

    def test_teclas_pulsadas_antes_de_abrir_se_sueltan(self):
        self.i.evento(A, 1)
        self.i.evento(tp.KEY_SPACE, 1)
        self.i.evento(F, 1)
        self.assertEqual(self.i.evento(A, 0), [("off", 60)], "la nota se apaga aunque el menú esté abierto")
        self.assertEqual(self.i.evento(tp.KEY_SPACE, 0), [("cc", 64, 0)], "y el pedal se suelta")

    def test_enter_carga_y_vuelve_a_tocar(self):
        self.i.evento(F, 1)
        self.i.evento(DOWN_, 1)
        self.assertEqual(self.i.evento(tp.KEY_ENTER, 1), [("router", "instrumento ya headroom")])
        self.assertEqual(self.i.evento(tp.KEY_ENTER, 2), [], "la repetición de ENTER no hace nada más")
        self.assertEqual(self.i.evento(A, 1), [("on", 60, 80)])

    def test_flechas_con_repeticion_en_el_menu(self):
        self.i.evento(F, 1)
        self.i.evento(DOWN_, 2)
        self.assertEqual(self.i.menu.idx, 1, "mantener la flecha recorre la lista")
        self.assertEqual(self.i.evento(tp.KEY_UP, 1), [], "las flechas no cambian el volumen con el menú abierto")

    def test_sin_lista_f9_no_abre(self):
        i = tp.Interprete()
        self.assertEqual(i.evento(F, 1), [])
        self.assertFalse(i.menu.abierto)
        i2 = tp.Interprete(instrumentos=lambda: ([], None))
        i2.evento(F, 1)
        self.assertFalse(i2.menu.abierto)


class TestApagarConF12(unittest.TestCase):
    """Fase 11: F12 pide confirmar y solo S apaga; nada suena mientras se pregunta."""

    def setUp(self):
        self.i = tp.Interprete(instrumentos=lambda: (LISTA, "salamander"))

    def test_f12_pregunta_y_s_apaga_soltando_lo_que_suena(self):
        self.assertEqual(self.i.evento(A, 1), [("on", 60, 80)])
        self.i.evento(tp.KEY_SPACE, 1)
        self.assertEqual(self.i.evento(tp.KEY_F12, 1), [])
        self.assertTrue(self.i.confirmar.abierto)
        self.assertEqual(self.i.evento(tp.KEY_S, 1), [("off", 60), ("cc", 64, 0), ("apagar",)],
                         "antes de apagar se suelta todo (nada queda sonando)")
        self.assertFalse(self.i.confirmar.abierto)

    def test_n_esc_o_f12_cancelan_sin_salir(self):
        for tecla in (tp.KEY_N, tp.KEY_ESC, tp.KEY_F12):
            self.i.evento(tp.KEY_F12, 1)
            self.assertEqual(self.i.evento(tecla, 1), [], f"{tecla}: cancela")
            self.assertFalse(self.i.confirmar.abierto)
        self.assertEqual(self.i.evento(A, 1), [("on", 60, 80)], "y se sigue tocando")

    def test_mientras_pregunta_no_suena_nada_ni_cambia_nada(self):
        self.i.evento(tp.KEY_F12, 1)
        for tecla in (A, W, J, tp.KEY_UP, tp.KEY_F6, tp.KEY_BACKSPACE, tp.KEY_ENTER, tp.KEY_F9):
            self.assertEqual(self.i.evento(tecla, 1), [], f"{tecla} no hace nada mientras se pregunta")
        self.assertEqual(self.i.sonando, {})
        self.assertFalse(self.i.menu.abierto)
        self.assertTrue(self.i.confirmar.abierto, "sigue preguntando")
        self.assertEqual(self.i.evento(tp.KEY_S, 2), [], "la repetición de una tecla no confirma")
        self.assertTrue(self.i.confirmar.abierto)

    def test_soltar_teclas_pulsadas_antes_de_preguntar(self):
        self.i.evento(A, 1)
        self.i.evento(tp.KEY_F12, 1)
        self.assertEqual(self.i.evento(A, 0), [("off", 60)], "la nota se apaga aunque se esté preguntando")

    def test_con_un_menu_abierto_f12_no_pregunta(self):
        self.i.evento(tp.KEY_F9, 1)
        self.assertEqual(self.i.evento(tp.KEY_F12, 1), [])
        self.assertFalse(self.i.confirmar.abierto, "primero se cierra el menú")

    def test_ventana_y_ayuda(self):
        for l in tp.LINEAS_APAGAR:
            self.assertFalse({ch for ch in l if ch not in CP437}, l)
        self.assertIn("S   sí, apagar", tp.LINEAS_APAGAR)
        self.assertIn(("Salir", "ESC        F12 apagar la Pi"), tp.lineas_controles())
        self.assertLessEqual(len("ESC        F12 apagar la Pi"), tp.ANCHO_VALOR)
        self.assertIn("F12 apagar", tp.AYUDA)
        self.assertEqual(tp.ALTO_MINIMO, 33, "sin filas nuevas: sigue cabiendo en el monitor")
        self.assertEqual(tp.CODIGO_APAGAR, 10)


class TestTeclasDeControl(unittest.TestCase):
    def setUp(self):
        self.i = tp.Interprete()

    def test_flechas_volumen_y_reverb_con_repeticion(self):
        self.assertEqual(self.i.evento(tp.KEY_UP, 1), [("volumen", 1)])
        self.assertEqual(self.i.evento(tp.KEY_UP, 2), [("volumen", 1)], "mantener la flecha repite")
        self.assertEqual(self.i.evento(tp.KEY_UP, 0), [])
        self.assertEqual(self.i.evento(tp.KEY_DOWN, 1), [("volumen", -1)])
        self.assertEqual(self.i.evento(tp.KEY_RIGHT, 1), [("reverb", 1)])
        self.assertEqual(self.i.evento(tp.KEY_LEFT, 2), [("reverb", -1)])
        self.assertEqual(self.i.sonando, {}, "las flechas no tocan notas")

    def test_teclas_de_funcion_tab_y_enter(self):
        self.assertEqual(self.i.evento(tp.KEY_F1, 1), [("router", "transponer -1")])
        self.assertEqual(self.i.evento(tp.KEY_F2, 1), [("router", "transponer +1")])
        self.assertEqual(self.i.evento(tp.KEY_F3, 1), [("router", "curva siguiente")])
        self.assertEqual(self.i.evento(tp.KEY_F4, 1), [("router", "latencia siguiente")])
        self.assertEqual(self.i.evento(tp.KEY_F5, 1), [("router", "auto")])
        self.assertEqual(self.i.evento(tp.KEY_F6, 1), [("router", "instrumento anterior")])
        self.assertEqual(self.i.evento(tp.KEY_F7, 1), [("router", "instrumento siguiente")])
        self.assertEqual(self.i.evento(tp.KEY_F7, 2), [], "mantener F7 no recorre la lista solo")
        self.assertEqual(self.i.evento(tp.KEY_F1, 2), [], "sin repetición en las teclas de función")
        self.assertEqual(self.i.evento(tp.KEY_F1, 0), [])
        self.assertEqual(self.i.evento(tp.KEY_TAB, 1), [("seleccion", 1)])
        self.assertEqual(self.i.evento(tp.KEY_ENTER, 1), [("alternar_seleccion",)])

    def test_retroceso_es_panico_local_y_del_enrutador(self):
        self.i.evento(A, 1)
        self.i.evento(tp.KEY_SPACE, 1)
        msgs = self.i.evento(tp.KEY_BACKSPACE, 1)
        self.assertCountEqual(msgs, [("off", 60), ("cc", 64, 0), ("cc", 123, 0), ("cc", 120, 0),
                                     ("router", "panico")])
        self.assertEqual((self.i.sonando, self.i.pedal), ({}, False))
        self.assertEqual(tp.Interprete().evento(tp.KEY_BACKSPACE, 1),
                         [("cc", 64, 0), ("cc", 123, 0), ("cc", 120, 0), ("router", "panico")])
        self.assertEqual(self.i.evento(tp.KEY_BACKSPACE, 2), [])


class TestEventoSeq(unittest.TestCase):
    def test_tamano_y_desplazamientos(self):
        self.assertEqual(ctypes.sizeof(tp.EventoSeq), 28)
        self.assertEqual(tp.EventoSeq.time.offset, 4)
        self.assertEqual(tp.EventoSeq.source.offset, 12)
        self.assertEqual(tp.EventoSeq.dest.offset, 14)
        self.assertEqual(tp.EventoSeq.data.offset, 16)

    def test_nota_on_y_off(self):
        b = bytes(tp.construir_evento(("on", 60, 100), puerto=3))
        self.assertEqual(b[0], tp.SEQ_EVENT_NOTEON)
        self.assertEqual(b[3], tp.SEQ_QUEUE_DIRECT)
        self.assertEqual(b[12:16], bytes([0, 3, tp.SEQ_ADDRESS_SUBSCRIBERS, tp.SEQ_ADDRESS_UNKNOWN]))
        self.assertEqual(b[16:20], bytes([0, 60, 100, 0]))
        off = bytes(tp.construir_evento(("off", 60), puerto=3))
        self.assertEqual(off[0], tp.SEQ_EVENT_NOTEOFF)
        self.assertEqual(off[16:19], bytes([0, 60, 0]))

    def test_controlador(self):
        b = bytes(tp.construir_evento(("cc", 64, 127), puerto=0))
        self.assertEqual(b[0], tp.SEQ_EVENT_CONTROLLER)
        self.assertEqual(struct.unpack_from("<Ii", b, 20), (64, 127))

    def test_mensaje_invalido(self):
        with self.assertRaises(ValueError):
            tp.construir_evento(("salir",), 0)


class TestLectorEvdev(unittest.TestCase):
    def test_eventos_y_lecturas_parciales(self):
        datos = (tp.empaquetar_evento(A, 1) + tp.empaquetar_evento(0, 0, tipo=0) + tp.empaquetar_evento(A, 0))
        lector = tp.LectorEvdev()
        corte = tp.TAM_EVDEV + 5
        self.assertEqual(lector.alimentar(datos[:corte]), [(A, 1)])
        self.assertEqual(lector.alimentar(datos[corte:]), [(A, 0)])
        self.assertEqual(lector.pendiente, b"")

    @unittest.skipUnless(ES_LINUX and struct.calcsize("l") == 8, "struct input_event de Linux 64 bits")
    def test_tamano_input_event_linux64(self):
        self.assertEqual(tp.TAM_EVDEV, 24)


class TestGeometria(unittest.TestCase):
    def test_teclado_de_4_octavas(self):
        t = tp.teclas_vista(48, 4, 4, sonando={60, 61}, etiquetas=tp.etiquetas_pc(4))
        blancas = [k for k in t if not k["negra"]]
        negras = [k for k in t if k["negra"]]
        self.assertEqual((len(blancas), len(negras)), (29, 20), "4 octavas + el Do final")
        self.assertEqual((blancas[0]["nota"], blancas[-1]["nota"]), (48, 96))
        self.assertEqual(t.index(negras[0]), 29, "las negras van después: se dibujan encima")
        self.assertTrue([k for k in t if k["nota"] == 60][0]["sonando"])
        self.assertTrue([k for k in t if k["nota"] == 61][0]["sonando"])
        self.assertEqual([k for k in t if k["nota"] == 60][0]["etiqueta"], "A")
        self.assertEqual([k for k in t if k["nota"] == 61][0]["etiqueta"], "W")
        self.assertEqual([k for k in t if k["nota"] == 48][0]["etiqueta"], "", "fuera de la zona del PC")
        for n in negras:
            self.assertEqual((n["x"] + n["ancho"] // 2) % 4, 0, "cada negra sobre la frontera de dos blancas")
            self.assertLessEqual(n["x"] + n["ancho"], 29 * 4)

    def test_nombres_segun_ancho(self):
        estrecho = [k for k in tp.teclas_vista(48, 4, 4) if not k["negra"]]
        self.assertEqual(estrecho[4]["nombre"], "So3", "con 3 columnas se abrevia Sol")
        self.assertTrue(all(len(k["nombre"]) <= 3 for k in estrecho))
        ancho = [k for k in tp.teclas_vista(48, 4, 6) if not k["negra"]]
        self.assertEqual(ancho[4]["nombre"], "Sol3")

    def test_inicio_y_transposicion(self):
        self.assertEqual(tp.inicio_teclado(4), 48, "una octava por debajo de la zona del PC")
        self.assertEqual(tp.inicio_teclado(0), 12, "no baja de Do0")
        self.assertEqual(tp.inicio_teclado(7), 60, "no pasa de Do8")
        self.assertEqual(tp.inicio_teclado(4, transposicion=12), 60)
        self.assertEqual(tp.etiquetas_pc(4, transposicion=2)[62], "A", "las letras siguen a la transposición")

    def test_ancho_de_teclas(self):
        self.assertEqual(tp.ancho_teclas(120), 4, "monitor 1080p con fuente 16x32")
        self.assertEqual(tp.ancho_teclas(240), 8)
        self.assertEqual(tp.ancho_teclas(100), 0, "no cabe")
        self.assertLessEqual((7 * tp.N_OCTAVAS + 1) * tp.ancho_teclas(120) + 1, 120)

    def test_mapa_88(self):
        m = tp.mapa_88(48, 96, {60, 21})
        self.assertEqual(len(m), 88)
        self.assertEqual((m[0], m[60 - 21], m[61 - 21], m[47 - 21]), ("█", "█", "═", "·"))


class Resultado:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode = stdout, returncode


class EjecutorFalso:
    """Simula wpctl y vcgencmd."""

    def __init__(self, volumen="0.30", throttled="0x0", falla=False, lento=False, set_falla=False):
        self.vol, self.thr, self.falla, self.llamadas = volumen, throttled, falla, []
        self.lento, self.set_falla = lento, set_falla

    def __call__(self, args):
        self.llamadas.append(args)
        if self.falla:
            raise FileNotFoundError(args[0])
        if args[:2] == ["wpctl", "get-volume"]:
            return Resultado(f"Volume: {self.vol}\n")
        if args[:2] == ["wpctl", "set-volume"]:
            if self.set_falla:
                return Resultado("", returncode=1)
            if not self.lento:
                self.vol = args[3]
            return Resultado("")
        if args[:2] == ["vcgencmd", "get_throttled"]:
            return Resultado(f"throttled={self.thr}\n")
        return Resultado("")


ESTADO_ROUTER = {
    "fuentes": [{"id": "Teclado Piano:notas", "nombre": "Teclado Piano", "tipo": "pc", "activa": True, "conectada": True},
                {"id": "Roland FP:MIDI 1", "nombre": "Roland FP", "tipo": "midi", "activa": False, "conectada": True}],
    "auto_nuevas": True, "transposicion": 2, "curva": "dura", "latencia": 512, "reverb": 0.4,
    "sonando": [62, 66], "pedal": True, "ultima": [66, 70, "Roland FP"], "xruns": 3, "xrun_hace": 4.0, "bq": 0.4}
NOMBRE_LARGO = "Kawai vertical (Upright KW)"          # el más largo del catálogo real
INSTRUMENTO = {"actual": {"id": "maestro", "nombre": "Maestro (Yamaha CF-3)"},
               "elegido": {"id": "maestro", "nombre": "Maestro (Yamaha CF-3)"},
               "cargando": None, "estado": "listo", "error": None, "posicion": 3, "total": 10}


class ConRouter(unittest.TestCase):
    """Crea un estado de enrutador en disco y (en Linux) un FIFO de órdenes con lector."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.json = os.path.join(self.d.name, "router.json")
        with open(self.json, "w") as f:
            json.dump(ESTADO_ROUTER, f)
        self.fifo = os.path.join(self.d.name, "router.ctl")
        self.lector = None
        if ES_LINUX:
            os.mkfifo(self.fifo)
            self.lector = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)

    def tearDown(self):
        if self.lector is not None:
            os.close(self.lector)
        self.d.cleanup()

    def controles(self, **kw):
        return tp.Controles(ejecutar=EjecutorFalso("0.30"), ctl_router=self.fifo, estado_router=self.json, **kw)

    def ordenes(self):
        try:
            return os.read(self.lector, 10000).decode()
        except BlockingIOError:
            return ""


SALIDA = {"estado": "lista", "aviso": None, "error": None, "tasa": 44100, "destino": None,
          "activa": {"nombre": "usb-g432", "visible": "G432 Gaming Headset", "id": 80, "tipo": "usb"},
          "lista": [{"nombre": "usb-g432", "visible": "G432 Gaming Headset", "tipo": "usb", "aviso": None,
                     "activa": True},
                    {"nombre": "usb-g1", "visible": "Sound BlasterX G1", "tipo": "usb", "aviso": None, "activa": False},
                    {"nombre": "pi-jack", "visible": "Auriculares de la Pi (3,5 mm)", "tipo": "pi",
                     "aviso": "salida de la Pi: calidad limitada", "activa": False}]}


class TestSalidaDeAudio(ConRouter):
    """Fase 10: menú F10, fila «Salida», ventanas de cambio y desconexión, volumen de la tarjeta activa."""

    def escribir(self, **salida):
        with open(self.json, "w") as f:
            json.dump(dict(ESTADO_ROUTER, salida=dict(SALIDA, **salida)), f)

    def test_menu_f10(self):
        m = tp.MenuSalidas()
        m.abrir(SALIDA["lista"])
        self.assertEqual((m.abierto, m.idx), (True, 0), "se abre en la que suena")
        self.assertEqual(m.tecla(UP_), [])
        self.assertEqual(m.idx, 2, "circular")
        m.tecla(DOWN_)
        m.tecla(DOWN_)
        self.assertEqual(m.tecla(tp.KEY_ENTER), [("router", "salida usb-g1")])
        self.assertFalse(m.abierto)
        m.abrir(SALIDA["lista"])
        self.assertEqual(m.tecla(tp.KEY_ENTER), [], "ENTER en la que ya suena: solo cierra")
        self.assertFalse(m.abierto)
        for tecla in (tp.KEY_ESC, tp.KEY_F10):
            m.abrir(SALIDA["lista"])
            m.tecla(tecla)
            self.assertFalse(m.abierto)

    def test_interprete_f10(self):
        i = tp.Interprete(salidas=lambda: SALIDA["lista"], instrumentos=lambda: (LISTA, "rhodes"))
        self.assertEqual(i.evento(A, 1), [("on", 60, 80)])
        self.assertEqual(i.evento(tp.KEY_F10, 1), [])
        self.assertTrue(i.menu_salida.abierto)
        self.assertEqual(i.evento(F, 1), [], "con F10 abierto, F9 no abre el otro menú")
        self.assertFalse(i.menu.abierto)
        self.assertEqual(i.evento(S, 1), [], "las letras no tocan")
        self.assertEqual(i.evento(A, 0), [("off", 60)], "la nota pulsada antes de abrir se suelta igual")
        self.assertEqual(i.evento(DOWN_, 1), [])
        self.assertEqual(i.evento(tp.KEY_ENTER, 1), [("router", "salida usb-g1")])
        self.assertFalse(i.menu_salida.abierto)
        self.assertEqual(tp.Interprete().evento(tp.KEY_F10, 1), [], "sin salidas publicadas no se abre")

    def test_fila_salida(self):
        self.assertEqual(tp.lineas_salida(None), [], "modo silencio: sin fila")
        self.assertEqual(tp.lineas_salida(SALIDA), [("Salida", "G432 Gaming Headset", False)])
        filas = tp.lineas_salida(dict(SALIDA, aviso="la salida elegida no está conectada: se usa G432 Gaming Headset"))
        self.assertEqual(filas[0], ("Salida", "G432 Gaming Headset", True))
        self.assertTrue(all(aviso for _, _, aviso in filas) and len(filas) == 3, "el aviso, en rojo, en dos filas")
        filas = tp.lineas_salida(dict(SALIDA, error="Tarjeta 48k necesita 48 kHz: se usará al volver a abrir el piano"))
        self.assertIn("necesita 48 kHz", " ".join(t for _, t, _ in filas))
        self.assertEqual(tp.lineas_salida(dict(SALIDA, estado="desconectada")),
                         [("Salida", "G432 Gaming Headset (desconec", True)])
        for etiqueta, texto, _ in tp.lineas_salida(dict(SALIDA, aviso="x" * 80)):
            self.assertLessEqual(len(texto), tp.ANCHO_VALOR)

    def test_ventanas(self):
        self.escribir(estado="cambiando", destino="Sound BlasterX G1")
        c = self.controles()
        self.assertEqual(tp.lineas_modal(c)[:3], ["Cambiando la salida de audio", "", "Sound BlasterX G1"])
        self.escribir(estado="desconectada")
        c.leer_router()
        self.assertEqual(tp.lineas_modal(c)[0], "Salida de audio desconectada")
        self.assertIn("F10", tp.lineas_modal(c)[-1])
        self.assertIsNone(tp.lineas_modal(c, menu_abierto=True), "con el menú abierto no tapa: se puede elegir otra")
        self.escribir()
        c.leer_router()
        self.assertIsNone(tp.lineas_modal(c))
        for lineas in (["Cambiando la salida de audio", "Salida de audio desconectada", "El piano está en pausa un momento",
                        "Vuelve a conectarla o elige otra con F10"],):
            for l in lineas:
                self.assertFalse({ch for ch in l if ch not in CP437}, l)

    def test_filas_del_menu(self):
        m = tp.MenuSalidas()
        m.abrir(SALIDA["lista"])
        filas = tp.lineas_menu_salidas(m)
        self.assertEqual(len(filas), 2 + tp.MENU_SALIDAS_FILAS + 3, "alto fijo")
        sel = [t for t, e in filas if e == "sel"]
        self.assertEqual(len(sel), 1)
        self.assertIn("G432 Gaming Headset", sel[0])
        self.assertIn("(suena ahora)", sel[0])
        m.tecla(UP_)                                      # a los auriculares de la Pi: su aviso, resaltado
        filas = tp.lineas_menu_salidas(m)
        self.assertIn((" Aviso: salida de la Pi: calidad limitada", "restringido"), filas)
        for t, _ in filas:
            self.assertLessEqual(len(t), tp.ANCHO_PANELES)
            self.assertFalse({ch for ch in t if ch not in CP437}, t)
        vacio = tp.MenuSalidas()
        vacio.abrir([])
        self.assertTrue(any("ninguna salida" in t for t, _ in tp.lineas_menu_salidas(vacio)))
        self.assertLessEqual(1 + len(filas), 33, "el menú cabe en la pantalla")

    def test_volumen_de_la_tarjeta_activa(self):
        self.escribir()
        e = EjecutorFalso("0.40")
        c = tp.Controles(ejecutar=e, ctl_router=self.fifo, estado_router=self.json)
        self.assertEqual(c.destino_volumen(), "80")
        self.assertIn(["wpctl", "get-volume", "80"], e.llamadas, "se lee el volumen de la tarjeta del piano")
        c.cambiar_volumen(+1)
        self.assertIn(["wpctl", "set-volume", "80", "0.45"], e.llamadas)
        self.escribir(activa={"nombre": "usb-g1", "visible": "Sound BlasterX G1", "id": 81, "tipo": "usb"})
        e.llamadas.clear()
        c.leer_router()
        self.assertIn(["wpctl", "get-volume", "81"], e.llamadas, "otra tarjeta: se vuelve a leer su volumen")
        e.llamadas.clear()
        c.leer_router()
        self.assertNotIn(["wpctl", "get-volume", "81"], e.llamadas, "sin cambio, no se relee en cada vuelta")
        self.assertEqual(tp.Controles(ejecutar=EjecutorFalso()).destino_volumen(), "@DEFAULT_AUDIO_SINK@",
                         "sin enrutador: la salida por defecto")

    def test_latencia_con_la_tasa_de_la_salida(self):
        self.escribir(tasa=48000)
        filas = dict((e, t) for e, t, _ in tp.lineas_sonido(self.controles()))
        self.assertEqual(filas["Latencia"], "512 (10,7 ms)", "a 48 kHz, el mismo bloque dura menos")
        self.assertEqual(filas["Salida"], "G432 Gaming Headset")

    def test_ayuda_y_alto(self):
        self.assertIn(("Salida", "F10 tarjeta de sonido"), tp.lineas_controles())
        self.assertEqual(tp.ALTO_MINIMO, 33, "cabe justo en el monitor (1080/32 = 33 filas)")


class TestControles(ConRouter):
    def test_volumen_lectura_pasos_y_limites(self):
        e = EjecutorFalso("0.30")
        c = tp.Controles(ejecutar=e)
        self.assertAlmostEqual(c.volumen, 0.30)
        c.cambiar_volumen(+1)
        self.assertIn(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.35"], e.llamadas)
        for _ in range(30):
            c.cambiar_volumen(+1)
        self.assertAlmostEqual(c.volumen, tp.Controles.VOLUMEN_MAX)
        for _ in range(30):
            c.cambiar_volumen(-1)
        self.assertAlmostEqual(c.volumen, 0.0)

    def test_volumen_con_wireplumber_lento_y_fallo(self):
        e = EjecutorFalso("0.30", lento=True)
        c = tp.Controles(ejecutar=e, reloj=lambda: 0.0)
        c.cambiar_volumen(-1)
        self.assertAlmostEqual(c.volumen, 0.25, msg="muestra el valor pedido")
        e.vol = "0.60"
        c._t_sistema = -10
        c.actualizar_sistema()
        self.assertAlmostEqual(c.volumen, 0.60, msg="la relectura periódica refleja cambios externos")
        f = tp.Controles(ejecutar=EjecutorFalso("0.30", set_falla=True))
        f.cambiar_volumen(+1)
        self.assertAlmostEqual(f.volumen, 0.30)

    def test_volumen_agrupado_al_mantener_la_flecha(self):
        t = [0.0]
        e = EjecutorFalso("0.30")
        c = tp.Controles(ejecutar=e, reloj=lambda: t[0])
        ordenes = lambda: [a[3] for a in e.llamadas if a[:2] == ["wpctl", "set-volume"]]
        c.cambiar_volumen(+1)
        self.assertEqual(ordenes(), ["0.35"], "el primer paso sale al instante")
        for _ in range(4):                       # repetición automática: un paso cada 30 ms (0,12 s en total)
            t[0] += 0.03
            c.cambiar_volumen(+1)
        self.assertEqual(ordenes(), ["0.35"], "los pasos seguidos no generan una orden cada uno")
        self.assertAlmostEqual(c.volumen, 0.55, msg="pero se ven al instante")
        t[0] += 0.04
        c.aplicar_volumen()
        self.assertEqual(ordenes(), ["0.35", "0.55"], "pasado el intervalo sale el valor final")
        t[0] += 0.05
        c.cambiar_volumen(-1)
        c._t_sistema = -10
        c.actualizar_sistema()
        self.assertAlmostEqual(c.volumen, 0.50, msg="la relectura no pisa un cambio aún sin enviar")
        t[0] += 0.2
        c.actualizar_sistema()
        self.assertEqual(ordenes()[-1], "0.50", "el bucle de la interfaz envía el pendiente")
        n = len(ordenes())
        c.actualizar_sistema()
        self.assertEqual(len(ordenes()), n, "sin cambios, sin órdenes")

    def test_volumen_pendiente_se_envia_al_salir(self):
        t = [0.0]
        e = EjecutorFalso("0.30")
        c = tp.Controles(ejecutar=e, reloj=lambda: t[0])
        c.cambiar_volumen(+1)
        c.cambiar_volumen(+1)
        c.aplicar_volumen(forzar=True)
        self.assertEqual([a[3] for a in e.llamadas if a[:2] == ["wpctl", "set-volume"]], ["0.35", "0.40"])

    def test_volumen_mudo_y_sin_wpctl(self):
        self.assertTrue(tp.Controles(ejecutar=EjecutorFalso("0.40 [MUTED]")).silenciado)
        sin = tp.Controles(ejecutar=EjecutorFalso(falla=True))
        sin.cambiar_volumen(+1)
        self.assertIsNone(sin.volumen)

    def test_lee_estado_del_enrutador(self):
        c = self.controles()
        self.assertEqual(c.router["curva"], "dura")
        self.assertEqual(c.reverb, 0.4, "la reverb viene del enrutador")
        self.assertEqual(len(c.fuentes()), 2)
        os.remove(self.json)
        c.leer_router()
        self.assertIsNone(c.router, "sin enrutador no falla")
        self.assertEqual(c.fuentes(), [])

    @unittest.skipUnless(ES_LINUX, "FIFO")
    def test_ordenes_al_enrutador(self):
        c = self.controles()
        c.aplicar(("router", "transponer +1"))
        c.aplicar(("reverb", +1))
        self.assertEqual(self.ordenes(), "transponer +1\nreverb +1\n")
        self.assertEqual(c.reverb, 0.45, "se ve al instante")
        c.aplicar(("seleccion", 1))
        self.assertEqual(c.seleccion, 1)
        c.aplicar(("alternar_seleccion",))
        self.assertEqual(self.ordenes(), "fuente alternar Roland FP:MIDI 1\n")
        c.aplicar(("seleccion", 1))
        self.assertEqual(c.seleccion, 0, "la selección da la vuelta")

    def test_seleccion_se_ajusta_si_desaparecen_fuentes(self):
        c = self.controles()
        c.seleccion = 1
        with open(self.json, "w") as f:
            json.dump(dict(ESTADO_ROUTER, fuentes=ESTADO_ROUTER["fuentes"][:1]), f)
        c.leer_router()
        self.assertEqual(c.seleccion, 0)

    @unittest.skipUnless(ES_LINUX, "FIFO")
    def test_reverb_sin_enrutador_va_a_jalv(self):
        fifo = os.path.join(self.d.name, "jalv")
        os.mkfifo(fifo)
        lector = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        try:
            c = tp.Controles(ejecutar=EjecutorFalso(), ctl_reverb=fifo, reverb=0.35)
            c.aplicar(("reverb", +1))
            self.assertEqual(os.read(lector, 100), b"mix = 0.40\n")
        finally:
            os.close(lector)
        c.cambiar_reverb(-1)
        self.assertIsNone(c.ctl_reverb, "sin lector se desactiva sin fallar")

    def test_desde_estado(self):
        ruta = os.path.join(self.d.name, "estado")
        with open(ruta, "w") as f:
            f.write(f"reverb_ctl=/x.ctl\nreverb_mix=0.35\nrouter_ctl={self.fifo}\nrouter_estado={self.json}\n")
        c = tp.Controles.desde_estado(ruta, ejecutar=EjecutorFalso())
        self.assertEqual((c.ctl_reverb, c.ctl_router, c.estado_router), ("/x.ctl", self.fifo, self.json))
        self.assertEqual(c.router["transposicion"], 2)

    def test_estado_del_sistema(self):
        termica, stat = os.path.join(self.d.name, "temp"), os.path.join(self.d.name, "stat")
        with open(termica, "w") as f:
            f.write("56400\n")
        with open(stat, "w") as f:
            f.write("cpu  100 0 100 800 0 0 0 0 0 0\n")
        reloj = [0.0]
        c = tp.Controles(ejecutar=EjecutorFalso(throttled="0x50005"), termica=termica, stat=stat,
                         reloj=lambda: reloj[0])
        c.actualizar_sistema()
        self.assertAlmostEqual(c.temp, 56.4)
        self.assertTrue(c.bajo_voltaje_ahora and c.limitado_ahora and c.bajo_voltaje_hubo)
        with open(stat, "w") as f:
            f.write("cpu  150 0 150 900 0 0 0 0 0 0\n")
        reloj[0] = 2.5
        c.actualizar_sistema()
        self.assertEqual(c.cpu, 50)


class TestPaneles(ConRouter):
    def test_estado_sonido_y_entradas(self):
        c = self.controles()
        c.temp, c.cpu = 61.2, 40
        i = tp.Interprete()
        est = {e: (t, a) for e, t, a in tp.lineas_estado(i, c)}
        self.assertIn("30%", est["Volumen"][0])
        self.assertIn("40%", est["Reverb"][0])
        self.assertEqual(est["Pedal"], ("PISADO", True), "el pedal viene del enrutador (también del teclado MIDI)")
        self.assertIn("Roland FP", est["Ultima"][0])
        self.assertIn("61°C", est["Sistema"][0])
        son = {e: (t, a) for e, t, a in tp.lineas_sonido(c)}
        self.assertEqual(son["Transp."], ("+2 semitonos", True))
        self.assertEqual(son["Curva"][0], "dura")
        self.assertEqual(son["Latencia"][0], "512 (11,6 ms)")
        self.assertEqual(son["Cortes"], ("3 (último hace 4 s)", True), "un corte reciente se resalta")
        ent = tp.lineas_entradas(c)
        self.assertEqual(len(ent), 2)
        self.assertTrue(ent[0][0].startswith("> [x] Teclado Piano (PC)"))
        self.assertTrue(ent[1][0].startswith("  [ ] Roland FP (MIDI)"))

    def test_sin_enrutador(self):
        c = tp.Controles(ejecutar=EjecutorFalso())
        self.assertEqual(tp.lineas_sonido(c), [("Enrutador", "no disponible", True)])
        self.assertEqual(tp.lineas_entradas(c)[0][0].strip(), "(sin entradas detectadas)")
        self.assertEqual(len(tp.lineas_estado(tp.Interprete())), 4, "sin controles: solo el teclado")

    def test_desconectado_y_nombres_largos(self):
        c = self.controles()
        c.router["fuentes"][1].update(conectada=False, nombre="Un teclado MIDI con un nombre larguísimo")
        texto = tp.lineas_entradas(c)[1][0]
        self.assertLessEqual(len(texto), tp.ANCHO_COLUMNA)
        self.assertTrue(texto.endswith("(MIDI) desconect."))

    def test_todo_cabe_en_su_columna_y_en_cp437(self):
        c = self.controles()
        c.temp, c.cpu, c.bajo_voltaje_ahora, c.silenciado = 61.2, 100, True, True
        textos = []
        for etiqueta, texto, _ in tp.lineas_estado(tp.Interprete(), c) + tp.lineas_sonido(c):
            self.assertLessEqual(9 + len(texto), tp.ANCHO_COLUMNA, texto)
            textos.append(etiqueta + texto)
        for tecla, accion in tp.lineas_controles():
            self.assertLessEqual(9 + len(accion), tp.ANCHO_COLUMNA, accion)
            textos.append(tecla + accion)
        textos += [t for t, *_ in tp.lineas_entradas(c)]
        textos += [k["nombre"] + k["etiqueta"] for k in tp.teclas_vista(12, 4, 4, etiquetas=tp.etiquetas_pc(4))]
        textos += [tp.mapa_88(48, 96, {60}), tp.barra(0.5), "ESTADO SONIDO ENTRADAS MIDI CONTROLES ─│"]
        for t in textos:
            self.assertFalse({ch for ch in t if ch not in CP437}, t)

    def test_instrumento_en_el_panel_sonido(self):
        c = self.controles()
        c.router["instrumento"] = dict(INSTRUMENTO)
        filas = tp.lineas_sonido(c)
        self.assertEqual(filas[0], ("Sonido", "Maestro (Yamaha CF-3)", False))
        self.assertEqual(filas[1], ("", "3 de 10   F6/F7 cambiar", False))
        self.assertEqual(filas[2][0], "Transp.", "el resto del panel sigue igual")
        estados = {
            "cargando": dict(INSTRUMENTO, estado="cargando", cargando={"id": "u", "nombre": NOMBRE_LARGO}),
            "elegido": dict(INSTRUMENTO, estado="elegido", elegido={"id": "u", "nombre": NOMBRE_LARGO}),
            "error": dict(INSTRUMENTO, estado="error", error=f"no se pudo cargar {NOMBRE_LARGO}"),
        }
        for estado, inst in estados.items():
            with self.subTest(estado=estado):
                filas = tp.lineas_instrumento(inst)
                texto = " ".join(t for e, t, _ in filas if e == "")
                self.assertIn(NOMBRE_LARGO, texto, "el nombre completo se ve, partido en dos filas")
                self.assertTrue(all(len(t) <= tp.ANCHO_VALOR for _, t, _ in filas))
                self.assertLessEqual(len(filas), 3)
                self.assertEqual(any(a for *_, a in filas), estado == "error", "solo el error se resalta")
        self.assertIn("cargando:", tp.lineas_instrumento(estados["cargando"])[1][1])
        self.assertTrue(tp.lineas_instrumento(estados["elegido"])[1][1].startswith("> "))
        sin_actual = tp.lineas_instrumento(dict(INSTRUMENTO, actual=None, estado="cargando",
                                                cargando={"id": "a", "nombre": "A"}))
        self.assertEqual(sin_actual[0], ("Sonido", "(ninguno)", True), "tras un fallo de carga, sin sonido")
        self.assertEqual(tp.lineas_instrumento(None), [])

    def test_progreso_de_carga(self):
        self.assertEqual(tp.progreso_carga(0, 8), 0.0)
        self.assertAlmostEqual(tp.progreso_carga(4, 8), 0.5)
        self.assertAlmostEqual(tp.progreso_carga(7.2, 8), 0.9)
        valores = [tp.progreso_carga(t / 10, 8) for t in range(0, 600)]
        self.assertEqual(valores, sorted(valores), "nunca retrocede")
        self.assertLess(max(valores), 0.99, "no llega al 100 % hasta que la carga termina de verdad")
        self.assertGreater(tp.progreso_carga(16, 8), 0.95, "si tarda más de lo previsto, se acerca al final")
        self.assertEqual(tp.progreso_carga(-1, 8), 0.0)
        self.assertAlmostEqual(tp.progreso_carga(0.5, 0), 0.5, msg="estimación inválida: 1 s")

    def test_ventana_de_carga(self):
        c = self.controles()
        self.assertIsNone(tp.lineas_modal(c), "sin carga, sin ventana")
        c.router["instrumento"] = dict(INSTRUMENTO, estado="cargando",
                                       carga={"id": "osiris", "nombre": "Osiris (vertical)", "inicio": 1000.0,
                                              "estimado_s": 8.0, "despues": None})
        lineas = tp.lineas_modal(c, ahora=1004.0)
        self.assertEqual(lineas[0], "Cargando instrumento")
        self.assertIn("Osiris (vertical)", lineas)
        barra = next(l for l in lineas if "%" in l)
        self.assertTrue(barra.endswith(" 50 %"))
        self.assertEqual(barra.count("█"), tp.ANCHO_BARRA_CARGA // 2)
        self.assertIn("El piano está en pausa hasta que termine", lineas)
        self.assertFalse(any(l.startswith("Después") for l in lineas))
        c.router["instrumento"]["carga"]["despues"] = {"id": "cp80", "nombre": "Yamaha CP80"}
        lineas = tp.lineas_modal(c, ahora=1004.0)
        self.assertEqual(lineas[-1], "Después: Yamaha CP80")
        for l in lineas:
            self.assertLessEqual(len(l) + 8, tp.ANCHO_MINIMO, l)
            self.assertFalse({ch for ch in l if ch not in CP437}, l)
        self.assertIsNone(tp.lineas_modal(None))

    def test_la_tabla_de_la_fuente(self):
        for c in "ÓÁáéíóúñÑ─│┌┐└┘█░═·°←↑→↓":
            self.assertIn(c, CP437, c)
        for c in "▀♪►":
            self.assertNotIn(c, CP437, f"{c} no existe en Terminus: no debe usarse")

    def test_lineas_del_menu(self):
        m = tp.MenuInstrumentos()
        m.abrir(LISTA, "rhodes")
        filas = tp.lineas_menu(m)
        textos = [t for t, _ in filas]
        self.assertIn("[Pianos eléctricos]", textos[1], "pestaña elegida entre corchetes")
        self.assertIn(" Órganos ", textos[1])
        sel = [t for t, e in filas if e == "sel"]
        self.assertEqual(len(sel), 1)
        self.assertIn("> Rhodes Mark I (jRhodes3d)", sel[0])
        self.assertIn("(suena ahora)", sel[0])
        alto = 3 + tp.MENU_FILAS + 1 + tp.MENU_DETALLE + 3
        self.assertEqual(filas[-1], (" Piano Raspberry Pi · creado por Reinaldo Johnson Espinoza, con la ayuda de "
                                     "Claude (Anthropic)", "credito"), "créditos del proyecto al pie, enteros")
        self.assertEqual(len(filas), alto, "alto fijo: el menú no salta al cambiar de categoría")
        detalle = [(t, e) for t, e in filas if e in ("detalle", "restringido")]
        self.assertEqual(detalle, [
            (" Autor     Jeff Learman", "detalle"),
            (" Licencia  Muestras CC BY-NC 4.0 (uso no comercial); SFZ CC0", "detalle"),
            (" Uso       solo uso no comercial", "restringido"),
            (" Fuente    https://github.com/sfzinstruments/jlearman.jRhodes3d", "detalle")],
            "créditos COMPLETOS del sonido marcado, la restricción resaltada")
        m.tecla(RIGHT_)                                  # Órganos: el Hammond de la lista no trae créditos
        filas = tp.lineas_menu(m)
        self.assertEqual(len(filas), alto, "sin créditos, el mismo alto")
        self.assertEqual([t for t, e in filas if e in ("detalle", "restringido")], [""] * tp.MENU_DETALLE)
        m.tecla(LEFT_)
        m.tecla(LEFT_)                                   # Pianos de cola: Salamander, sin restricción
        filas = tp.lineas_menu(m)
        self.assertIn((" Uso       libre; citar al autor", "detalle"), filas)
        self.assertNotIn("restringido", [e for _, e in filas])
        m.tecla(O_)
        m.tecla(R)
        filas = tp.lineas_menu(m)
        self.assertEqual(filas[1][0], " Buscar: or_")
        self.assertTrue(any("Órganos" in t for t, e in filas if e in ("item", "sel")), "en la búsqueda, su categoría")
        for t, _ in filas:
            self.assertLessEqual(len(t), tp.ANCHO_PANELES)
            self.assertFalse({ch for ch in t if ch not in CP437}, t)

    def test_menu_con_muchos_resultados_se_desplaza(self):
        m = tp.MenuInstrumentos()
        muchos = [{"id": f"p{k}", "nombre": f"Piano {k}", "tipo": "cola"} for k in range(20)]
        m.abrir(muchos, "p15")
        filas = tp.lineas_menu(m)
        self.assertTrue(any("> Piano 15" in t for t, _ in filas), "el elegido siempre está a la vista")
        self.assertEqual(sum(1 for _, e in filas if e in ("item", "sel")), tp.MENU_FILAS)

    def test_partir(self):
        self.assertEqual(tp.partir("uno dos tres", 7), ["uno dos", "tres"])
        self.assertEqual(tp.partir("corto", 29), ["corto"])
        self.assertEqual(tp.partir("a b c d e f", 3), ["a b", "c d"], "como máximo dos filas, recortando")
        self.assertEqual(tp.partir("palabralarguísima", 5), ["palab"])

    def test_titulo_con_el_instrumento(self):
        c = self.controles()
        self.assertEqual(tp.titulo_ventana("Piano - Raspberry Pi", c), "Piano - Raspberry Pi")
        c.router["instrumento"] = dict(INSTRUMENTO)
        self.assertEqual(tp.titulo_ventana("Piano - Raspberry Pi", c), "Maestro (Yamaha CF-3) - Raspberry Pi")
        self.assertEqual(tp.titulo_ventana("Base", None), "Base")
        self.assertEqual(tp.titulo_ventana("Base", tp.Controles(ejecutar=EjecutorFalso())), "Base")

    def test_instrumento_cabe_y_en_cp437(self):
        c = self.controles()
        for inst in (dict(INSTRUMENTO, actual={"id": "u", "nombre": NOMBRE_LARGO}),
                     dict(INSTRUMENTO, estado="error", error=f"sin respuesta al cargar {NOMBRE_LARGO}")):
            c.router["instrumento"] = inst
            for etiqueta, texto, _ in tp.lineas_sonido(c):
                self.assertLessEqual(9 + len(texto), tp.ANCHO_COLUMNA, texto)
                self.assertFalse({ch for ch in etiqueta + texto if ch not in CP437}, texto)

    def test_barra(self):
        self.assertEqual(tp.barra(0.5, 10), "█████░░░░░")
        self.assertEqual(tp.barra(None, 4), "????")
        self.assertEqual(tp.barra(2.0, 3), "███")

    def test_pantalla_minima_1080p_terminus(self):
        self.assertLessEqual(tp.ANCHO_MINIMO, 120, "1920/16 = 120 columnas")
        self.assertLessEqual(tp.ALTO_MINIMO, 33, "1080/32 = 33 filas")

    def test_espacio_del_panel_de_creditos(self):
        """En el monitor (33 filas), debajo de ESTADO quedan 7 filas para los créditos; el menú F9, con su detalle,
        también cabe entero."""
        c = self.controles()
        alto_estado = 2 + len(tp.lineas_estado(tp.Interprete(), c))
        y_creditos = 2 + 12 + alto_estado + 1           # título y teclado dibujado (_teclado: y + 12), ESTADO, un hueco
        self.assertEqual(33 - y_creditos - 2, 7)
        self.assertLessEqual(1 + 3 + tp.MENU_FILAS + 1 + tp.MENU_DETALLE + 3, 33)
        self.assertLessEqual(1 + len(tp.CREDITO_PROYECTO), tp.ANCHO_PANELES, "el crédito del proyecto cabe entero")
        self.assertFalse({ch for ch in tp.CREDITO_PROYECTO if ch not in CP437}, "y con letras de la fuente")


class TestCreditosSonido(unittest.TestCase):
    """Créditos de cada sonido: panel inferior izquierdo (solo datos enteros) y detalle completo en el menú F9."""

    def comprobar_enteros(self, it, filas):
        """Cada dato mostrado está COMPLETO (sus filas, unidas, son el dato) y cabe en el ancho del panel."""
        originales = {etq: txt for _, etq, txt, _ in tp.detalle_sonido(it)}
        datos, actual = {}, None
        for etiqueta, texto, _ in filas:
            self.assertLessEqual(len(texto), tp.ANCHO_VALOR, texto)
            self.assertFalse({ch for ch in etiqueta + texto if ch not in CP437}, texto)
            if etiqueta:
                actual = etiqueta
            datos.setdefault(actual, []).append(texto)
        for etiqueta, trozos in datos.items():
            if etiqueta == "Fuente":
                self.assertEqual("".join(trozos), originales[etiqueta].split("://", 1)[-1])
            else:
                self.assertEqual(" ".join(trozos), " ".join(originales[etiqueta].split()))
        return list(datos)

    def test_partir_entero(self):
        self.assertEqual(tp.partir_entero("uno dos tres", 7), ["uno dos", "tres"])
        self.assertEqual(tp.partir_entero("exacto", 6), ["exacto"])
        self.assertIsNone(tp.partir_entero("a b c d e f", 3), "en más filas de las permitidas: no se recorta, no va")
        self.assertEqual(tp.partir_entero("a b c d e f", 3, lineas=3), ["a b", "c d", "e f"])
        self.assertIsNone(tp.partir_entero("palabralarguísima", 5), "una palabra más ancha que la fila")
        self.assertIsNone(tp.partir_entero("", 10))
        self.assertEqual(tp.partir_entero("github.com/sfzinstruments/Osiris_Piano", 29, url=True),
                         ["github.com/sfzinstruments/", "Osiris_Piano"], "la dirección se parte tras «/»")
        self.assertIsNone(tp.partir_entero("x.org/acoustic-grand-piano.html#UprightKW", 29, url=True))

    def test_panel_con_restriccion(self):
        filas = tp.lineas_creditos(RHODES, 7)
        self.assertEqual(filas, [
            ("Autor", "Jeff Learman", False),
            ("Licencia", "Muestras CC BY-NC 4.0 (uso no", False), ("", "comercial); SFZ CC0", False),
            ("Uso", "solo uso no comercial", True),
            ("Fuente", "github.com/sfzinstruments/", False), ("", "jlearman.jRhodes3d", False)])
        self.comprobar_enteros(RHODES, filas)

    def test_lo_que_no_cabe_entero_no_se_muestra(self):
        it = dict(RHODES, fuente="http://freepats.zenvoid.org/Piano/acoustic-grand-piano.html#UprightKW",
                  autor="una lista de autores tan larga que ni en tres filas de veintinueve letras cabe completa")
        filas = tp.lineas_creditos(it, 7)
        self.assertEqual(self.comprobar_enteros(it, filas), ["Licencia", "Uso"], "ni autor ni fuente a medias")

    def test_si_no_caben_todos_se_quitan_por_prioridad(self):
        for max_filas, quedan in ((6, ["Autor", "Licencia", "Uso", "Fuente"]), (5, ["Autor", "Licencia", "Uso"]),
                                  (4, ["Autor", "Licencia", "Uso"]), (3, ["Licencia", "Uso"]), (2, ["Uso"]),
                                  (1, ["Uso"]), (0, [])):
            with self.subTest(max_filas=max_filas):
                filas = tp.lineas_creditos(RHODES, max_filas)
                self.assertLessEqual(len(filas), max_filas)
                self.assertEqual(self.comprobar_enteros(RHODES, filas), quedan, "la fuente sale primero; el uso, nunca")

    def test_datos_que_faltan_o_raros(self):
        self.assertEqual(tp.lineas_creditos(None, 7), [])
        self.assertEqual(tp.lineas_creditos({"id": "x", "nombre": "X"}, 7), [], "un enrutador sin créditos")
        filas = tp.lineas_creditos({"uso": "solo uso no comercial", "restringido": "sí", "autor": "  "}, 7)
        self.assertEqual(filas, [("Uso", "solo uso no comercial", False)],
                         "solo true resalta; un texto vacío no ocupa fila")

    def test_sonido_actual(self):
        ctl = tp.Controles(ejecutar=EjecutorFalso())
        self.assertIsNone(tp.sonido_actual(None))
        self.assertIsNone(tp.sonido_actual(ctl))
        ctl.router = {"instrumento": dict(INSTRUMENTO, lista=LISTA, actual={"id": "rhodes", "nombre": "Rhodes"})}
        self.assertEqual(tp.sonido_actual(ctl), RHODES)
        ctl.router["instrumento"]["actual"] = {"id": "borrado", "nombre": "?"}
        self.assertIsNone(tp.sonido_actual(ctl))

    def test_catalogo_real(self):
        """Los 22 sonidos reales: en el panel, todo lo que se ve está entero y el uso se ve siempre; en el menú F9,
        los cuatro datos completos, sin recortar, dentro del ancho."""
        import catalogo_instrumentos as cat
        import enrutador_midi as em
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instrumentos.json")
        lista = cat.cargar(ruta, "/base")
        publicada = em.GestorInstrumentos(lista, lista[0].id, lambda: 0.0).estado()["lista"]
        menu = tp.MenuInstrumentos()
        for it in publicada:
            with self.subTest(it["id"]):
                vistos = self.comprobar_enteros(it, tp.lineas_creditos(it, 7))
                self.assertIn("Uso", vistos)
                self.assertGreaterEqual(len(vistos), 3, "al menos licencia y uso, casi siempre todo")
                menu.abrir(publicada, it["id"])
                detalle = [t for t, e in tp.lineas_menu(menu) if e in ("detalle", "restringido")]
                esperado = [f" {etq:<9} {txt}" for _, etq, txt, _ in tp.detalle_sonido(it)]
                self.assertEqual(detalle, esperado, "en el menú, enteros")
                self.assertEqual(len(detalle), 4)
                for t in detalle:
                    self.assertLessEqual(len(t), tp.ANCHO_PANELES, t)
                    self.assertFalse({ch for ch in t if ch not in CP437}, t)
                resaltado = [t for t, e in tp.lineas_menu(menu) if e == "restringido"]
                self.assertEqual(bool(resaltado), it["restringido"])


class SalidaFalsa:
    def __init__(self):
        self.enviados = []

    def enviar(self, m):
        self.enviados.append(m)


class ControlesFalsos:
    def __init__(self):
        self.aplicados, self.actualizaciones = [], 0

    def aplicar(self, m):
        self.aplicados.append(m)

    def actualizar_sistema(self):
        self.actualizaciones += 1


# Capacidades reales (capabilities/key) de las 4 interfaces del teclado del usuario (LogoTech Mechanical Keyboard)
CAP_PRINCIPAL = "1000000000007 ff800000000007ff febeffdfffefffff fffffffffffffffe"          # event4 (boot, 6 teclas)
CAP_MULTIMEDIA = ("33eff 0 0 483ffff17aff32d bfd4444600000000 1 130c730b17c000 267bfad9415fed "
                  "9e168000004400 10000002")                                              # event5 (Consumer Control)
CAP_SISTEMA = "c000 10000000000000 0"                                                     # event6 (System Control)
CAP_NKRO = "1000000000000 0 9e80ffcd7fefffff febffbffdffffffe"                            # event7 (resto de teclas)


class TestInterfacesDelTeclado(unittest.TestCase):
    def test_tiene_letras_con_las_capacidades_reales(self):
        self.assertTrue(tp.tiene_letras(CAP_PRINCIPAL, 64))
        self.assertTrue(tp.tiene_letras(CAP_NKRO, 64), "la segunda interfaz lleva las teclas de letras")
        self.assertFalse(tp.tiene_letras(CAP_MULTIMEDIA, 64), "teclas multimedia: no es el teclado")
        self.assertFalse(tp.tiene_letras(CAP_SISTEMA, 64))
        self.assertFalse(tp.tiene_letras("", 64))

    def test_palabras_de_32_bits(self):
        # El mismo mapa en un sistema de 32 bits: cada palabra de 64 se imprime como dos de 32
        cap32 = " ".join(f"{int(w, 16) >> 32:x} {int(w, 16) & 0xFFFFFFFF:x}" for w in CAP_NKRO.split())
        self.assertTrue(tp.tiene_letras(cap32, 32))

    def _sysfs(self, d):
        """Árbol sysfs simulado con la estructura real de la Pi, más otro teclado USB y un teclado no USB."""
        usb = os.path.join(d, "sys", "devices", "platform", "soc", "3f980000.usb", "usb1", "1-1")
        dispositivos = {
            "event4": (os.path.join(usb, "1-1.4", "1-1.4:1.0", "0003:04D9:1836.0004", "input", "input5"), CAP_PRINCIPAL),
            "event5": (os.path.join(usb, "1-1.4", "1-1.4:1.1", "0003:04D9:1836.0005", "input", "input6"), CAP_MULTIMEDIA),
            "event6": (os.path.join(usb, "1-1.4", "1-1.4:1.1", "0003:04D9:1836.0005", "input", "input7"), CAP_SISTEMA),
            "event7": (os.path.join(usb, "1-1.4", "1-1.4:1.1", "0003:04D9:1836.0005", "input", "input8"), CAP_NKRO),
            "event9": (os.path.join(usb, "1-1.3", "1-1.3:1.0", "0003:1111:2222.0009", "input", "input20"), CAP_PRINCIPAL),
            "event2": (os.path.join(d, "sys", "devices", "platform", "gpio-keys", "input", "input2"), CAP_PRINCIPAL),
        }
        clase = os.path.join(d, "sys", "class", "input")
        os.makedirs(clase)
        os.makedirs(os.path.join(d, "dev", "by-id"))
        for ev, (ruta, cap) in dispositivos.items():
            os.makedirs(os.path.join(ruta, "capabilities"))
            with open(os.path.join(ruta, "capabilities", "key"), "w") as f:
                f.write(cap + "\n")
            os.makedirs(os.path.join(clase, ev))
            os.symlink(ruta, os.path.join(clase, ev, "device"))
            open(os.path.join(d, "dev", ev), "w").close()
        os.symlink("../event4", os.path.join(d, "dev", "by-id", "usb-LogoTech_Mechanical_Keyboard-event-kbd"))
        return os.path.join(d, "sys"), os.path.join(d, "dev")

    @unittest.skipUnless(ES_LINUX, "enlaces simbólicos de sysfs")
    def test_detecta_la_segunda_interfaz_del_mismo_teclado(self):
        with tempfile.TemporaryDirectory() as d:
            sysfs, dev = self._sysfs(d)
            ruta = os.path.join(dev, "by-id", "usb-LogoTech_Mechanical_Keyboard-event-kbd")
            self.assertEqual(tp.dispositivos_del_teclado(ruta, sysfs, dev, 64),
                             [os.path.join(dev, "event4"), os.path.join(dev, "event7")],
                             "la NKRO sí; multimedia, sistema y el otro teclado USB no")
            self.assertEqual(tp.dispositivos_del_teclado(os.path.join(dev, "event9"), sysfs, dev, 64),
                             [os.path.join(dev, "event9")], "otro teclado: solo él")
            self.assertEqual(tp.dispositivos_del_teclado(os.path.join(dev, "event2"), sysfs, dev, 64),
                             [os.path.join(dev, "event2")], "no USB: solo él")


@unittest.skipUnless(ES_LINUX, "select() sobre tuberías")
class TestBucle(unittest.TestCase):
    def _ejecutar(self, eventos, controles=None):
        r, w = os.pipe()
        os.write(w, b"".join(tp.empaquetar_evento(c, v) for c, v in eventos))
        os.close(w)
        salida, redibujos = SalidaFalsa(), []
        try:
            res = tp.bucle(r, salida, tp.Interprete(), lambda i: redibujos.append(1), refresco=0.01,
                           controles=controles)
        finally:
            os.close(r)
        return res, salida.enviados, redibujos

    def test_fin_de_entrada(self):
        res, enviados, redibujos = self._ejecutar([(A, 1), (A, 0)])
        self.assertEqual(res, "fin")
        self.assertEqual(enviados, [("on", 60, 80), ("off", 60)])
        self.assertTrue(redibujos)

    def test_dos_interfaces_suman_teclas(self):
        """Caso real: 6 teclas por la interfaz principal y la 7.ª (J) por la segunda; deben sonar las 7."""
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        seis = (A, S, 32, 33, 34, 35)                       # A S D F G H
        os.write(w1, b"".join(tp.empaquetar_evento(c, 1) for c in seis))
        os.write(w2, tp.empaquetar_evento(J, 1) + tp.empaquetar_evento(J, 0))
        os.write(w1, b"".join(tp.empaquetar_evento(c, 0) for c in seis))
        os.close(w1)
        salida = SalidaFalsa()
        try:
            res = tp.bucle([r1, r2], salida, tp.Interprete(), refresco=0.01)
        finally:
            for fd in (r1, r2, w2):
                os.close(fd)
        self.assertEqual(res, "fin")
        ons = sorted(m[1] for m in salida.enviados if m[0] == "on")
        self.assertEqual(ons, [60, 62, 64, 65, 67, 69, 71], "las 7 notas suenan")
        self.assertEqual(len([m for m in salida.enviados if m[0] == "off"]), 7, "y todas se apagan")

    def test_esc_sale_y_apaga(self):
        res, enviados, _ = self._ejecutar([(A, 1), (tp.KEY_ESC, 1), (S, 1)])
        self.assertEqual(res, "salir")
        self.assertEqual(enviados, [("on", 60, 80), ("off", 60)])

    def test_f12_confirmado_termina_con_apagar(self):
        res, enviados, _ = self._ejecutar([(A, 1), (tp.KEY_F12, 1), (W, 1), (tp.KEY_S, 1), (J, 1)])
        self.assertEqual(res, "apagar")
        self.assertEqual(enviados, [("on", 60, 80), ("off", 60)], "W no sonó (se preguntaba) y nada queda sonando")

    def test_reparto_de_mensajes(self):
        ctl = ControlesFalsos()
        res, enviados, _ = self._ejecutar([(tp.KEY_UP, 1), (A, 1), (tp.KEY_F2, 1), (tp.KEY_TAB, 1),
                                           (tp.KEY_RIGHT, 2), (A, 0), (tp.KEY_BACKSPACE, 1)], ctl)
        self.assertEqual(res, "fin")
        self.assertEqual(ctl.aplicados, [("volumen", 1), ("router", "transponer +1"), ("seleccion", 1),
                                         ("reverb", 1), ("router", "panico")])
        self.assertEqual(enviados, [("on", 60, 80), ("off", 60), ("cc", 64, 0), ("cc", 123, 0), ("cc", 120, 0)])
        self.assertGreater(ctl.actualizaciones, 0)


@unittest.skipUnless(ES_LINUX, "curses en pseudoterminal")
class TestInterfazPantalla(ConRouter):
    def _dibujar_en_pty(self, filas, columnas, confirmar=False):
        import fcntl
        import pty
        import termios
        pid, maestro = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", filas, columnas, 0, 0))
                import curses
                import locale
                locale.setlocale(locale.LC_ALL, "")
                os.environ["TERM"] = "xterm"
                i = tp.Interprete()
                i.evento(A, 1)
                if confirmar:
                    i.evento(tp.KEY_F12, 1)
                ctl = self.controles()
                ctl.temp, ctl.cpu, ctl.bajo_voltaje_ahora = 58.0, 33, True
                curses.wrapper(lambda scr: tp.VistaTexto(scr, "Prueba").dibujar(i, ctl))
                os._exit(0)
            except Exception as e:   # noqa: BLE001
                os.write(2, repr(e).encode())
                os._exit(3)
        salida = b""
        while True:
            try:
                bloque = os.read(maestro, 65536)
            except OSError:
                break
            if not bloque:
                break
            salida += bloque
        _, estado = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(estado), salida.decode("utf-8", "replace")

    def test_ventana_de_apagar(self):
        codigo, texto = self._dibujar_en_pty(33, 120, confirmar=True)
        self.assertEqual(codigo, 0, texto[-500:])
        for fragmento in ("Apagar la Raspberry Pi?", "apagar", "seguir tocando", "luz verde", "F12 apagar la Pi"):
            self.assertIn(fragmento, texto)

    def test_pantalla_1080p_terminus(self):
        codigo, texto = self._dibujar_en_pty(33, 120)
        self.assertEqual(codigo, 0, texto[-500:])
        for fragmento in ("Prueba", "ESTADO", "SONIDO", "ENTRADAS MIDI", "CONTROLES", "Roland FP", "[x]",
                          "+2 semitonos", "dura", "11,6 ms", "Cortes", "BAJO VOLTAJE", "Volumen", "F1 baja",
                          "TAB elegir", "PISADO", "La0", "Do8"):
            self.assertIn(fragmento, texto)

    def test_pantalla_con_instrumento(self):
        with open(self.json, "w") as f:
            json.dump(dict(ESTADO_ROUTER, instrumento=dict(INSTRUMENTO, estado="cargando",
                                                           cargando={"id": "c", "nombre": "Yamaha CP80"})), f)
        codigo, texto = self._dibujar_en_pty(33, 120)
        self.assertEqual(codigo, 0, texto[-500:])
        for fragmento in ("Maestro (Yamaha CF-3) - Raspberry Pi", "Sonido", "cargando: Yamaha CP80",
                          "F6 anterior F7 siguiente", "ENTRADAS MIDI", "Salir"):
            self.assertIn(fragmento, texto)

    def test_pantalla_con_ventana_de_carga(self):
        import time as _t
        with open(self.json, "w") as f:
            json.dump(dict(ESTADO_ROUTER, instrumento=dict(
                INSTRUMENTO, estado="cargando", cargando={"id": "osiris", "nombre": "Osiris (vertical)"},
                carga={"id": "osiris", "nombre": "Osiris (vertical)", "inicio": _t.time() - 2, "estimado_s": 8.0,
                       "despues": {"id": "cp80", "nombre": "Yamaha CP80"}})), f)
        codigo, texto = self._dibujar_en_pty(33, 120)
        self.assertEqual(codigo, 0, texto[-500:])
        for fragmento in ("Cargando instrumento", "Osiris (vertical)", "El piano est", "Después: Yamaha CP80",
                          "┌", "┘", "%"):
            self.assertIn(fragmento, texto)

    def test_pantalla_con_menu(self):
        import fcntl
        import pty
        import termios
        with open(self.json, "w") as f:
            json.dump(dict(ESTADO_ROUTER, instrumento=dict(INSTRUMENTO, lista=LISTA,
                                                           actual={"id": "rhodes", "nombre": "Rhodes"})), f)
        pid, maestro = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 33, 120, 0, 0))
                import curses
                import locale
                locale.setlocale(locale.LC_ALL, "")
                os.environ["TERM"] = "xterm"
                ctl = self.controles()
                i = tp.Interprete(instrumentos=ctl.instrumentos)
                i.evento(F, 1)
                curses.wrapper(lambda scr: tp.VistaTexto(scr, "Prueba").dibujar(i, ctl))
                os._exit(0 if i.menu.abierto else 4)
            except Exception as e:   # noqa: BLE001
                os.write(2, repr(e).encode())
                os._exit(3)
        salida = b""
        while True:
            try:
                bloque = os.read(maestro, 65536)
            except OSError:
                break
            if not bloque:
                break
            salida += bloque
        _, estado = os.waitpid(pid, 0)
        texto = salida.decode("utf-8", "replace")
        self.assertEqual(os.waitstatus_to_exitcode(estado), 0, texto[-500:])
        for fragmento in ("SONIDOS por categor", "[Pianos el", "Rhodes Mark I", "(suena ahora)", "ENTER cargar",
                          "F9 sonidos por categor", "Muestras CC BY-NC 4.0 (uso no comercial); SFZ CC0",
                          "https://github.com/sfzinstruments/jlearman.jRhodes3d",
                          "creado por Reinaldo Johnson Espinoza, con la ayuda de Claude (Anthropic)"):
            self.assertIn(fragmento, texto)

    def test_pantalla_con_creditos_abajo_a_la_izquierda(self):
        with open(self.json, "w") as f:
            json.dump(dict(ESTADO_ROUTER, instrumento=dict(INSTRUMENTO, lista=LISTA,
                                                           actual={"id": "rhodes", "nombre": "Rhodes"})), f)
        codigo, texto = self._dibujar_en_pty(33, 120)
        self.assertEqual(codigo, 0, texto[-500:])
        for fragmento in ("SOBRE ESTE SONIDO", "Jeff Learman", "comercial); SFZ CC0", "solo uso no comercial",
                          "github.com/sfzinstruments/", "jlearman.jRhodes3d"):
            self.assertIn(fragmento, texto)
        self.assertNotIn("https://", texto, "en el panel, la dirección sin «https://» (el menú la da completa)")

    def test_pantalla_grande(self):
        codigo, texto = self._dibujar_en_pty(67, 240)
        self.assertEqual(codigo, 0, texto[-500:])
        self.assertIn("Sol3", texto, "con teclas anchas se ven los nombres completos")

    def test_se_adapta_si_cambia_el_tamano(self):
        import fcntl
        import pty
        import termios
        pid, maestro = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 33, 120, 0, 0))
                import curses
                import locale
                locale.setlocale(locale.LC_ALL, "")
                os.environ["TERM"] = "xterm"

                def dos_dibujos(scr):
                    v = tp.VistaTexto(scr, "Prueba")
                    v.dibujar(tp.Interprete(), self.controles())
                    # cambio de fuente / ventana: el terminal crece sin que curses lo sepa
                    fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 67, 240, 0, 0))
                    v.dibujar(tp.Interprete(), self.controles())
                    os.write(2, f"TAM={scr.getmaxyx()}".encode())
                curses.wrapper(dos_dibujos)
                os._exit(0)
            except Exception as e:   # noqa: BLE001
                os.write(2, repr(e).encode())
                os._exit(3)
        salida = b""
        while True:
            try:
                bloque = os.read(maestro, 65536)
            except OSError:
                break
            if not bloque:
                break
            salida += bloque
        _, estado = os.waitpid(pid, 0)
        texto = salida.decode("utf-8", "replace")
        self.assertEqual(os.waitstatus_to_exitcode(estado), 0, texto[-500:])
        self.assertIn("TAM=(67, 240)", texto)
        self.assertIn("Sol3", texto, "el segundo dibujo usa el tamaño nuevo (teclas anchas)")

    def test_ventana_pequena_no_falla(self):
        codigo, texto = self._dibujar_en_pty(20, 80)
        self.assertEqual(codigo, 0, texto[-500:])
        self.assertIn("demasiado", texto)


if __name__ == "__main__":
    unittest.main()
