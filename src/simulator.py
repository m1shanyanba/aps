"""Событийное ядро для ОД2 и ОР1."""
from dataclasses import dataclass, replace
from random import Random

from .buffer import Buffer
from .calendar import Event, EventCalendar, EventKind
from .dispatchers import PlacementDispatcher, SelectionDispatcher
from .models import Device, Source, TrialConfig, later
from .statistics import RunReport, StatisticsCollector


@dataclass(frozen=True)
class StepSnapshot:
    now: float
    event: Event | None
    remaining: int
    finished: bool
    sources: tuple
    slots: tuple
    devices: tuple
    buffer_pointer: int
    device_pointer: int
    calendar: tuple
    transitions: tuple
    report: RunReport


class Simulator:
    def __init__(self, config, *, journal=True, intervals=None, durations=None):
        self.initialize(config, journal=journal, intervals=intervals, durations=durations)

    def initialize(self, config, *, journal=True, intervals=None, durations=None):
        self.now = 0.0
        self.remaining = config.limit
        self.finished = False
        self.last_event = None
        seed_stream = Random(config.seed)
        intervals = intervals or {}
        durations = durations or {}
        self.sources = [
            Source(i, config.a, config.b, Random(seed_stream.getrandbits(64)), intervals.get(i))
            for i in range(1, config.sources + 1)
        ]
        self.devices = [
            Device(i, config.mu, Random(seed_stream.getrandbits(64)), durations.get(i))
            for i in range(1, config.devices + 1)
        ]
        self.calendar = EventCalendar()
        self.buffer = Buffer(config.capacity)
        self.stats = StatisticsCollector(config.sources, config.devices, journal)
        self.placement = PlacementDispatcher(self.buffer, self.stats)
        self.selection = SelectionDispatcher(self.buffer, self.devices, self.calendar, self.stats)
        for source in self.sources:
            self.calendar.schedule_arrival(later(self.now, source.sample_interval()), source.id)

    def _arrival(self, source):
        request = source.generate(self.now)
        self.stats.record_generated(request, self.now)
        self.remaining -= 1
        if self.remaining:
            at = later(self.now, source.sample_interval())
            self.calendar.schedule_arrival(at, source.id)
        else:
            self.calendar.discard_arrivals()
            self.stats.log(self.now, "Лимит генераций исчерпан. Осталось обработать принятые сообщения.")
        self.placement.place(request, self.now)
        self.selection.dispatch(self.now)

    def _completion(self, device):
        request = device.complete(self.now)
        self.stats.record_completion(request, self.now, device.id)
        device.release()
        self.stats.log(self.now, f"Узел П{device.id} освободился.")
        self.selection.dispatch(self.now)

    def advance(self):
        """Обработать одно календарное событие без создания снимка."""
        if self.finished:
            return False
        self.stats.clear_journal()
        event = self.calendar.pop_next()
        self.last_event = event
        self.now = event.at
        if event.kind == EventKind.ARRIVAL:
            self._arrival(self.sources[event.origin_id - 1])
        else:
            self._completion(self.devices[event.origin_id - 1])

        totals = self.stats.total
        busy = sum(not device.is_free() for device in self.devices)
        if totals.generated != totals.completed + totals.dropped + self.buffer.used + busy:
            raise RuntimeError("Нарушен баланс заявок.")
        if self.buffer.used and busy < len(self.devices):
            raise RuntimeError("Ожидающее сообщение осталось при свободном приборе.")
        if not self.calendar:
            if self.remaining or self.buffer.used or busy:
                raise RuntimeError("Календарь опустел до завершения прогона.")
            self.finished = True
            self.stats.log(self.now, f"Прогон окончен. Баланс {totals.generated} = "
                                     f"{totals.completed} + {totals.dropped}.")
        return True

    def snapshot(self):
        events = self.calendar.snapshot()
        next_arrivals = {event.origin_id: event.at for event in events if event.kind == EventKind.ARRIVAL}
        sources = tuple(replace(source.snapshot(), next_at=next_arrivals.get(source.id))
                        for source in self.sources)
        devices = tuple(device.snapshot() for device in self.devices)
        return StepSnapshot(self.now, self.last_event, self.remaining, self.finished, sources,
                            self.buffer.snapshot(), devices, self.selection.buffer_pointer(),
                            self.selection.device_pointer(), events, self.stats.transitions(),
                            self.stats.report(self.now, devices))

    def step(self):
        return self.snapshot() if self.advance() else None

    def report(self):
        return self.stats.report(self.now, self.devices)

    def run(self):
        while self.advance():
            pass
        return self.report()


def manual_simulation():
    """Воспроизводит входные данные из docs/scenarios.md."""
    config = TrialConfig(sources=2, devices=2, capacity=3, a=0.5, b=9, limit=8)
    return Simulator(config, intervals={1: (1, 2, 2, 2, 8), 2: (2, 2, 4, 8)},
                     durations={1: (5, 3, 5, 2, 1), 2: (10, 6)})
