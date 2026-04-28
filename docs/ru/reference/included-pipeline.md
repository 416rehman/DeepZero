---
layout: default
title: Конвейер LOLDrivers
order: 3
---

## Справочник конвейера LOLDrivers

Эталонный конвейер BYOVD (Bring Your Own Vulnerable Driver) поддерживается в `pipelines/loldrivers/`.

1. **discover:** Прием PE и разбор заголовков LIEF.
2. **kernel_filter:** Обработка ограничений до драйверов режима ядра, предоставляющих поверхности IOCTL.
3. **loldrivers_filter:** Исключение известных сущностей из loldrivers.io.
4. **decompile:** Безголовая декомпиляция Ghidra.
5. **semgrep_scanner:** Массовый статический анализ экспортированного исходного кода C.
6. **pick_top_10:** Эвристическое сокращение до главных кандидатов.
7. **assess:** Инъекция подсказок LLM и логическая оценка.
