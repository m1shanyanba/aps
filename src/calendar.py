"""Календарь содержит только будущие приходы и завершения."""
from dataclasses import dataclass
from enum import IntEnum
from heapq import heapify, heappop, heappush


class EventKind(IntEnum):
    COMPLETION = 0
    ARRIVAL = 1

    @property
    def title(self):
        return "Завершение" if self == EventKind.COMPLETION else "Генерация"


@dataclass(frozen=True)
class Event:
    at: float
    kind: EventKind
    origin_id: int
    serial: int

    def sort_key(self):
        return self.at, self.kind, self.origin_id, self.serial


class EventCalendar:
    def __init__(self):
        self._events = []
        self._next_serial = 0

    def __bool__(self):
        return bool(self._events)

    def _schedule(self, at, kind, origin_id):
        self._next_serial += 1
        event = Event(at, kind, origin_id, self._next_serial)
        heappush(self._events, (event.sort_key(), event))

    def schedule_arrival(self, at, source_id):
        self._schedule(at, EventKind.ARRIVAL, source_id)

    def schedule_completion(self, at, device_id):
        self._schedule(at, EventKind.COMPLETION, device_id)

    def pop_next(self):
        return heappop(self._events)[1] if self._events else None

    def discard_arrivals(self):
        self._events = [entry for entry in self._events if entry[1].kind == EventKind.COMPLETION]
        heapify(self._events)

    def snapshot(self):
        return tuple(event for _, event in sorted(self._events))
