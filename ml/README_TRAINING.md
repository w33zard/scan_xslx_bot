# План обучения / дообучения для извлечения полей паспорта РФ

## Цель

Улучшить качество извлечения полей из паспортов РФ путём дообучения моделей на размеченных данных.

## Правильный подход: разделение на 2 задачи

**Не учим «всё сразу».** Делим на:

1. **OCR / Text Recognition** — распознавание текста в ROI (regions of interest)
2. **Field Extraction (NER)** — структурирование: какой текст к какому полю относится

Итоговый ensemble: `OCR → NER → правила/валидация`

---

## 1. OCR (распознавание текста)

### Данные

- Собрать датасет **кропов полей** паспорта (image_crop, ground_truth_text)
- Только легально: с согласия владельцев, анонимизация где нужно
- Разметка: пары `(image_crop, text)`

### Аугментации

- blur, noise, jpeg artifacts
- shadow, glare, rotation (-15°…+15°), perspective
- Изменение яркости/контраста

### Модели

- **PaddleOCR** / **TrOCR** / **DocTR** — fine-tune на кропах полей паспорта РФ
- Сохранять веса отдельно для полей (ФИО, серия, даты и т.д.) или один универсальный

### Метрики

- CER (Character Error Rate)
- WER (Word Error Rate)
- Char Accuracy = 1 - CER

### Экспорт

- Сохранение модели в `models/ocr_*`
- checksum для версионирования
- Инференс: `ml/infer.py`

---

## 2. Field Extraction (NER)

### Данные

- Сырой OCR-текст + разметка сущностей: SURNAME, NAME, PATRONYMIC, BIRTH_DATE, SERIES, NUMBER, ...
- Формат: BIO или spaCy JSON

### Модели

- **ruBERT** (DeepPavlov, sberbank-ai) — fine-tune для NER
- Или **spaCy** transformer NER

### Метрики

- F1 по сущностям (micro/macro)
- Field-level accuracy: exact match по каждому полю
- Partial match для адреса (overlap)

---

## 3. Минимальный baseline без обучения

Текущая реализация: **правила + OCR** как работающая первая версия.

- Метки («Фамилия», «Имя», …) → значение рядом
- Регексы для серии/номера, дат, кода подразделения
- Обучение — опциональный upgrade для повышения качества

---

## 4. Структура репозитория

```
ml/
  README_TRAINING.md    # этот документ
  augmentations.py     # аугментации для OCR
  dataset_tools.py     # загрузка, разметка, split
  train_ocr.py         # скрипт обучения OCR
  train_ner.py         # скрипт обучения NER
  infer.py             # инференс обученных моделей
models/                # сохранённые модели
  ocr_ru_passport/
  ner_ru_passport/
```

---

## 5. Версионирование

- `models/` + checksum (SHA256) в `models/manifest.json`
- `pipeline_version` в debug-выводе результата

---

## 6. Рекомендуемый порядок

1. Собрать 100–500 размеченных кропов полей
2. Fine-tune OCR на кропах
3. Оценить CER/WER
4. Собрать разметку NER (текст + сущности)
5. Fine-tune NER
6. Интегрировать в pipeline как опциональный путь
