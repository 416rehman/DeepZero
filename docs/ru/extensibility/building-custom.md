---
layout: default
title: Создание Процессоров
order: 2
---

## Создание Пользовательских Процессоров

Пользовательская логика интегрируется в DeepZero путем наследования типизированных абстракций в `deepzero.engine.stage`. Чтобы понять, как эти этапы соотносятся с фазами выполнения, см. [Базовую Архитектуру]({{ '/ru/overview/architecture.html' | relative_url }}).

### Контекст Процессора (`ProcessorContext`)

Объект `ctx`, внедряемый в каждый хук жизненного цикла, обеспечивает системный контекст и вспомогательные средства:
- `ctx.pipeline_dir`: Корневой каталог запущенного конвейера, полезен для поиска локальных шаблонов и наборов правил.
- `ctx.global_config`: TypedDict, содержащий `settings`, `knowledge` и настроенную `model` уровня конвейера. `ctx.get_setting(key)` и `ctx.get_knowledge(key)` являются сокращениями для доступа к нему.
- `ctx.llm`: Экземпляр обобщенного прокси (реализующего `LLMProtocol`) со встроенными задержками и повторами, либо `None`, если конвейер не задает модель. Какой бэкенд за ним стоит, определяется строкой `model` конвейера, поэтому процессор, вызывающий `ctx.llm.complete()`, работает одинаково и с ключом API, и с локальным агентским CLI. См. [Выбор Модели]({{ '/ru/reference/pipeline-yaml.html' | relative_url }}).
- `ctx.log`: Настроенный `logging.Logger` в своем пространстве имен.
- `ctx.progress`: Хук отчета о прогрессе, `update(amount=, total=, description=)`, чтобы долгий этап приема или пакетной обработки показывал движение на панели, а не выглядел зависшим.
- `ctx.shutdown_event`: Объект `threading.Event`, устанавливаемый при прерывании запуска. Процессор, выполняющий долгую работу, должен проверять его и завершаться досрочно, а не быть убитым посреди записи.

### Хуки Выполнения

Процессоры реализуют определенные хуки жизненного цикла, вызываемые движком:

1. **`validate(ctx: ProcessorContext) -> list[str]`**: Вызывается при первичной проверке схемы (через `deepzero validate` или перед выполнением). Возвращает список строк с ошибками, если зависимости не удовлетворены (например, отсутствует бинарный файл или YAML не разбирается).
2. **`setup(global_config: dict) -> None`**: Выполняется ровно один раз до активации пула потоков.
3. **`process(...)`**: Основная операция. Сигнатура зависит от типа процессора.
4. **`teardown() -> None`**: Выполняется по завершении конвейера или при фатальном прерывании.

Еще один стоит переопределять у процессора Map, который дорого обходится на каждом образце:

5. **`max_parallelism() -> int | None`**: Потолок автоматического параллелизма. Применяется, только когда этап объявляет `parallel: 0`; явное `parallel: N` всегда соблюдается как написано. Возвращайте число, когда каждый образец стоит JVM, контейнера или нескольких гигабайт памяти, чтобы конвейер, оставленный на значении по умолчанию, не мог исчерпать машину. `None`, значение по умолчанию, означает отсутствие потолка.

### Определения Конфигурации

Используйте вложенный `@dataclass` с именем `Config`, чтобы строго определить и проверить принимаемые конфигурации YAML. Движок разбирает словарь [YAML Конвейера]({{ '/ru/reference/pipeline-yaml.html' | relative_url }}) и создает экземпляр вашего объекта `Config`, автоматически раскрывая `${ENV_VARS}` средствами стандартных [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) Python.

```python
from dataclasses import dataclass
from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorEntry, ProcessorResult

class BinaryAnalyzer(MapProcessor):
    description = "Static heuristics extraction"

    @dataclass
    class Config:
        target_arch: str = "x86_64"
        max_entropy: float = 7.5

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        # получаем данные, выданные вышестоящим IngestProcessor
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")
        
        # ProcessorEntry привязан к изолированной песочнице каждого образца
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text('{"entropy": 7.1}')
        
        # ProcessorResult определяет дальнейшую маршрутизацию
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")
            
        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": True}
        )
```

### Результаты Выполнения (`ProcessorResult`)

Процессоры Map/BulkMap обязаны возвращать строго оформленный `ProcessorResult`:
- **`.ok(data={...}, artifacts={...})`**: Помечает выполнение как `COMPLETED`. Словарь `data` попадает в блок истории данного процессора. `artifacts` сопоставляет ключи относительным путям к файлам.
- **`.filter(reason="...", data={...})`**: Молча прекращает обработку образца. `SampleState.verdict` меняется на `FILTERED`.
- **`.fail(error="...")`**: Прекращает обработку из-за фатальной непредвиденной ошибки. `SampleState.verdict` меняется на `FAILED`.
- **`.timed_out(budget)`**: Работа исчерпала время, а не пошла не так. `SampleState.verdict` меняется на `TIMED_OUT`, и бюджет едет вместе с ним, чтобы отчет мог сказать, сколько дать взамен. Возвращайте это из процессора, который следит за собственным бюджетом; `timeout:` на уровне этапа производит такой результат сам.

Процессор Map может также переопределить **`should_skip(ctx, entry) -> str | None`**, возвращая причину, по которой работу можно считать уже сделанной, обычно потому, что его собственный выходной файл уже лежит на диске. Пропущенный образец засчитывается как прошедший и идет дальше по конвейеру. Записывайте при этом вывод как артефакт: `deepzero run --redo` удаляет записанные артефакты именно затем, чтобы закэшированный файл нельзя было подхватить снова, а файл, который запуск не записал, переживет описывающее его состояние.

### Объявление Того, Чем Смогут Пользоваться Следующие Этапы

Ключи `data` и артефакты процессора становятся доступны промптам этапов, выполняющихся после него. Объявите эти имена в `provides`, чтобы `deepzero validate` мог проверить промпт до запуска, а не позволял неизвестному имени отрендериться в пустоту:

```python
class Decompiler(MapProcessor):
    description = "Static heuristics extraction"
    provides = (
        "device_name",                    # ключ, который этот процессор кладет в data
        "decompiled_dispatch_ioctl_c",    # артефакт decompiled/dispatch_ioctl.c
    )
```

Имя артефакта строится из его пути, в который сворачиваются разделители и расширение; `template_key_for_artifact` в `engine/stage.py` является единственным правилом, которое используют и рендеринг, и проверка. Перечисляйте и те имена, которые записываются лишь иногда: предполагается, что промпт переживет их отсутствие. О том, что получает промпт, см. [Значения для Промптов]({{ '/ru/reference/pipeline-yaml.html' | relative_url }}).

### Доступ к Вышестоящим Данным

Процессоры по своей природе опираются на артефакты и данные, созданные предшественниками. Фасад `ProcessorEntry` предоставляет вспомогательные методы с отложенной загрузкой, чтобы получать эти данные без лишних усилий:

```python
# сокращенное извлечение конкретного поля (со значением по умолчанию)
sha = entry.upstream_data("discover", "sha256", default="")

# полное извлечение объекта StageOutput предыдущего этапа
output = entry.upstream("scan")
findings = output.data.get("finding_count", 0)
json_file = output.artifacts.get("findings_file")
```

### Базовые Классы

В зависимости от требований к топологии вашего конвейера наследуйтесь от подходящего базового класса:

| Базовый класс | Тип процессора | Сигнатура `process()` |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` |
