"""Четыре вкладки Tkinter. Модель и расчёты выполняются в src."""
from dataclasses import replace
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .experiments import (AccuracyIteration, Costs, ExperimentRow, FACTORS, FACTOR_LABELS,
                          best_index, configuration_grid, estimate_accuracy, export_csv,
                          graph_slice, parse_range, run_in_batches, study)
from .models import TrialConfig
from .simulator import Simulator, manual_simulation
from .calendar import EventKind


SETTINGS = (
    ("sources", "Датчики"), ("devices", "Вычислительные узлы"),
    ("capacity", "Ячейки буфера"), ("a", "Нижняя граница a"),
    ("b", "Верхняя граница b"), ("mu", "Интенсивность μ"),
    ("limit", "Лимит генераций"), ("seed", "Seed"),
)
PRESETS = {
    "Нормальная нагрузка": TrialConfig(),
    "Высокая нагрузка": TrialConfig(sources=6, devices=3, capacity=14, a=1, b=3, mu=1),
    "Переполнение буфера": TrialConfig(sources=4, devices=1, capacity=2, a=1, b=2, mu=0.35, limit=30),
}


def number(value):
    return "—" if value is None else f"{value:.6g}"


def percent(value):
    return "—" if value is None else f"{value:.2%}"


def decimal(text):
    return float(text.strip().replace(",", "."))


def bounded_int(text, low, high, label):
    value = int(text)
    if not low <= value <= high:
        raise ValueError(f"{label} должно быть в диапазоне {low}…{high}.")
    return value


def table(parent, columns, height=7):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=list(range(len(columns))), show="headings", height=height)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    for index, (title, width) in enumerate(columns):
        tree.heading(index, text=title)
        tree.column(index, width=width, minwidth=width, anchor="center")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.pack(fill="both", expand=True)
    return tree


