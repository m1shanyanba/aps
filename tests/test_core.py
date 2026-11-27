from random import Random
from unittest import TestCase
from unittest.mock import Mock, patch

from src.buffer import Buffer
from src.calendar import EventCalendar, EventKind
from src.dispatchers import PlacementDispatcher, SelectionDispatcher
from src.models import Device, Request, Source, TrialConfig
from src.simulator import Simulator, manual_simulation
from src.statistics import StatisticsCollector


def message(number, source=1):
    return Request(source, number, "Температура", 60.0, 0)


class TestSource(TestCase):
    def test_independent_generation_and_uniform_interval(self):
        random = Mock()
        random.random.side_effect = (0, .25, .5, .75)
        random.uniform.return_value = 60
        source = Source(1, 2, 6, random)
        self.assertEqual([source.sample_interval() for _ in range(4)], [2, 3, 4, 5])
        self.assertEqual(source.generate(3).label, "1.1")
        second = source.generate(4)
        self.assertEqual((second.label, second.generated_at, second.value), ("1.2", 4, 60))
        self.assertIsNone(second.start_at)

    def test_random_intervals_have_expected_range_and_mean(self):
        source = Source(1, 2, 6, Random(26))
        intervals = [source.sample_interval() for _ in range(5000)]
        self.assertTrue(all(2 <= interval < 6 for interval in intervals))
        self.assertAlmostEqual(sum(intervals) / len(intervals), 4, delta=.08)

    def test_service_uses_exponential_sampler(self):
        rng = Mock()
        rng.expovariate.return_value = 2.5
        device = Device(1, .7, rng)
        request = message(1)
        self.assertEqual(device.start(request, 10), 12.5)
        rng.expovariate.assert_called_once_with(.7)
        self.assertEqual(request.start_at, 10)
        self.assertFalse(device.is_free())


class TestBufferAndDispatchers(TestCase):
    def setUp(self):
        self.buffer = Buffer(3)
        self.stats = StatisticsCollector(2, 2)
        self.placement = PlacementDispatcher(self.buffer, self.stats)
        self.devices = [Device(i, 1, Random(i), [2, 2, 2]) for i in (1, 2)]
        self.calendar = EventCalendar()
        self.selection = SelectionDispatcher(self.buffer, self.devices, self.calendar, self.stats)

    def pointers(self):
        return self.selection.buffer_pointer(), self.selection.device_pointer()

    def test_first_free_slot_and_no_shift(self):
        for n in range(1, 4):
            self.placement.place(message(n), 0)
        self.buffer.take(2)
        self.assertEqual([q.number if q else None for q in self.buffer.snapshot()], [1, None, 3])
        self.assertEqual(self.buffer.find_first_free(), 2)
        self.placement.place(message(4), 0)
        self.assertEqual([q.number for q in self.buffer.snapshot()], [1, 4, 3])

    def test_overflow_evicts_latest_even_in_middle_and_counts_owner(self):
        for n in range(1, 4):
            self.placement.place(message(n), 0)
        self.buffer.take(2)
        victim = message(4, source=2)
        self.placement.place(victim, 0)
        self.assertEqual(self.buffer.find_newest(), 2)
        saved_pointers = self.pointers()
        new = message(5)
        self.placement.place(new, 1)
        self.assertIs(self.buffer.peek(2), new)
        self.assertEqual((victim.outcome, victim.ended_at), ("отказ", 1))
        self.assertEqual(self.stats.by_source[1].dropped, 0)
        self.assertEqual(self.stats.by_source[2].dropped, 1)
        self.assertEqual(self.pointers(), saved_pointers)

    def test_loop_assigns_several_and_wraps_device_pointer(self):
        self.placement.place(message(1), 0)
        self.placement.place(message(2), 0)
        self.selection.dispatch(0)
        self.assertEqual([device.current.number for device in self.devices], [1, 2])
        self.assertEqual(self.pointers(), (3, 1))
        self.assertEqual(len(self.calendar.snapshot()), 2)

    def test_skip_busy_and_empty_wrap_and_independent_pointers(self):
        self.devices[0].start(message(1), 0)
        self.buffer.put(3, message(2), 0)
        self.selection.dispatch(0)
        self.assertEqual(self.devices[1].current.number, 2)
        self.assertEqual(self.pointers(), (1, 1))
        self.devices[0].release()
        self.buffer.put(2, message(3), 1)
        self.selection.dispatch(1)
        self.assertEqual(self.pointers(), (3, 2))
        self.devices[0].release()
        self.buffer.put(1, message(4), 2)
        self.selection.dispatch(2)
        self.assertEqual(self.devices[0].current.number, 4)
        self.assertEqual(self.pointers(), (2, 2))

    def test_failed_assignment_does_not_move_pointers_or_extract(self):
        self.selection.dispatch(0)
        self.assertEqual(self.pointers(), (1, 1))
        for device in self.devices:
            device.start(message(device.id), 0)
        request = message(3)
        self.placement.place(request, 0)
        self.selection.dispatch(0)
        self.assertIs(self.buffer.peek(1), request)
        self.assertEqual(self.pointers(), (1, 1))


