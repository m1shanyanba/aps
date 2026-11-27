"""Сообщения, датчики и вычислительные узлы."""
from dataclasses import dataclass, replace
from math import inf, isfinite, nextafter


def later(now, duration):
    """Сохранить продвижение времени даже при округлении float."""
    at = now + duration
    if at == now:
        at = nextafter(now, inf)
    if not isfinite(at) or duration <= 0:
        raise ValueError("Интервал выходит за числовой диапазон модельного времени.")
    return at


@dataclass(frozen=True)
class TrialConfig:
    sources: int = 4
    devices: int = 3
    capacity: int = 8
    a: float = 1.0
    b: float = 3.0
    mu: float = 0.9
    limit: int = 3000
    seed: int = 26

    def __post_init__(self):
        for value in (self.sources, self.devices, self.capacity, self.limit):
            if type(value) is not int or value < 1:
                raise ValueError("Число датчиков, узлов, ячеек и заявок должно быть целым и положительным.")
        if not all(isfinite(x) for x in (self.a, self.b, self.mu)) or not (0 < self.a < self.b and self.mu > 0):
            raise ValueError("Требуются конечные параметры 0 < a < b и μ > 0.")
        if type(self.seed) is not int:
            raise ValueError("Seed должен быть целым числом.")


@dataclass
class Request:
    source_id: int
    number: int
    kind: str
    value: float
    generated_at: float
    queued_at: float | None = None
    placement_order: int = 0
    start_at: float | None = None
    ended_at: float | None = None
    outcome: str | None = None

    @property
    def label(self):
        return f"{self.source_id}.{self.number}"

    def mark_queued(self, now, order):
        self.queued_at = now
        self.placement_order = order

    def mark_started(self, now):
        self.start_at = now

    def mark_dropped(self, now):
        self.ended_at = now
        self.outcome = "отказ"

    def mark_completed(self, now):
        self.ended_at = now
        self.outcome = "сохранено"

    def snapshot(self):
        return replace(self)


@dataclass(frozen=True)
class SourceState:
    id: int
    kind: str
    generated: int
    next_at: float | None = None


class Source:
    _measurements = (
        ("Температура, °C", 40, 85),
        ("Вибрация, мм/с", 1, 8),
        ("Давление, кПа", 90, 130),
    )

    def __init__(self, source_id, a, b, rng, intervals=None):
        self.id = source_id
        self.a, self.b = a, b
        self.rng = rng
        self.last_number = 0
        self.kind, self.low, self.high = self._measurements[(source_id - 1) % 3]
        self._intervals = iter(intervals) if intervals is not None else None

    def sample_interval(self):
        if self._intervals is not None:
            return next(self._intervals)
        return self.a + (self.b - self.a) * self.rng.random()

    def generate(self, now):
        self.last_number += 1
        # Значение нужно только для демонстрации сообщения.
        value = round(self.rng.uniform(self.low, self.high), 2)
        return Request(self.id, self.last_number, self.kind, value, now)

    def snapshot(self):
        return SourceState(self.id, self.kind, self.last_number)


@dataclass(frozen=True)
class DeviceState:
    id: int
    current: Request | None
    due_at: float | None


class Device:
    def __init__(self, device_id, rate, rng, durations=None):
        self.id = device_id
        self.rate = rate
        self.rng = rng
        self.current = None
        self.due_at = None
        self._durations = iter(durations) if durations is not None else None

    def is_free(self):
        return self.current is None

    def _sample_duration(self):
        if self._durations is not None:
            return next(self._durations)
        duration = self.rng.expovariate(self.rate)
        while duration == 0:
            duration = self.rng.expovariate(self.rate)
        return duration

    def start(self, request, now):
        if not self.is_free():
            raise RuntimeError("Вычислительный узел уже занят.")
        self.due_at = later(now, self._sample_duration())
        request.mark_started(now)
        self.current = request
        return self.due_at

    def complete(self, now):
        if self.current is None or self.due_at != now:
            raise RuntimeError("Завершение не соответствует текущей обработке.")
        self.current.mark_completed(now)
        return self.current

    def release(self):
        self.current = None
        self.due_at = None

    def snapshot(self):
        return DeviceState(self.id, self.current.snapshot() if self.current else None, self.due_at)
