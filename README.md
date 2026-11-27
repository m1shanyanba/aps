# Обработка телеметрии датчиков промышленного оборудования

Первичные проектные артефакты курсовой работы по моделированию системы массового обслуживания. **Вариант №26.** Студент **Жирнов М. С.**, группа **5130904/40101**.

`ИБ — ИЗ2 — ПЗ1 — Д1ОЗ3 — Д1ОО4 — Д2П2 — Д2Б3 — ОР1 — ОД2`

| Код | Дисциплина |
| --- | --- |
| ИБ | Каждый датчик независимо формирует бесконечный поток. |
| ИЗ2 | Интервалы между генерациями имеют равномерное распределение. |
| ПЗ1 | Длительности обслуживания имеют экспоненциальное распределение. |
| Д1ОЗ3 | Новое сообщение ставится в первую свободную ячейку при просмотре с начала. |
| Д1ОО4 | При полном буфере выбивается последняя поставленная из ожидающих заявок. Новая занимает её ячейку. |
| Д2П2 | Первый свободный прибор выбирается по кольцу от УП. |
| Д2Б3 | Первая занятая ячейка выбирается по кольцу от УБ. |
| ОР1 | Две сводные таблицы автоматического режима, по датчикам и приборам. |
| ОД2 | Формализованная схема и состояние СМО после каждого события. |

Датчики передают температуру, давление и вибрацию. Сервер помещает все сообщения в общий буфер. Планировщик запускается после постановки сообщения или освобождения узла, сначала ищет свободный прибор, затем ожидающее измерение и продолжает передачи, пока находит пары. Узел моделирует проверку, преобразование и сохранение измерения. При переполнении потеря учитывается у датчика, создавшего вытесненное сообщение. Календарь управляет переходами модельного времени. После последней генерации СМО завершает оставшееся обслуживание.

## Документация

| Файл | Содержание |
| --- | --- |
| [Бизнес-домен](docs/domain.md) | Описание системы из исходного документа |
| [Маппинг](docs/mapping.md) | Соответствие терминов СМО и предметной области |
| [Архитектурные решения](docs/architecture-decisions.md) | События, диспетчеры, статистика и структуры двух режимов |
| [Ручной сценарий](docs/scenarios.md) | Покадровый разбор перегрузки и проверка баланса |

## Диаграммы

| Диаграмма | Исходник | Изображение |
| --- | --- | --- |
| Классы | [PUML](docs/artifacts/classes.puml) | [PNG](docs/artifacts/classes.png) · [SVG](docs/artifacts/classes.svg) |
| Успешный сценарий | [PUML](docs/artifacts/sequence-happy-flow.puml) | [PNG](docs/artifacts/sequence-happy-flow.png) |
| Перегрузка и продолжение обслуживания | [PUML](docs/artifacts/sequence-full.puml) | [PNG](docs/artifacts/sequence-full.png) · [SVG](docs/artifacts/sequence-full.svg) |
| Переполнение и выбивание | [PUML](docs/artifacts/sequence-buffer-overflow.puml) | [PNG](docs/artifacts/sequence-buffer-overflow.png) |
| Кольцевой выбор сообщения | [PUML](docs/artifacts/sequence-buffer-selection.puml) | [PNG](docs/artifacts/sequence-buffer-selection.png) |
| Кольцевой выбор узла | [PUML](docs/artifacts/sequence-device-selection.puml) | [PNG](docs/artifacts/sequence-device-selection.png) |
| Завершение обслуживания | [PUML](docs/artifacts/sequence-service-completion.puml) | [PNG](docs/artifacts/sequence-service-completion.png) |
| Блок-схема с дорожками | [PUML](docs/artifacts/flowchart.puml) | [PNG](docs/artifacts/flowchart.png) · [SVG](docs/artifacts/flowchart.svg) |
| Формализованная схема ОД2 | [PUML](docs/artifacts/formalized-scheme.puml) | [PNG](docs/artifacts/formalized-scheme.png) |

## Генерация PNG

Изображения подготовлены в PlantUML 1.2025.10. Для повторной генерации понадобятся Java, Graphviz (`dot`) и шрифт DejaVu Sans. Из корня репозитория запустите команды, подставив путь к JAR.

```bash
plantuml_jar=/path/to/plantuml.jar
java -Djava.awt.headless=true -jar "$plantuml_jar" \
  -charset UTF-8 -failfast2 -checkonly docs/artifacts/*.puml
java -Djava.awt.headless=true -DPLANTUML_LIMIT_SIZE=8192 -jar "$plantuml_jar" \
  -charset UTF-8 -failfast2 -tpng docs/artifacts/*.puml
```

Для крупной схемы можно сгенерировать масштабируемое изображение той же командой с `-tsvg` вместо `-tpng`.
