---
layout: default
title: Базовая Архитектура
order: 2
---

## Архитектура Движка

Движок оркестрации DeepZero работает со строгим направленным графом обработки, определяемым [конвейерами]({{ '/ru/reference/pipeline-yaml.html' | relative_url }}). Механизм выполнения гарантирует отказоустойчивое, возобновляемое [управление состоянием]({{ '/ru/system/state-persistence.html' | relative_url }}), распределяя параллельные операции по ограниченному пулу потоков ([`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)).

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 400" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="flowGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--border)" />
                <stop offset="50%" stop-color="var(--text-tertiary)" />
                <stop offset="100%" stop-color="var(--border)" />
            </linearGradient>
            <pattern id="isoGridSmall" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#isoGridSmall)" opacity="0.3"/>

        <!-- Ingest Node -->
        <g transform="translate(150, 200)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--text-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">INGEST</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">1 → N</text>
        </g>

        <!-- Connecting Lines to Map -->
        <path d="M 210 170 L 250 150 L 300 150 L 350 125" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 350 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 250 190 L 300 190 L 350 215" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Map Nodes -->
        <g transform="translate(350, 90)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 160)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 230)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>

        <!-- Connecting Lines to Reduce -->
        <path d="M 430 90 L 480 115 L 520 115 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 160 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 230 L 480 205 L 520 205 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Reduce Node -->
        <g transform="translate(560, 180)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--accent)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--text-secondary)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--bg-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--bg-primary)" transform="skewX(30) rotate(-30)">REDUCE</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">N → M</text>
            
            <!-- Output stream -->
            <path d="M 60 10 L 90 -5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
            <path d="M 70 20 L 100 5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
        </g>
    </svg>
</div>

### Жизненные циклы компонентов

По мере продвижения образца модель данных проходит через следующие абстракции:

1. **`Sample`**: Базовая структура, выдаваемая процессором `IngestProcessor`. Связывает физический `source_path` с уникальным `sample_id` (обычно это хеш SHA-256 или детерминированный UUID) и инициализирует словарь `data` образца.
2. **`SampleState`**: Постоянная запись, поддерживаемая `StateStore`. Отслеживает вердикт образца (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `COMPLETED`) и ведет отображение `history` из экземпляров `StageOutput` по каждому процессору.
3. **`ProcessorEntry`**: Динамически создаваемый экономный по памяти фасад, передаваемый процессорам Map/BulkMap/Reduce. Он внедряет механизм отложенной загрузки (`_store`), который читает историю выполнения с диска только при обращении к `.history` или `.upstream_data()`.

### Модели обработки

Процессоры задают топологию выполнения и модель параллелизма. Все они наследуются от базового класса `Processor` и предоставляют хуки жизненного цикла: `validate()`, `setup()`, `process()` и `teardown()`. О том, как написать собственный, см. [Создание Пользовательских Процессоров]({{ '/ru/extensibility/building-custom.html' | relative_url }}).

#### `IngestProcessor` (1 → N)
- **Сигнатура типа:** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **Параллелизм:** Синхронный. Выполняется ровно один раз за запуск конвейера.
- **Роль:** Формирует исходный корпус. До этапа приема вышестоящих данных не существует.

#### `MapProcessor` (1 → 1)
- **Сигнатура типа:** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **Параллелизм:** Разветвление по потокам. Настраивается полем `parallel:` в YAML конвейера.
- **Ограничения:** Обязан быть строго потокобезопасным. Избегайте разделяемого изменяемого состояния.

#### `BulkMapProcessor` (N → N)
- **Сигнатура типа:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **Параллелизм:** Синхронное выполнение над частью или над всем множеством активных образцов.
- **Роль:** Оптимизирует вызовы внешних процессов (например, запуск монолитного инструмента на JVM или пакетное сканирование Semgrep), распределяя тяжелый старт на несколько образцов. Результаты должны строго соответствовать по индексам входному списку `entries`.

#### `ReduceProcessor` (N → M)
- **Сигнатура типа:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **Параллелизм:** Глобальный барьер синхронизации. Приостанавливает выполнение в потоках, пока все активные образцы не дойдут до этого этапа.
- **Роль:** Возвращает упорядоченный список строк `sample_id`, определяющий, какие образцы проходят дальше. Любой идентификатор образца, отсутствующий в возвращенном списке, окончательно помечается как `SampleStatus.FILTERED`.

### Контракт вывода

Что бы процессор ни делал, он записывает одни и те же три вещи: `data`, произвольный
словарь в своем пространстве имен; `artifacts`, отображение метки на относительный путь
к файлу; и статус. Этот контракт намеренно не привязан к предметной области, и на нем
построено все, что находится ниже движка.

Нагляднее всего это видно на [отчете]({{ '/ru/reference/cli.html' | relative_url }}). Отчет
представляет собой проекцию сохраненного состояния, а не этап конвейера: он читает те же
`data` и `artifacts`, которые мог бы прочитать любой процессор. Поэтому и поиск уязвимых
драйверов, и аудит исходного кода, и что угодно еще отображаются, притом что код отчета
не знает, что именно перед ним. Конвейер предоставляет только словарь терминов, и это
[блок YAML]({{ '/ru/reference/pipeline-yaml.html' | relative_url }}), а не код.

Поскольку отчет не содержит ничего, чего нет в каталоге запуска, его можно собрать во
время выполнения, пересобрать после удаления и пересобрать снова для запуска, который
завершился недели назад. То же свойство делает заменяемым и слой LLM: бэкенд выбирается
по строке модели из конвейера, и ни один процессор, этап или файл состояния не знает,
какой из них ответил.
