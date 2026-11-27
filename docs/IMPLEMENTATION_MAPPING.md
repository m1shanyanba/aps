# Соответствие программы первичным артефактам

**Вариант №26. Жирнов М. С., 5130904/40101.**

`ИБ — ИЗ2 — ПЗ1 — Д1ОЗ3 — Д1ОО4 — Д2П2 — Д2Б3 — ОР1 — ОД2`

| Дисциплина | Диаграмма | Класс | Метод | Тест |
| --- | --- | --- | --- | --- |
| ИБ | [Успешная последовательность](artifacts/sequence-happy-flow.puml) | `Source`, `Simulator` | `generate`, `_arrival`, `initialize` | `test_independent_generation_and_uniform_interval`, `test_generation_stops_but_tail_is_served` |
| ИЗ2 | [Успешная последовательность](artifacts/sequence-happy-flow.puml) | `Source` | `sample_interval` | `test_random_intervals_have_expected_range_and_mean` и контроль значений U |
| ПЗ1 | [Успешная последовательность](artifacts/sequence-happy-flow.puml) | `Device`, `EventCalendar` | `start`, `_sample_duration`, `schedule_completion` | `test_service_uses_exponential_sampler`, `test_all_documented_states_and_balance` |
| Д1ОЗ3 | [Блок-схема](artifacts/flowchart.puml) | `Buffer`, `PlacementDispatcher` | `find_first_free`, `put`, `place` | `test_first_free_slot_and_no_shift` |
| Д1ОО4 | [Переполнение](artifacts/sequence-buffer-overflow.puml) | `PlacementDispatcher`, `Buffer`, `StatisticsCollector` | `place`, `find_newest`, `record_drop` | `test_overflow_evicts_latest_even_in_middle_and_counts_owner`, `test_all_documented_states_and_balance` |
| Д2П2 | [Выбор прибора](artifacts/sequence-device-selection.puml) | `SelectionDispatcher` | `_find_free_device`, `_advance_pointers`, `dispatch` | `test_skip_busy_and_empty_wrap_and_independent_pointers`, `test_loop_assigns_several_and_wraps_device_pointer` |
| Д2Б3 | [Выбор заявки](artifacts/sequence-buffer-selection.puml) | `Buffer`, `SelectionDispatcher` | `find_occupied`, `take`, `dispatch` | `test_skip_busy_and_empty_wrap_and_independent_pointers`, `test_failed_assignment_does_not_move_pointers_or_extract` |
| ОР1 | [Блок-схема](artifacts/flowchart.puml) | `StatisticsCollector`, `Simulator`, `App` | `report`, `run`, `_finish_auto` | `test_missing_data_and_partial_utilization`, `test_fixed_batches_match_core`, `test_auto_study_graph_and_export_controls` |
| ОД2 | [Формализованная схема](artifacts/formalized-scheme.puml) | `Simulator`, `App` | `step`, `snapshot`, `_show_step` | `test_all_documented_states_and_balance`, `test_step_manual_controls_and_calendar` |

## Вызовы на sequence-диаграммах

Названия классов перенесены буквально. Методы Python используют `snake_case`. Внутренние операции из диаграммы обозначены начальным подчёркиванием.

| Действие | Имена в диаграммах и соответствующий код |
| --- | --- |
| Календарь и генерация | `popNext → pop_next`, `scheduleArrival → schedule_arrival`, `discardArrivals → discard_arrivals`, `generate`, `sampleInterval → sample_interval`. Вызовы соединены в `advance` и `_arrival`. |
| Постановка | `place`, `findFirstFree → find_first_free`, `findNewest → find_newest`, `peek`, `markDropped → mark_dropped`, `take`, `put`. Счётчик отказа обращается напрямую к полю `Request.source_id`, соответствующему `sourceId()`. |
| Планирование | `dispatch`, `findFreeDevice → _find_free_device`, `isFree → is_free`, `findOccupied → find_occupied`, `take`, `start`, `sampleDuration → _sample_duration`, `advancePointers → _advance_pointers`, `scheduleCompletion → schedule_completion`. |
| Завершение | `complete`, `recordCompletion → record_completion`, `release`, `dispatch`. Порядок в `Simulator._completion`. |
| Учёт и журнал | `recordGenerated → record_generated`, `recordDrop → record_drop`, `recordQueued → record_queued`, `recordStart → record_start`, `recordCompletion → record_completion`. Выбор узла и ячейки, освобождение и остановка записываются в журнал того же события. |

Пройдена статическая сверка всех 148 стрелок вызовов с получателями, методами и количеством аргументов. В общем прогоне порядок `(время, тип, участник, серийный номер)` и триггеры совпадают с [архитектурой](architecture-decisions.md). Полная трасса сравнивается с Markdown в [тесте сценария](../tests/test_scenario.py).

## Уточнения реализации

- Параметры a, b и μ из формы применяются ко всем соответствующим элементам. Объекты датчиков и приборов хранят свои параметры и отдельные состояния RNG.
- Свойства событий и заявок доступны как поля Python. Пара `step` и `advance` позволяет одному алгоритму работать и со снимком, и без копирования состояния. Это сохраняет правила обеих диаграмм и ограничивает память автоматического режима.
- На первой итерации подбора проводится пилот. Для подтверждения точности нужны два пригодных прогона с минимум десятью отказами и десятью успехами в каждом. Это ограничение оценки, дисциплины СМО остаются прежними.
- Учёт ожидания в программе использует отметку генерации, а в архитектуре написана отметка постановки. Они равны, потому что оба перехода выполняются в одном событии, поэтому результаты совпадают.
- Утверждённые диаграммы сохранены. Полная sequence-диаграмма сворачивает повторяющиеся вызовы в блоки `ref`, а модель исполняет их при каждой соответствующей записи календаря.

## Финальная проверка

| Проверка | Результат |
| --- | --- |
| Формула и предметная область | Пересверены с приложением 1 пособия, бизнес-доменом и маппингом. Все девять дисциплин соответствуют варианту №26. |
| Ядро и статистика | Проверены равномерная генерация, экспоненциальное обслуживание, буфер, оба кольца, календарь, промежуточные значения и полные отчёты. |
| Детерминированная трасса | Проверены все 16 состояний, включая старт. Конец на t = 18, баланс 8 = 7 + 1. |
| Интерфейс | Пройдены проверки реального Tkinter под Xvfb. Проверены форма, пошаговый режим и календарь, кнопки воспроизведения и паузы, фиксированный прогон, история подбора, график и экспорт CSV. |
| Оценка объёма | Проверены подтверждённый прогон, нулевая оценка, недостающие наблюдения и пределы. Отчёт явно различает подтверждение по пособию и остановку без подтверждения. |
| Исследование | Проверены диапазоны, пропуск недопустимых сочетаний, отбор оптимума, отсутствие подходящих строк, экономика и CSV. |
