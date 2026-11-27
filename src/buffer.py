"""Общий буфер СМО. Номера ячеек в модели начинаются с единицы."""


class Buffer:
    def __init__(self, capacity):
        self._slots = [None] * capacity
        self._placement_order = 0
        self.used = 0

    @property
    def capacity(self):
        return len(self._slots)

    def find_first_free(self):
        for slot, request in enumerate(self._slots, 1):
            if request is None:
                return slot
        return None

    def find_newest(self):
        newest_slot = None
        newest_order = 0
        for slot, request in enumerate(self._slots, 1):
            if request is not None and request.placement_order > newest_order:
                newest_slot = slot
                newest_order = request.placement_order
        return newest_slot

    def find_occupied(self, from_slot):
        for offset in range(self.capacity):
            index = (from_slot - 1 + offset) % self.capacity
            if self._slots[index] is not None:
                return index + 1
        return None

    def peek(self, slot):
        request = self._slots[slot - 1]
        if request is None:
            raise RuntimeError("Ячейка буфера пуста.")
        return request

    def put(self, slot, request, now):
        if self._slots[slot - 1] is not None:
            raise RuntimeError("Ячейка буфера уже занята.")
        self._placement_order += 1
        request.mark_queued(now, self._placement_order)
        self._slots[slot - 1] = request
        self.used += 1

    def take(self, slot):
        request = self.peek(slot)
        self._slots[slot - 1] = None
        self.used -= 1
        return request

    def snapshot(self):
        return tuple(request.snapshot() if request else None for request in self._slots)
