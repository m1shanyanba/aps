import csv
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from src.experiments import (AccuracyIteration, Costs, best_index, configuration_grid, estimate_accuracy,
                             evaluate, export_csv, graph_slice, parse_range, required_sample_size,
                             run_in_batches, study)
from src.models import TrialConfig
from src.simulator import Simulator


def consume(job):
    updates = []
    while True:
        try:
            updates.append(next(job))
        except StopIteration as stop:
            return updates, stop.value


class TestExperiments(TestCase):
    def test_fixed_batches_match_core(self):
        config = TrialConfig(limit=600)
        updates, report = consume(run_in_batches(config))
        self.assertTrue(updates)
        self.assertEqual(report, Simulator(config).run())

    def test_formula_and_reporting_confirmation(self):
        self.assertEqual(required_sample_size(.2), 1080)
        self.assertIsNone(required_sample_size(0))
        self.assertIsNone(required_sample_size(1))
        config = TrialConfig(sources=4, devices=1, capacity=2, a=1, b=2, mu=.35, limit=100)
        updates, result = consume(estimate_accuracy(config, 10000, 8))
        history = [update for update in updates if isinstance(update, AccuracyIteration)]
        self.assertTrue(result.converged)
        self.assertGreaterEqual(len(history), 2)
        self.assertGreaterEqual(history[-1].size, history[-1].estimate)
        self.assertLess(history[-1].change, 0.1)
        self.assertEqual(history[-1].probability, result.report.total.loss)

    def test_zero_or_too_few_observations_is_not_a_confirmation(self):
        config = TrialConfig(sources=1, devices=1, capacity=1, a=10, b=11, mu=50, limit=5)
        updates, result = consume(estimate_accuracy(config, 20, 4))
        history = [update for update in updates if isinstance(update, AccuracyIteration)]
        self.assertEqual([it.size for it in history], [5, 10, 20])
        self.assertTrue(all(it.probability == 0 for it in history))
        self.assertFalse(result.converged)
        self.assertIn("предел заявок", result.message)

    def test_iteration_limit(self):
        config = TrialConfig(sources=1, devices=1, capacity=1, a=10, b=11, mu=50, limit=5)
        _, result = consume(estimate_accuracy(config, 100000, 2))
        self.assertFalse(result.converged)
        self.assertIn("предел итераций", result.message)

    def test_ranges_and_invalid_generation_pair(self):
        self.assertEqual(parse_range("0,1:0,3:0,1"), (.1, .2, .3))
        self.assertEqual(parse_range("2:5:2", True), (2, 4))
        for invalid in ("1:2:0", "4:2:1", "NaN", "1:3", "0.3"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_range(invalid, True)
        grid, skipped = configuration_grid(TrialConfig(), [(2,), (3,), (5,), (.5, 2), (1, 3), (1,)])
        self.assertEqual((len(grid), skipped), (3, 1))

    def test_study_csv_graph_and_economics(self):
        c = TrialConfig(sources=2, devices=1, capacity=3, limit=300)
        grid = [c, replace(c, capacity=4)]
        costs = Costs(2, .5, .1)
        _, rows = consume(study(grid, .1, costs))
        self.assertEqual(len(rows), 2)
        report = rows[0].report
        self.assertAlmostEqual(rows[0].expense, report.total.dropped * 2 + report.now * (.5 + 3 * .1))
        self.assertAlmostEqual(rows[0].expense_per_success, rows[0].expense / report.total.completed)
        self.assertEqual(graph_slice(rows, 0, "capacity"), rows)
        self.assertEqual(graph_slice(rows, 0, "devices"), rows[:1])
        # Проверка выбора по Tпреб, затем по затратам на успешную заявку.
        total = replace(report.total, loss=.05, residence=3.0)
        valid = evaluate(c, replace(report, total=total, utilization=.9), .05, costs)
        self.assertTrue(valid.eligible)
        self.assertIsNone(best_index([evaluate(c, replace(report, utilization=.7), .05, costs)]))
        self.assertEqual(best_index([replace(valid, expense_per_success=3), replace(valid, expense_per_success=2)]), 1)
        faster = replace(valid, report=replace(valid.report, total=replace(total, residence=2)))
        self.assertEqual(best_index([faster, replace(valid, expense_per_success=0)]), 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "данные.csv"
            export_csv(path, rows)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                exported = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(len(exported), 2)
        self.assertEqual(exported[0]["Отказы"], str(report.total.dropped))
        self.assertEqual(exported[0]["Цена отказа"], "2")
