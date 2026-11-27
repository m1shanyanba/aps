"""Диспетчер постановки и отдельный планировщик обработки."""


class PlacementDispatcher:
    def __init__(self, buffer, stats):
        self._buffer = buffer
        self._stats = stats

    def place(self, request, now):
        slot = self._buffer.find_first_free()
        if slot is None:
            slot = self._buffer.find_newest()
            victim = self._buffer.peek(slot)
            victim.mark_dropped(now)
            self._stats.record_drop(victim, now, slot)
            self._buffer.take(slot)
        self._buffer.put(slot, request, now)
        self._stats.record_queued(request, now, slot)


class SelectionDispatcher:
    def __init__(self, buffer, devices, calendar, stats):
        self._buffer = buffer
        self._devices = devices
        self._calendar = calendar
        self._stats = stats
        self._next_device = 1
        self._next_slot = 1

    def device_pointer(self):
        return self._next_device

    def buffer_pointer(self):
        return self._next_slot

    def _find_free_device(self):
        for offset in range(len(self._devices)):
            index = (self._next_device - 1 + offset) % len(self._devices)
            if self._devices[index].is_free():
                return index + 1
        return None

    def _advance_pointers(self, device, slot):
        self._next_device = device % len(self._devices) + 1
        self._next_slot = slot % self._buffer.capacity + 1

    def dispatch(self, now):
        while True:
            device = self._find_free_device()
            if device is None:
                self._stats.log(now, "Все узлы заняты. Указатели остаются на местах.")
                return
            slot = self._buffer.find_occupied(self._next_slot)
            if slot is None:
                self._stats.log(now, "Буфер пуст. Указатели остаются на местах.")
                return

            self._stats.log(now, f"Д2П2. От УП={self._next_device} выбран П{device}.")
            request = self._buffer.take(slot)
            self._stats.log(now, f"Д2Б3. От УБ={self._next_slot} выбрана ячейка {slot}, сообщение {request.label}.")
            due_at = self._devices[device - 1].start(request, now)
            self._advance_pointers(device, slot)
            self._calendar.schedule_completion(due_at, device)
            self._stats.record_start(request, now, slot, device)
