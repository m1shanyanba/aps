import csv
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class TestWindow(TestCase):
    def setUp(self):
        try:
            from tkinter import TclError
            from src.gui import App
        except ImportError as error:
            self.skipTest(str(error))
        try:
            self.app = App()
        except TclError as error:
            if "display" not in str(error).lower():
                raise
            self.skipTest("Для теста окна нужен графический дисплей.")
        self.addCleanup(self.app.destroy)
        self.app.update()

    def click(self, parent, label):
        for child in parent.winfo_children():
            if child.winfo_class() == "TButton" and child.cget("text") == label:
                child.invoke()
                return True
            if self.click(child, label):
                return True
        return False

    def wait(self, key):
        deadline = time.monotonic() + 10
        while key in self.app.jobs and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.002)
        self.assertNotIn(key, self.app.jobs)

    def test_step_manual_controls_and_calendar(self):
        a = self.app
        a.tabs.select(a.step_tab)
        a.update()
        self.click(a.step_tab, "Ручной сценарий")
        self.assertEqual(len(a.calendar_view.get_children()), 2)
        for _ in range(8):
            self.click(a.step_tab, "Следующий шаг")
        self.assertEqual(a.step_state.now, 8)
        self.assertIn("из ячейки 2", a.log.get("1.0", "end").lower())
        self.click(a.step_tab, "Автовоспроизведение")
        self.assertIsNotNone(a._play_id)
        self.click(a.step_tab, "Пауза")
        self.assertIsNone(a._play_id)
        for _ in range(6):
            self.click(a.step_tab, "Следующий шаг")
        self.assertTrue(a.step_state.finished)
        self.assertEqual(len(a.calendar_view.get_children()), 0)
        self.click(a.step_tab, "Сброс")
        self.assertIsNone(a.step_state)

    def test_auto_study_graph_and_export_controls(self):
        a = self.app
        self.click(a.settings_tab, "Переполнение буфера")
        self.click(a.auto_tab, "Прогон по лимиту")
        self.wait("auto")
        self.assertEqual(a.report.total.generated, 30)
        self.assertGreater(a.report.total.dropped, 0)
        self.click(a.auto_tab, "Подобрать объём")
        self.wait("auto")
        self.assertGreaterEqual(len(a.history.get_children()), 2)
        self.assertIn("Баланс", a.auto_status.cget("text"))
        a.study_limit.set("100")
        self.click(a.study_tab, "Исследовать")
        self.wait("study")
        self.assertTrue(a.study_ready)
        self.assertEqual(len(a.study_table.get_children()), 27)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.csv"
            with patch("src.gui.filedialog.asksaveasfilename", return_value=str(path)):
                self.click(a.study_tab, "Экспорт CSV")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream, delimiter=";"))), 27)
        self.click(a.study_tab, "График выбранного среза")
        a.update()
        graph = [widget for widget in a.winfo_children() if widget.winfo_class() == "Toplevel"]
        self.assertEqual(len(graph), 1)
        canvas = [widget for widget in graph[0].winfo_children() if widget.winfo_class() == "Canvas"][0]
        self.assertTrue(canvas.find_all())
        graph[0].destroy()
