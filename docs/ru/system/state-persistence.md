---
layout: default
title: Сохранение Состояния
order: 1
---

## Подсистема Персистентности

Целостность данных обеспечивается модулем `StateStore` (определен в `engine/state.py`). Операции, выполняемые в файловой системе, надежно защищены от повреждения, даже при SIGKILL или прерывании на уровне ОС, за счет строгой атомарной замены файлов.

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 250" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <pattern id="isoGridState" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#isoGridState)" opacity="0.3"/>
        
        <!-- Memory Node -->
        <g transform="translate(100, 120)">
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="8"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">Память</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">SampleState</text>
        </g>

        <!-- Path to Temp -->
        <path d="M 220 120 L 320 120" fill="none" stroke="var(--text-tertiary)" stroke-width="2" stroke-dasharray="6 6"/>
        <text x="270" y="110" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-secondary)">Сериализация</text>
        
        <!-- Temp Node -->
        <g transform="translate(320, 120)">
            <rect x="0" y="-40" width="140" height="80" fill="var(--bg-secondary)" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" rx="8"/>
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.json.tmp</text>
            <text x="70" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Буфер</text>
        </g>
        
        <!-- Path to Final -->
        <path d="M 460 120 L 580 120" fill="none" stroke="var(--accent)" stroke-width="3"/>
        <circle cx="0" cy="0" r="5" fill="var(--accent)">
            <animateMotion path="M 460 120 L 580 120" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <text x="520" y="110" font-family="Inter, sans-serif" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--accent)">os.replace</text>
        <text x="520" y="140" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)">Атомарная замена</text>
        
        <!-- Final Node -->
        <g transform="translate(580, 120)">
            <rect x="-10" y="-30" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="-5" y="-35" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="4"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">state.json</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">На диске</text>
        </g>
    </svg>
</div>

### Атомарные Замены (`atomic_replace`)

Вместо прямой записи в артефакты (например, `state.json`), уровень персистентности использует временные `.tmp` буферы. После завершения сериализации операция `os.replace` принудительно перезаписывает целевой inode. Механизм повторов с задержкой перехватывает блокировки `PermissionError`, которые возникают, когда EDR или антивирус на хосте проверяет только что созданные файлы.

### Версионирование Схемы

Все объекты состояния помечены внутренним `STATE_VERSION`. Если при десериализации движок встречает расхождение схемы (например, читает JSON версии v1 в среде выполнения v2), он явно объявляет объект состояния устаревшим, вместо того чтобы порождать непредсказуемые ошибки мутации.

### Иерархия Рабочего Пространства

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # Сериализованный `RunState`: метрики выполнения и метаданные конвейера
├── pipeline.yaml        # Неизменяемый снимок YAML конфигурации на момент инициализации
├── run_manifest.json    # Сводный обзор всех образцов (используется API Starlette)
├── report/              # HTML-отчет, перестраиваемый по мере появления результатов
└── samples/
    └── <sample_id>/     # Изолированная песочница
        ├── state.json   # Сериализованный `SampleState`: полный журнал карт `StageOutput`
        ├── context.md   # Контекст для LLM, собранный через `engine/context.py`
        └── ...          # Артефакты конкретных процессоров
```

### Разделение по Корпусам

Именно сегмент `<corpus_key>` разделяет две цели, прошедшие через один конвейер. Он
выводится из цели запуска: базовое имя плюс короткий дайджест разрешенного абсолютного
пути, поэтому остается и читаемым, и однозначным. В Windows путь сначала приводится к
единому регистру, поскольку `C:\Drivers` и `c:\drivers` обозначают один и тот же корпус.

Без этого сегмента запуск того же конвейера на втором корпусе возобновился бы в
хранилище образцов первого: образцы, которым на диске уже ничто не соответствует,
считались бы проанализированными, и запуск сообщил бы результаты по корпусу, который
ему никогда не передавали. С ним у каждого корпуса собственное состояние, собственный
манифест и собственный отчет, и каждый возобновляется независимо.

Один и тот же разрешенный путь всегда дает один и тот же ключ, поэтому повторный запуск
возвращается туда, где остановился. Все внутри этого каталога является производным:
`report/` в частности не содержит ничего, чего нет в состоянии запуска, и его удаление
стоит перестроения отчета, а не самого запуска.

### Журнал `history`

Словарь `SampleState.history` строго сопоставляет имена этапов процессоров с экземплярами `StageOutput`. Структуры выходных данных строго изолированы и разнесены по пространствам имен. Нижестоящий процессор, извлекающий метрики из вышестоящего map-этапа, обратится так: `history["upstream_processor"].data.get("metric")` (см. [Создание Пользовательских Процессоров]({{ '/ru/extensibility/building-custom.html' | relative_url }})).

Такое разнесение по пространствам имен окончательно исключает конфликт полей между разными методами эвристического анализа.
