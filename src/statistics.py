"""Накопители статистики и журнал переходов одного события."""
from dataclasses import dataclass, field


def ratio(numerator, denominator):
    return numerator / denominator if denominator > 0 else None


@dataclass
class Moments:
    count: int = 0
    total: float = 0.0
    squares: float = 0.0

    def add(self, value):
        self.count += 1
        self.total += value
        self.squares += value * value

    def mean(self):
        return ratio(self.total, self.count)

    def variance(self):
        if not self.count:
            return None
        # Убираем возможное отрицательное значение из-за округления.
        return max(0.0, self.squares / self.count - self.mean() ** 2)


@dataclass
class SourceTotals:
    generated: int = 0
    dropped: int = 0
    completed: int = 0
    waiting: Moments = field(default_factory=Moments)
    service: Moments = field(default_factory=Moments)
    residence: Moments = field(default_factory=Moments)

    def row(self, source_id):
        return SourceRow(source_id, self.generated, self.dropped, self.completed,
                         ratio(self.dropped, self.generated), self.residence.mean(),
                         self.waiting.mean(), self.service.mean(),
                         self.waiting.variance(), self.service.variance())


@dataclass
class DeviceTotals:
    completed: int = 0
    busy: float = 0.0


@dataclass(frozen=True)
class SourceRow:
    id: int
    generated: int
    dropped: int
    completed: int
    loss: float | None
    residence: float | None
    wait: float | None
    service: float | None
    wait_variance: float | None
    service_variance: float | None


@dataclass(frozen=True)
class DeviceRow:
    id: int
    completed: int
    busy: float
    utilization: float | None


@dataclass(frozen=True)
class RunReport:
    now: float
    sources: tuple
    devices: tuple
    total: SourceRow
    utilization: float | None


class StatisticsCollector:
    def __init__(self, sources, devices, journal=True):
        self.by_source = {number: SourceTotals() for number in range(1, sources + 1)}
        self.by_device = {number: DeviceTotals() for number in range(1, devices + 1)}
        self.total = SourceTotals()
        self._journal_enabled = journal
        self._journal = []

    def clear_journal(self):
        self._journal.clear()

    def log(self, now, message):
        if self._journal_enabled:
            self._journal.append((now, message))

    def journal_size(self):
        return len(self._journal)

    def transitions(self, interval=None):
        if interval is None:
            return tuple(self._journal)
        start, end = interval
        return tuple(self._journal[start:end])

    def record_generated(self, request, now):
        self.by_source[request.source_id].generated += 1
        self.total.generated += 1
        self.log(now, f"Датчик И{request.source_id} сформировал сообщение {request.label}.")

    def record_queued(self, request, now, slot):
        self.log(now, f"Д1ОЗ3. Сообщение {request.label} в ячейке {slot}, постановка №{request.placement_order}.")

    def record_drop(self, request, now, slot):
        self.by_source[request.source_id].dropped += 1
        self.total.dropped += 1
        self.log(now, f"Д1ОО4. Буфер полон. Из ячейки {slot} выбито сообщение {request.label} "
                      f"с последней постановкой №{request.placement_order}. Отказ у И{request.source_id}.")

    def record_start(self, request, now, slot, device):
        self.log(now, f"ПЗ1. Узел П{device} начал обработку {request.label} из ячейки {slot}.")

    def record_completion(self, request, now, device):
        # Постановка проходит в момент генерации, поэтому эти отметки совпадают.
        wait = request.start_at - request.generated_at
        service = now - request.start_at
        for totals in (self.by_source[request.source_id], self.total):
            totals.completed += 1
            totals.waiting.add(wait)
            totals.service.add(service)
            totals.residence.add(wait + service)
        self.by_device[device].completed += 1
        self.by_device[device].busy += service
        self.log(now, f"Узел П{device} завершил обработку. Сообщение {request.label} сохранено.")

    def report(self, now, devices):
        device_rows = []
        for device in devices:
            totals = self.by_device[device.id]
            busy = totals.busy
            if device.current is not None:
                busy += now - device.current.start_at
            device_rows.append(DeviceRow(device.id, totals.completed, busy, ratio(busy, now)))
        rows = tuple(totals.row(number) for number, totals in self.by_source.items())
        utilization = ratio(sum(row.busy for row in device_rows), now * len(device_rows))
        return RunReport(now, rows, tuple(device_rows), self.total.row(0), utilization)
