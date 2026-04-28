---
layout: default
title: Быстрый старт
order: 1
---

## Быстрый старт

DeepZero требует целевого корпуса файлов для анализа и [конфигурации конвейера]({{ '/ru/reference/pipeline-yaml.html' | relative_url }}), детализирующей их обработку. Мы предоставляем [полный пример конвейера]({{ '/ru/reference/included-pipeline.html' | relative_url }}), предназначенный для поиска новых уязвимых драйверов (BYOVD) в необработанных бинарных наборах данных, путем фильтрации известных хешей с использованием проекта [LOLDrivers](https://www.loldrivers.io/).

### 1. Установка

DeepZero требует **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

### 2. Настройка среды

Если вы интегрируете этапы ИИ-анализа, настройте API-ключи, создав файл `.env`:

```bash
cp .env.example .env
```

### 3. Выполнение конвейера

Запустите встроенный конвейер LOLDrivers на целевом пути:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

<div class="callout">
    <p><strong>Примечание:</strong> DeepZero безопасно <a href="{{ '/ru/overview/architecture.html' | relative_url }}">распараллеливает выполнение</a> и кэширует промежуточные результаты. Для корректной остановки отправьте SIGINT (<code>Ctrl+C</code>). Последующие запуски с идентичными параметрами мгновенно возобновятся из <a href="{{ '/ru/system/state-persistence.html' | relative_url }}">сохраненного состояния на диске</a>.</p>
</div>
