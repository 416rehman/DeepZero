---
layout: default
title: YAML Конвейера
order: 2
---

## Конфигурация Конвейера

**Конвейер (Pipeline)** в DeepZero — это декларативный граф выполнения, определяющий процесс преобразования данных. Схема строго определена в YAML.

### Схема Конфигурации

```yaml
name: my_pipeline
description: Стандартный конвейер поиска уязвимостей
version: "1.0"
model: openai/gpt-4o

settings:
  work_dir: work
  max_workers: 8

stages:
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]
```

### Параметры Этапов

| Поле | Тип | По умолчанию | Описание |
|-------|------|---------|-------------|
| `name` | string | `stage_N` | Уникальное имя этапа |
| `processor` | string | требуется | Ссылка на процессор |
| `config` | dict | `{}` | Настройки процессора |
| `parallel` | int | `4` | Параллелизм для Map процессоров |