def populate(tree, rows):
    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=row)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("СМО №26 — телеметрия промышленного оборудования")
        self.geometry("1160x800")
        self.minsize(900, 640)
        self.simulator = None
        self.step_state = None
        self._play_id = None
        self.jobs = {}
        self.study_rows = []
        self.study_ready = False
        self.report = None
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.settings_tab = self._tab("Настройки")
        self.step_tab = self._tab("Пошаговый режим")
        self.auto_tab = self._tab("Автоматический режим")
        self.study_tab = self._tab("Исследование конфигураций")
        self._build_settings()
        self._build_step()
        self._build_auto()
        self._build_study()
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _tab(self, title):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text=title)
        return tab

    def _entry(self, parent, label, value, row, column=0, width=15):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 7), pady=3)
        variable = tk.StringVar(value=str(value))
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=column + 1, sticky="w", padx=(0, 15), pady=3)
        return variable

    def _build_settings(self):
        ttk.Label(self.settings_tab, text="Обработка телеметрии датчиков", font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(self.settings_tab, text="Вариант №26 · Жирнов М. С. · 5130904/40101").pack(anchor="w", pady=(3, 12))
        forms = ttk.LabelFrame(self.settings_tab, text="Параметры нового прогона", padding=12)
        forms.pack(anchor="w", fill="x")
        defaults = TrialConfig()
        self.inputs = {key: self._entry(forms, label, getattr(defaults, key), i)
                       for i, (key, label) in enumerate(SETTINGS)}
        preset = ttk.LabelFrame(self.settings_tab, text="Демонстрационные конфигурации", padding=10)
        preset.pack(anchor="w", fill="x", pady=12)
        for name in PRESETS:
            ttk.Button(preset, text=name, command=lambda choice=name: self._preset(choice)).pack(side="left", padx=(0, 8))
        ttk.Label(self.settings_tab, text="Параметры применяются при новом запуске. Настройки a, b и μ общие для элементов.\n"
                  "Датчики получают независимые потоки случайных чисел. Измерения условные.").pack(anchor="w")

    def _preset(self, name):
        config = PRESETS[name]
        for key, _ in SETTINGS:
            self.inputs[key].set(getattr(config, key))

    def _read_config(self):
        values = {key: variable.get() for key, variable in self.inputs.items()}
        for key in ("sources", "devices", "capacity"):
            values[key] = bounded_int(values[key], 1, 500, dict(SETTINGS)[key])
        values["limit"] = bounded_int(values["limit"], 1, 10_000_000, "Лимит")
        values["seed"] = int(values["seed"])
        for key in ("a", "b", "mu"):
            values[key] = decimal(values[key])
        return TrialConfig(**values)

    def _build_step(self):
        toolbar = ttk.Frame(self.step_tab)
        toolbar.pack(fill="x", pady=(0, 5))
        for label, command in (
            ("Инициализация", self._init_step), ("Ручной сценарий", lambda: self._init_step(True)),
            ("Следующий шаг", self._step), ("Автовоспроизведение", self._play),
            ("Пауза", self._pause), ("Сброс", self._reset_step),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=(0, 5))
        self.step_info = ttk.Label(self.step_tab, text="Инициализируйте прогон или откройте ручной сценарий.")
        self.step_info.pack(anchor="w")
        self.scheme = tk.Canvas(self.step_tab, height=122, background="white", highlightthickness=1,
                                highlightbackground="#a7b5c1")
        self.scheme.pack(fill="x", pady=5)
        self.scheme.bind("<Configure>", lambda _: self._draw_scheme())
        sheets = ttk.Notebook(self.step_tab)
        sheets.pack(fill="both", expand=True)
        definitions = (
            ("Датчики", "source_view", (("Датчик", 80), ("Измерение", 180), ("Генерации", 110),
                                        ("Следующий приход", 145), ("Отказы", 100), ("Обработано", 110), ("Доля отказов", 115))),
            ("Буфер", "buffer_view", (("Ячейка", 95), ("Сообщение", 100), ("№ постановки", 130),
                                      ("Измерение", 160), ("Значение", 90), ("Время записи", 120), ("УБ", 70))),
            ("Узлы", "device_view", (("Узел", 85), ("Состояние", 120), ("Сообщение", 105),
                                    ("Конец обработки", 135), ("Обработано", 100), ("Загрузка", 110), ("УП", 70))),
            ("Календарь", "calendar_view", (("Время", 130), ("Событие", 160), ("Участник", 145), ("№ записи", 110))),
        )
        for name, attr, columns in definitions:
            panel = ttk.Frame(sheets, padding=4)
            sheets.add(panel, text=name)
            setattr(self, attr, table(panel, columns, height=6))
        journal_frame = ttk.LabelFrame(self.step_tab, text="Журнал переходов", padding=4)
        journal_frame.pack(fill="x", pady=(6, 0))
        self.log = tk.Text(journal_frame, height=7, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(journal_frame, orient="vertical", command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(fill="x", expand=True)

    def _on_tab_changed(self, _event):
        if self.tabs.select() != str(self.step_tab):
            self._pause()

    def _draw_scheme(self):
        canvas = self.scheme
        canvas.delete("all")
        width = max(canvas.winfo_width(), 740)
        state = self.step_state
        occupied = sum(q is not None for q in state.slots) if state else 0
        busy = sum(d.current is not None for d in state.devices) if state else 0
        labels = ["Датчики", "Приёмщик\nтелеметрии", "Буфер", "Планировщик", "Вычислительные\nузлы", "Сохранено"]
        if state:
            labels[0] += f" · {len(state.sources)}"
            labels[2] += f" {occupied}/{len(state.slots)}\nУБ = {state.buffer_pointer}"
            labels[3] += f"\nУП = {state.device_pointer}"
            labels[4] += f" {busy}/{len(state.devices)}"
            labels[5] += f" · {state.report.total.completed}"
        cell = width / 6
        for index, label in enumerate(labels):
            left, right = index * cell + 9, (index + 1) * cell - 9
            canvas.create_rectangle(left, 11, right, 62, outline="#47647a", fill="#edf4fa")
            canvas.create_text((left + right) / 2, 36, text=label, width=cell - 22, justify="center")
            if index < 5:
                canvas.create_line(right, 36, right + 18, 36, arrow="last", fill="#47647a")
        drop_x = 2.5 * cell
        canvas.create_line(drop_x, 62, drop_x, 83, arrow="last", fill="#9a4036")
        canvas.create_rectangle(drop_x - 67, 83, drop_x + 67, 111, outline="#9a4036", fill="#fff0eb")
        label = f"Отказы · {state.report.total.dropped}" if state else "Отказы"
        canvas.create_text(drop_x, 97, text=label)

    def _init_step(self, demo=False):
        self._pause()
        try:
            simulator = manual_simulation() if demo else Simulator(self._read_config())
        except (ValueError, ArithmeticError) as error:
            messagebox.showerror("Настройки", str(error), parent=self)
            return
        self._reset_step()
        self.simulator = simulator
        self._show_step(simulator.snapshot())

    def _reset_step(self):
        self._pause()
        self.simulator = self.step_state = None
        for tree in (self.source_view, self.buffer_view, self.device_view, self.calendar_view):
            populate(tree, ())
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.step_info.configure(text="Инициализируйте прогон или откройте ручной сценарий.")
        self._draw_scheme()

    def _step(self):
        if self.simulator is None or self.simulator.finished:
            return
        try:
            self._show_step(self.simulator.step())
        except (ValueError, ArithmeticError, RuntimeError) as error:
            self._pause()
            self.simulator = None
            messagebox.showerror("Ошибка прогона", str(error), parent=self)

    def _play(self):
        if self._play_id is None and self.simulator and not self.simulator.finished:
            self._play_tick()

    def _play_tick(self):
        self._play_id = None
        self._step()
        if self.simulator and not self.simulator.finished:
            self._play_id = self.after(230, self._play_tick)

    def _pause(self):
        if self._play_id is not None:
            self.after_cancel(self._play_id)
            self._play_id = None

    def _show_step(self, state):
        self.step_state = state
        total = state.report.total
        suffix = " · Прогон завершён" if state.finished else ""
        self.step_info.configure(text=f"t = {number(state.now)}    Генерации: {total.generated}    Отказы: {total.dropped}"
                                 f"    Завершения: {total.completed}    Pотк: {percent(total.loss)}"
                                 f"    Осталось сгенерировать: {state.remaining}{suffix}")
        self._draw_scheme()
        populate(self.source_view, ((f"И{s.id}", s.kind, s.generated, number(s.next_at),
                                     row.dropped, row.completed, percent(row.loss))
                                    for s, row in zip(state.sources, state.report.sources)))
        populate(self.buffer_view, ((i, q.label if q else "—", q.placement_order if q else "—",
                                     q.kind if q else "—", q.value if q else "—",
                                     number(q.queued_at) if q else "—", "←" if i == state.buffer_pointer else "")
                                    for i, q in enumerate(state.slots, 1)))
        populate(self.device_view, ((f"П{d.id}", "Занят" if d.current else "Свободен", d.current.label if d.current else "—",
                                     number(d.due_at), row.completed, percent(row.utilization),
                                     "←" if d.id == state.device_pointer else "")
                                    for d, row in zip(state.devices, state.report.devices)))
        populate(self.calendar_view, ((number(e.at), e.kind.title,
                                        f"{'И' if e.kind == EventKind.ARRIVAL else 'П'}{e.origin_id}", e.serial)
                                       for e in state.calendar))
        if state.transitions:
            self.log.configure(state="normal")
            self.log.insert("end", "".join(f"[{number(at)}] {message}\n" for at, message in state.transitions))
            lines = int(self.log.index("end-1c").split(".")[0])
            if lines > 3001:
                self.log.delete("1.0", f"{lines - 3000}.0")
            self.log.see("end")
            self.log.configure(state="disabled")

    def _build_auto(self):
        bar = ttk.Frame(self.auto_tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="Прогон по лимиту", command=self._start_fixed).pack(side="left")
        ttk.Button(bar, text="Подобрать объём", command=self._start_accuracy).pack(side="left", padx=6)
        ttk.Button(bar, text="Остановить", command=lambda: self._cancel("auto")).pack(side="left")
        params = ttk.LabelFrame(self.auto_tab, text="Подбор объёма · точность 10%, доверительная вероятность 0,9", padding=5)
        params.pack(fill="x", pady=5)
        self.pilot = self._entry(params, "Пилот", 100, 0, 0, 10)
        self.accuracy_max = self._entry(params, "Предел заявок", 200000, 0, 2, 10)
        self.iterations = self._entry(params, "Предел итераций", 8, 0, 4, 8)
        self.auto_status = ttk.Label(self.auto_tab, text="Входные параметры берутся со вкладки настроек.", wraplength=850)
        self.auto_status.pack(anchor="w", pady=4)
        views = ttk.Notebook(self.auto_tab)
        views.pack(fill="both", expand=True)
        self.auto_views = views
        sensor = ttk.Frame(views, padding=8)
        devices = ttk.Frame(views, padding=8)
        history = ttk.Frame(views, padding=8)
        views.add(sensor, text="Датчики и система")
        views.add(devices, text="Вычислительные узлы")
        views.add(history, text="История подбора объёма")
        self.auto_history_tab = history
        self.auto_summary_tab = sensor
        labels = ("Датчик", "Генерации", "Отказы", "Обслужено", "Pотк", "Tпреб", "Tож", "Tобсл", "Dож", "Dобсл")
        self.source_report = table(sensor, tuple((label, 90) for label in labels))
        self.device_report = table(devices, (("Узел", 100), ("Обслужено", 125), ("Время занятости", 160), ("Загрузка", 130)))
        self.history = table(history, (("Итерация", 80), ("Seed", 75), ("Заявок", 80), ("Отказы", 75), ("Pотк", 80),
                                       ("Оценка N", 90), ("Изменение", 95), ("Результат", 360)))

    def _start_fixed(self):
        self._start_auto(False)

    def _start_accuracy(self):
        self._start_auto(True)

    def _start_auto(self, accuracy):
        if "auto" in self.jobs:
            return
        try:
            config = self._read_config()
            if accuracy:
                limit = bounded_int(self.accuracy_max.get(), 1, 10_000_000, "Предел заявок")
                pilot = bounded_int(self.pilot.get(), 1, limit, "Пилот")
                iterations = bounded_int(self.iterations.get(), 2, 50, "Число итераций")
                job = estimate_accuracy(replace(config, limit=pilot), limit, iterations)
            else:
                job = run_in_batches(config)
        except (ValueError, ArithmeticError) as error:
            messagebox.showerror("Параметры прогона", str(error), parent=self)
            return
        for tree in (self.source_report, self.device_report, self.history):
            populate(tree, ())
        self.auto_views.select(self.auto_history_tab if accuracy else self.auto_summary_tab)
        self.report = None
        self._start_job("auto", job, self._auto_progress, self._finish_auto, self.auto_status)

    def _auto_progress(self, value):
        if isinstance(value, AccuracyIteration):
            self.history.insert("", "end", values=(value.number, value.seed, value.size, value.dropped,
                                percent(value.probability), number(value.estimate), percent(value.change), value.assessment))
            self.auto_status.configure(text=f"Итерация {value.number}. {value.assessment}")

    def _finish_auto(self, result):
        if hasattr(result, "report"):
            report, message = result.report, result.message
        else:
            report, message = result, "Прогон завершён."
        self.report = report
        total = report.total
        populate(self.source_report, ((f"И{row.id}" if row.id else "Система", row.generated, row.dropped,
                                       row.completed, percent(row.loss), number(row.residence), number(row.wait),
                                       number(row.service), number(row.wait_variance), number(row.service_variance))
                                      for row in (*report.sources, total)))
        populate(self.device_report, ((f"П{row.id}", row.completed, number(row.busy), percent(row.utilization))
                                      for row in report.devices))
        self.device_report.insert("", "end", values=("Система", total.completed,
                                  number(sum(row.busy for row in report.devices)), percent(report.utilization)))
        self.auto_status.configure(text=f"{message} Баланс {total.generated} = {total.completed} + {total.dropped}."
                                   f" Время: {number(report.now)}. Pотк: {percent(total.loss)}.")

    def _build_study(self):
        inputs = ttk.LabelFrame(self.study_tab, text="Диапазоны · одно число или начало:конец:шаг", padding=6)
        inputs.pack(fill="x")
        defaults = ("4:6:1", "2:4:1", "8:16:4", "1", "3", "1")
        self.ranges = [self._entry(inputs, label, value, i // 3, 2 * (i % 3))
                       for i, (label, value) in enumerate(zip(FACTOR_LABELS, defaults))]
        self.tolerance = self._entry(inputs, "Допуск загрузки, п. п.", 5, 2, 0)
        self.study_limit = self._entry(inputs, "Заявок на прогон", 3000, 2, 2)
        prices = ttk.LabelFrame(self.study_tab, text="Условные цены · узел и ячейка за единицу модельного времени", padding=6)
        prices.pack(fill="x", pady=5)
        self.loss_fee = self._entry(prices, "Потеря", 1, 0, 0)
        self.device_fee = self._entry(prices, "Узел", 0.1, 0, 2)
        self.slot_fee = self._entry(prices, "Ячейка", 0.01, 0, 4)
        toolbar = ttk.Frame(self.study_tab)
        toolbar.pack(fill="x", pady=4)
        ttk.Button(toolbar, text="Исследовать", command=self._start_study).pack(side="left")
        ttk.Button(toolbar, text="Остановить", command=lambda: self._cancel("study")).pack(side="left", padx=5)
        ttk.Button(toolbar, text="Экспорт CSV", command=self._export).pack(side="left")
        ttk.Button(toolbar, text="График выбранного среза", command=self._open_graph).pack(side="left", padx=5)
        self.study_status = ttk.Label(self.study_tab, text="Цель: Pотк ≤ 10%, загрузка около 90%, минимальное Tпреб.",
                                      wraplength=870)
        self.study_status.pack(anchor="w", pady=4)
        columns = ("Датчики", "Узлы", "Буфер", "a", "b", "μ", "Pотк", "Tпреб",
                   "Загрузка", "Обслужено", "Отказы", "Затраты", "На заявку", "Оценка")
        widths = (70, 65, 65, 55, 55, 55, 75, 75, 85, 90, 70, 90, 85, 105)
        self.study_table = table(self.study_tab, tuple(zip(columns, widths)))
        self.study_table.tag_configure("eligible", background="#eef6e8")
        self.study_table.tag_configure("best", background="#c9e9ca")

    def _start_study(self):
        if "study" in self.jobs:
            return
        try:
            limit = bounded_int(self.study_limit.get(), 1, 10_000_000, "Лимит исследования")
            seed = int(self.inputs["seed"].get())
            ranges = [parse_range(variable.get(), i < 3) for i, variable in enumerate(self.ranges)]
            if any(max(values) > 500 for values in ranges[:3]):
                raise ValueError("Допускается до 500 датчиков, узлов или ячеек.")
            tolerance = decimal(self.tolerance.get()) / 100
            if not 0 <= tolerance <= 1:
                raise ValueError("Допуск должен быть от 0 до 100 п. п.")
            costs = Costs(*(decimal(v.get()) for v in (self.loss_fee, self.device_fee, self.slot_fee)))
            configurations, self.skipped = configuration_grid(TrialConfig(limit=limit, seed=seed), ranges)
        except (ValueError, ArithmeticError) as error:
            messagebox.showerror("Параметры исследования", str(error), parent=self)
            return
        self.study_rows = []
        self.study_ready = False
        populate(self.study_table, ())
        self._start_job("study", study(configurations, tolerance, costs),
                        self._study_progress, self._finish_study, self.study_status)

    def _study_progress(self, value):
        if isinstance(value, ExperimentRow):
            index = len(self.study_rows)
            self.study_rows.append(value)
            self._show_study_row(index, value)

    def _show_study_row(self, index, row, best=False):
        c, r = row.config, row.report
        assessment = "Выбрана" if best else "Подходит" if row.eligible else "Вне условий"
        tag = "best" if best else "eligible" if row.eligible else ""
        values = (c.sources, c.devices, c.capacity, number(c.a), number(c.b), number(c.mu),
                  percent(r.total.loss), number(r.total.residence), percent(r.utilization), r.total.completed,
                  r.total.dropped, number(row.expense), number(row.expense_per_success), assessment)
        if best:
            self.study_table.item(str(index), values=values, tags=(tag,))
        else:
            self.study_table.insert("", "end", iid=str(index), values=values, tags=(tag,))

    def _finish_study(self, rows):
        self.study_ready = True
        index = best_index(rows)
        text = f"Проверено {len(rows)}. Пропущено сочетаний a ≥ b: {self.skipped}. "
        if index is None:
            text += "Подходящих конфигураций нет."
        else:
            row = rows[index]
            self._show_study_row(index, row, best=True)
            self.study_table.selection_set(str(index))
            self.study_table.see(str(index))
            text += (f"Выбрана строка {index + 1}: минимальное Tпреб среди подходящих. "
                     f"Условные затраты на обработанное сообщение: {number(row.expense_per_success)}.")
        self.study_status.configure(text=text)

    def _export(self):
        if not self.study_ready:
            messagebox.showinfo("Экспорт", "Сначала завершите исследование.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
                                            initialfile="configurations.csv", filetypes=[("CSV", "*.csv")])
        if path:
            try:
                export_csv(path, self.study_rows)
                self.study_status.configure(text=f"Сохранено {len(self.study_rows)} строк в {path}")
            except OSError as error:
                messagebox.showerror("Экспорт CSV", str(error), parent=self)

    def _open_graph(self):
        if not self.study_ready:
            messagebox.showinfo("График", "Сначала завершите исследование.", parent=self)
            return
        selected = self.study_table.selection()
        index = int(selected[0]) if selected else 0
        rows = tuple(self.study_rows)
        win = tk.Toplevel(self)
        win.title("Показатель при изменении одного параметра")
        win.geometry("780x470")
        controls = ttk.Frame(win, padding=8)
        controls.pack(fill="x")
        sizes = [len(graph_slice(rows, index, key)) for key in FACTORS]
        initial = max(range(len(sizes)), key=sizes.__getitem__)
        factor = ttk.Combobox(controls, values=FACTOR_LABELS, state="readonly", width=14)
        factor.current(initial)
        factor.pack(side="left", padx=5)
        metric = ttk.Combobox(controls, values=("Вероятность отказа", "Среднее время в системе", "Средняя загрузка"),
                              state="readonly", width=26)
        metric.current(0)
        metric.pack(side="left")
        ttk.Label(win, text="Остальные параметры взяты из выбранной строки.").pack(anchor="w", padx=12)
        canvas = tk.Canvas(win, background="white", highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=8, pady=8)

        def draw(_event=None):
            key = FACTORS[factor.current()]
            points = []
            for row in graph_slice(rows, index, key):
                r = row.report
                value = (r.total.loss, r.total.residence, r.utilization)[metric.current()]
                if value is not None:
                    points.append((getattr(row.config, key), value))
            self._draw_graph(canvas, points, factor.get(), metric.get(), metric.current() != 1)

        canvas.bind("<Configure>", draw)
        factor.bind("<<ComboboxSelected>>", draw)
        metric.bind("<<ComboboxSelected>>", draw)
        return win

    def _draw_graph(self, canvas, points, x_title, y_title, relative):
        canvas.delete("all")
        left, top = 78, 32
        right, bottom = canvas.winfo_width() - 27, canvas.winfo_height() - 55
        if right <= left or bottom <= top:
            return
        canvas.create_text(left, 12, text=y_title, anchor="w")
        canvas.create_line(left, top, left, bottom, right, bottom, fill="#486477")
        canvas.create_text((left + right) / 2, bottom + 38, text=x_title)
        if not points:
            canvas.create_text((left + right) / 2, (top + bottom) / 2, text="Нет данных")
            return
        low, high = points[0][0], points[-1][0]
        ceiling = max(y for _, y in points) or (1 if relative else 0.1)
        for i in range(5):
            y = bottom - (bottom - top) * i / 4
            value = ceiling * i / 4
            canvas.create_text(left - 6, y, text=percent(value) if relative else number(value), anchor="e")
            canvas.create_line(left, y, right, y, fill="#d8e1e9")
        coords = []
        label_step = max(1, (len(points) - 1) // 7 + 1)
        for i, (x, y) in enumerate(points):
            xx = left + (right - left) * ((x - low) / (high - low) if low != high else 0.5)
            yy = bottom - (bottom - top) * y / ceiling
            coords.extend((xx, yy))
            if i % label_step == 0 or i == len(points) - 1:
                canvas.create_text(xx, bottom + 14, text=number(x))
        if len(coords) >= 4:
            canvas.create_line(*coords, fill="#245b87", width=2)
        for x, y in zip(coords[::2], coords[1::2]):
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#245b87", outline="")

    def _start_job(self, key, job, progress, finish, status):
        """Один вызов next выполняется за один оборот цикла Tkinter."""
        def tick():
            try:
                update = next(job)
            except StopIteration as stop:
                self.jobs.pop(key, None)
                finish(stop.value)
                return
            except (ValueError, ArithmeticError, RuntimeError) as error:
                self.jobs.pop(key, None)
                status.configure(text=f"Ошибка: {error}")
                return
            if isinstance(update, str):
                status.configure(text=update)
            else:
                progress(update)
            self.jobs[key] = (self.after(1, tick), job, status)

        status.configure(text="Запуск…")
        self.jobs[key] = (self.after(1, tick), job, status)

    def _cancel(self, key):
        pending = self.jobs.pop(key, None)
        if pending:
            after_id, job, status = pending
            self.after_cancel(after_id)
            job.close()
            status.configure(text="Прогон остановлен пользователем.")
