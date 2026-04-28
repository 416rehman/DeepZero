---
layout: default
title: Справочник CLI
order: 1
---

## Интерфейс командной строки

CLI `deepzero` — это основной интерфейс для выполнения и управления конвейерами.

```bash
# Стандартное выполнение
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# Выполнить с очисткой состояния (новый запуск)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# Проверить статус выполнения
deepzero status -p loldrivers

# Запустить интерактивную REPL
deepzero interactive -w work/loldrivers

# Запустить REST API Starlette
deepzero serve -w work/loldrivers --port 8420

# Создать новый пользовательский конвейер
deepzero init my_custom_pipeline

# Проверить схему без выполнения
deepzero validate loldrivers

# Список системного реестра
deepzero list-processors
```

### Основные команды

| Команда | Описание |
| ------- | -------- |
| `run` | Выполняет конвейер. Автоматически возобновляется, если существует состояние. |
| `status` | Показывает текущий статус работы конвейера и метрики этапов. |
| `interactive` | Интерактивная REPL на базе LLM для анализа результатов. |
| `serve` | Запускает сервер REST API для вывода состояния конвейера. |
| `init` | Создает новую директорию конвейера со стандартным файлом `pipeline.yaml`. |
| `validate` | Выполняет тестовую проверку схемы конвейера и импорта процессоров. |
| `list-processors` | Показывает все встроенные и динамически зарегистрированные типы процессоров. |
