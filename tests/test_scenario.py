import re
from pathlib import Path
from unittest import TestCase

from src.simulator import manual_simulation


def request_name(request):
    return f"{'A' if request.source_id == 1 else 'B'}{request.number}"


class TestManualScenario(TestCase):
    def test_all_documented_states_and_balance(self):
        path = Path(__file__).resolve().parents[1] / "docs/scenarios.md"
        expected = [list(map(str.strip, line.split("|")[1:-1]))[:12]
                    for line in path.read_text(encoding="utf-8").splitlines() if re.match(r"\| \d+ \|", line)]
        self.assertEqual(len(expected), 16)
        simulator = manual_simulation()
        state = simulator.snapshot()
        self.assertEqual([s.kind for s in state.sources], ["Температура, °C", "Вибрация, мм/с"])
        for i, row in enumerate(expected):
            with self.subTest(row=i):
                event_name = "Инициализация"
                if i:
                    previous = state
                    state = simulator.step()
                    event = state.event
                    if event.kind.name == "ARRIVAL":
                        source = state.sources[event.origin_id - 1]
                        label = "A" if source.id == 1 else "B"
                        event_name = f"Генерация {label}{source.generated}"
                    else:
                        request = previous.devices[event.origin_id - 1].current
                        event_name = f"Завершение {request_name(request)}"
                total = state.report.total
                slots = [f"{request_name(q)}#{q.placement_order}" if q else "—" for q in state.slots]
                devices = [f"{request_name(d.current)}→{d.due_at:g}" if d.current else "—" for d in state.devices]
                actual = [f"{state.now:g}", event_name, *slots, *devices, str(state.buffer_pointer),
                          str(state.device_pointer), str(total.generated), str(total.dropped), str(total.completed)]
                self.assertEqual(actual, row)
                self.assertEqual(total.generated, total.completed + total.dropped
                                 + sum(q is not None for q in state.slots)
                                 + sum(d.current is not None for d in state.devices))
                self.assertTrue(all(at == state.now for at, _ in state.transitions))
                if state.now == 8:
                    self.assertTrue(any("1.4" in message and "ячейки 2" in message for _, message in state.transitions))
        self.assertTrue(state.finished)
        self.assertFalse(state.calendar)
        self.assertEqual((total.generated, total.completed, total.dropped, total.loss), (8, 7, 1, .125))
        self.assertEqual(state.report.sources[0].residence, 31 / 4)
        self.assertEqual(state.report.sources[0].wait_variance, 49 / 4)
        self.assertEqual(state.report.sources[0].service_variance, 59 / 16)
        self.assertEqual([d.busy for d in state.report.devices], [16, 16])
        self.assertEqual(state.report.utilization, 16 / 18)
