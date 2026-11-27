"""Полные прогоны, подбор объёма и сравнение конфигураций."""
import csv
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from itertools import product
from math import ceil, isfinite, prod

from .models import TrialConfig
from .simulator import Simulator
from .statistics import RunReport

DELTA = 0.1
T = 1.643
MIN_OUTCOMES = 10
MAX_CONFIGS = 300
FACTORS = ("sources", "devices", "capacity", "a", "b", "mu")
FACTOR_LABELS = ("Датчики", "Узлы", "Буфер", "a", "b", "μ")


def run_in_batches(config):
    """После 256 событий отдаёт управление интерфейсу."""
    simulator = Simulator(config, journal=False)
    while not simulator.finished:
        for _ in range(256):
            if not simulator.advance():
                break
        if not simulator.finished:
            yield f"Генерации: {simulator.stats.total.generated} из {config.limit}. Остаток СМО обрабатывается после лимита."
    return simulator.report()


def required_sample_size(probability):
    if not 0 < probability < 1:
        return None
    return ceil(T * T * (1 - probability) / (probability * DELTA * DELTA))


@dataclass(frozen=True)
class AccuracyIteration:
    number: int
    seed: int
    size: int
    dropped: int
    probability: float
    estimate: int | None
    change: float | None
    assessment: str


@dataclass(frozen=True)
class AccuracyResult:
    report: RunReport
    converged: bool
    message: str


def estimate_accuracy(config, max_requests, max_iterations):
    if not 1 <= config.limit <= max_requests or max_iterations < 2:
        raise ValueError("Пилот должен укладываться в предел заявок. Нужны хотя бы две итерации.")
    size = config.limit
    previous = None
    for number in range(1, max_iterations + 1):
        seed = config.seed + number - 1
        report = yield from run_in_batches(replace(config, limit=size, seed=seed))
        p = report.total.loss
        estimate = required_sample_size(p)
        change = abs(p - previous) / previous if previous and previous < 1 else None
        enough = min(report.total.dropped, report.total.completed) >= MIN_OUTCOMES
        converged = enough and change is not None and change < DELTA and size >= estimate

        if p in (0, 1):
            assessment = "Крайняя оценка p, требуется больше наблюдений."
        elif not enough:
            assessment = "Меньше 10 отказов или успешных обработок."
        elif converged:
            assessment = "Критерий пособия выполнен."
        elif size < estimate:
            assessment = "Объём ниже оценки по формуле."
        elif change is None:
            assessment = "Нужна вторая оценка для сравнения."
        else:
            assessment = "Оценки расходятся на 10% или больше."
        yield AccuracyIteration(number, seed, size, report.total.dropped, p, estimate, change, assessment)
        if converged:
            return AccuracyResult(report, True, "Точность подтверждена по критерию пособия для p отказа.")
        if size == max_requests and (not enough or estimate > max_requests):
            return AccuracyResult(report, False, "Достигнут предел заявок, точность не подтверждена.")
        previous = p if enough else None
        target = max(size, estimate or 0)
        if not enough or (change is not None and change >= DELTA):
            target = max(target, size * 2)
        size = min(max_requests, target)
    return AccuracyResult(report, False, "Достигнут предел итераций, точность не подтверждена.")


def parse_range(text, integer=False):
    """Одно значение или диапазон начало:конец:шаг."""
    try:
        parts = tuple(Decimal(x.strip().replace(",", ".")) for x in text.split(":"))
    except InvalidOperation:
        raise ValueError("Введите число или диапазон начало:конец:шаг.") from None
    if len(parts) not in (1, 3) or any(not x.is_finite() or x <= 0 for x in parts):
        raise ValueError("Значения диапазона должны быть положительными и конечными.")
    if integer and any(x != x.to_integral_value() for x in parts):
        raise ValueError("Для датчиков, узлов и буфера нужны целые числа.")
    convert = int if integer else float
    if len(parts) == 1:
        return (convert(parts[0]),)
    first, last, step = parts
    if first > last:
        raise ValueError("Конец диапазона должен быть не меньше начала.")
    count = int((last - first) // step) + 1 if last - first < step * MAX_CONFIGS else MAX_CONFIGS + 1
    if count > MAX_CONFIGS:
        raise ValueError(f"Допустимо до {MAX_CONFIGS} значений на диапазон.")
    return tuple(convert(first + step * i) for i in range(count))


def configuration_grid(base, ranges):
    """Построить сетку и посчитать пропущенные пары a ≥ b."""
    if prod(map(len, ranges)) > MAX_CONFIGS:
        raise ValueError(f"Сетка может содержать до {MAX_CONFIGS} сочетаний.")
    configurations = []
    skipped = 0
    for values in product(*ranges):
        if values[3] >= values[4]:
            skipped += 1
        else:
            configurations.append(replace(base, **dict(zip(FACTORS, values))))
    if not configurations:
        raise ValueError("В сетке нет конфигураций с a < b.")
    return configurations, skipped


@dataclass(frozen=True)
class Costs:
    loss: float = 1.0
    device: float = 0.1
    slot: float = 0.01

    def __post_init__(self):
        if any(not isfinite(value) or value < 0 for value in (self.loss, self.device, self.slot)):
            raise ValueError("Условные цены должны быть конечными и неотрицательными.")


@dataclass(frozen=True)
class ExperimentRow:
    config: TrialConfig
    report: RunReport
    eligible: bool
    costs: Costs
    expense: float
    expense_per_success: float | None


def evaluate(config, report, tolerance, costs):
    rate = report.utilization
    total = report.total
    eligible = total.loss is not None and total.loss <= 0.1 and rate is not None and abs(rate - 0.9) <= tolerance + 1e-12
    expense = (costs.loss * total.dropped + costs.device * config.devices * report.now
               + costs.slot * config.capacity * report.now)
    return ExperimentRow(config, report, eligible, costs, expense,
                         expense / total.completed if total.completed else None)


def study(configurations, tolerance, costs):
    results = []
    for index, config in enumerate(configurations, 1):
        yield f"Конфигурация {index} из {len(configurations)}"
        report = yield from run_in_batches(config)
        row = evaluate(config, report, tolerance, costs)
        results.append(row)
        yield row
    return results


def best_index(rows):
    candidates = [i for i, row in enumerate(rows) if row.eligible and row.report.total.residence is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda i: (rows[i].report.total.residence, rows[i].expense_per_success))


def graph_slice(rows, index, factor):
    """Оставить варианты, где все параметры кроме выбранного совпадают."""
    base = rows[index].config
    rest = [key for key in FACTORS if key != factor]
    slice_rows = [row for row in rows if all(getattr(row.config, key) == getattr(base, key) for key in rest)]
    return sorted(slice_rows, key=lambda row: getattr(row.config, factor))


def export_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow((*FACTOR_LABELS, "Лимит", "Seed", "Генерации", "Обслужено", "Отказы",
                         "P отказа", "Среднее время в системе", "Средняя загрузка",
                         "Полное модельное время", "Цена отказа", "Цена узла", "Цена ячейки",
                         "Условные затраты", "Затраты на обслуженное", "Подходит", "Выбрана"))
        best = best_index(rows)
        for i, row in enumerate(rows):
            c, r = row.config, row.report
            writer.writerow((*(getattr(c, key) for key in FACTORS), c.limit, c.seed, r.total.generated,
                             r.total.completed, r.total.dropped, r.total.loss, r.total.residence,
                             r.utilization, r.now, row.costs.loss, row.costs.device, row.costs.slot,
                             row.expense, row.expense_per_success, int(row.eligible), int(i == best)))