class TestSimulator(TestCase):
    def test_calendar_ties_sort_by_type_origin_and_serial(self):
        calendar = EventCalendar()
        calendar.schedule_arrival(2, 2)
        calendar.schedule_completion(2, 2)
        calendar.schedule_arrival(2, 1)
        calendar.schedule_completion(2, 1)
        calendar.schedule_completion(2, 1)
        calendar.schedule_arrival(1, 3)
        self.assertEqual([calendar.pop_next().serial for _ in range(6)], [6, 4, 5, 2, 3, 1])
        self.assertIsNone(calendar.pop_next())

    def test_coincident_completion_moves_waiting_request_before_arrival(self):
        c = TrialConfig(sources=2, devices=1, capacity=1, limit=3)
        s = Simulator(c, intervals={1: (2, 20), 2: (1, 10)}, durations={1: (10, 3, 1)})
        s.step()
        s.step()
        finish = s.step()
        arrive = s.step()
        self.assertEqual((finish.now, arrive.now), (11, 11))
        self.assertEqual((finish.event.kind, arrive.event.kind), (EventKind.COMPLETION, EventKind.ARRIVAL))
        self.assertEqual(arrive.devices[0].current.label, "1.1")
        self.assertEqual(arrive.slots[0].label, "2.2")
        self.assertEqual(arrive.report.total.dropped, 0)

    def test_arrival_and_completion_trigger_same_selection(self):
        s = manual_simulation()
        with patch.object(s.selection, "dispatch", wraps=s.selection.dispatch) as choose:
            s.run()
        self.assertEqual(choose.call_count, 15)

    def test_generation_stops_but_tail_is_served(self):
        s = manual_simulation()
        while s.remaining:
            state = s.step()
        self.assertEqual(state.now, 15)
        self.assertFalse(state.finished)
        self.assertEqual({e.kind for e in state.calendar}, {EventKind.COMPLETION})
        self.assertEqual(s.run().now, 18)
        self.assertIsNone(s.step())

    def test_reproducible_step_and_fast_run(self):
        config = TrialConfig(sources=4, devices=2, capacity=4, limit=400)
        manual = Simulator(config)
        while manual.step() is not None:
            pass
        fast = Simulator(config, journal=False)
        result = fast.run()
        self.assertEqual(result, manual.report())
        self.assertEqual(result, Simulator(config, journal=False).run())
        self.assertNotEqual(result, Simulator(TrialConfig(limit=400, seed=27)).run())
        self.assertFalse(fast.stats.transitions())

    def test_missing_data_and_partial_utilization(self):
        s = manual_simulation()
        init = s.snapshot().report
        self.assertIsNone(init.total.loss)
        self.assertIsNone(init.total.wait)
        self.assertIsNone(init.devices[0].utilization)
        s.step()
        state = s.step()
        self.assertEqual(state.report.devices[0].busy, 1)
        self.assertEqual(state.report.devices[0].utilization, .5)
        self.assertIsNone(state.report.total.residence)

    def test_rejects_invalid_parameters(self):
        for fields in ({"a": 3}, {"b": float("inf")}, {"mu": 0}, {"capacity": 0}, {"sources": 1.5}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                TrialConfig(**fields)
