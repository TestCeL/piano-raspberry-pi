"""Pruebas de pw_puertos.py con un volcado sintético de pw-dump."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pw_puertos as p  # noqa: E402


def nodo(id_, nombre):
    return {"id": id_, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": nombre}}}


def puerto(id_, nodo_id, nombre, direccion, dsp):
    return {"id": id_, "type": "PipeWire:Interface:Port",
            "info": {"direction": direccion,
                     "props": {"node.id": nodo_id, "port.name": nombre, "format.dsp": dsp}}}


VOLCADO = [
    nodo(50, "piano"),
    nodo(60, "otro-cliente"),
    puerto(101, 50, "out_2", "output", "32 bit float mono audio"),
    puerto(100, 50, "out_1", "output", "32 bit float mono audio"),
    puerto(102, 50, "midi_in", "input", "8 bit raw midi"),
    puerto(103, 50, "control", "input", "32 bit raw UMP"),
    puerto(200, 60, "out_1", "output", "32 bit float mono audio"),
    {"id": 999, "type": "PipeWire:Interface:Link", "info": None},
    {"id": 998, "type": "PipeWire:Interface:Port", "info": None},
]


class TestPuertos(unittest.TestCase):
    def test_filtra_por_nodo_y_clasifica(self):
        self.assertEqual(p.puertos_de_nodo(VOLCADO, "piano"), [
            ("in", "midi", "piano:control"),
            ("in", "midi", "piano:midi_in"),
            ("out", "audio", "piano:out_1"),
            ("out", "audio", "piano:out_2"),
        ])

    def test_nodo_inexistente(self):
        self.assertEqual(p.puertos_de_nodo(VOLCADO, "no-existe"), [])

    def test_tipo_desconocido(self):
        self.assertEqual(p.tipo_de({"format.dsp": "video"}), "otro")
        self.assertEqual(p.tipo_de({}), "otro")

    def test_main_lee_stdin(self):
        sys.stdin = io.StringIO(json.dumps(VOLCADO))
        salida = io.StringIO()
        try:
            with redirect_stdout(salida):
                self.assertEqual(p.main(["x", "otro-cliente"]), 0)
        finally:
            sys.stdin = sys.__stdin__
        self.assertEqual(salida.getvalue(), "out audio otro-cliente:out_1\n")

    def test_main_sin_argumentos(self):
        self.assertEqual(p.main(["x"]), 2)


if __name__ == "__main__":
    unittest.main()
