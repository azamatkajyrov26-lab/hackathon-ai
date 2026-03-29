# Scoring Engine — Алгоритм скоринга

## Общая формула

```
ИТОГОВЫЙ_БАЛЛ = Σ (factor_value × weight) для всех soft factors
```

Диапазон: **0 — 100 баллов**

Скоринг запускается только ПОСЛЕ прохождения всех Hard Filters.

---

## Этап 1: Hard Filters (10 бинарных проверок)

Каждый фильтр = PASS или FAIL. Если хотя бы один FAIL → автоматический отказ.

| # | Фильтр | Источник данных | Проверка |
|---|--------|-----------------|----------|
| 1 | Регистрация в ГИСС | ГИСС API | registered == true |
| 2 | Наличие ЭЦП | Данные заявки | eds_signed == true |
| 3 | Учётный номер в ИАС "РСЖ" | ИАС РСЖ API | registered == true (исключение: СПК) |
| 4 | Земельный участок с/х назначения | ЕГКН API | has_agricultural_land == true |
| 5 | Регистрация в ИС ИСЖ | ИС ИСЖ API | animals verified > 0 |
| 6 | Регистрация в ИБСПР | ИАС РСЖ API | ibspr_registered == true |
| 7 | Подтверждение затрат через ЭСФ | ИС ЭСФ API | invoice_count > 0, payment_confirmed == true |
| 8 | Нет невыполненных обязательств | ГИСС API | obligations_met == true OR obligations_required == false |
| 9 | Нет блокировки | ГИСС API | blocked == false |
| 10 | Возраст животных в допустимом диапазоне | ИС ИСЖ API | age_valid == true для всех животных |
| 11 | Животные не субсидировались ранее | ИС ИСЖ API | previously_subsidized == false для всех |

При FAIL формируется мотивированный отказ с указанием конкретных причин (по Приложению 7).

---

## Этап 2: Soft Factors (8 факторов)

Каждый фактор рассчитывается на шкале 0 — max_value. Итоговый балл = сумма всех weighted_value.

### Factor 1: История субсидий (max 20 баллов, weight 0.20)

**Источник:** ИАС РСЖ API → subsidy_history

**Формула:**
```python
total_subsidies = len(subsidy_history)
successful = count where status == "executed" and obligations_met == true
success_rate = successful / total_subsidies if total_subsidies > 0 else 0

if total_subsidies == 0:
    score = 10  # нейтральный — первичный заявитель
elif success_rate >= 0.9:
    score = 18 + min(total_subsidies, 2)  # 18-20 баллов
elif success_rate >= 0.7:
    score = 14 + (success_rate - 0.7) * 20  # 14-18
elif success_rate >= 0.5:
    score = 8 + (success_rate - 0.5) * 30   # 8-14
else:
    score = success_rate * 16                 # 0-8
```

**Объяснение (пример):** "5 субсидий за 3 года, все обязательства выполнены (100%), 0 возвратов — высокая надежность"

---

### Factor 2: Рост валовой продукции (max 20 баллов, weight 0.20)

**Источник:** ГИСС API → gross_production_previous_year, gross_production_year_before

**Формула:**
```python
growth_rate = giss_data["growth_rate"]  # в процентах

if growth_rate >= 10:
    score = 20
elif growth_rate >= 5:
    score = 14 + (growth_rate - 5) * 1.2   # 14-20
elif growth_rate >= 0:
    score = 8 + growth_rate * 1.2            # 8-14
elif growth_rate >= -5:
    score = 4 + (growth_rate + 5) * 0.8      # 4-8
else:
    score = max(0, 4 + growth_rate * 0.4)     # 0-4
```

**Объяснение:** "Валовая продукция: 45M тг (2024) vs 42M тг (2023), рост +7.14% — положительная динамика"

---

### Factor 3: Размер хозяйства (max 15 баллов, weight 0.15)

**Источник:** ЕГКН API → total_agricultural_area, ИС ИСЖ API → total_verified (поголовье)

**Формула:**
```python
land_area = egkn_data["total_agricultural_area"]  # га
herd_size = is_iszh_data["total_verified"]  # голов

# Земля: 0-8 баллов
if land_area >= 500:
    land_score = 8
elif land_area >= 100:
    land_score = 4 + (land_area - 100) / 100  # 4-8
elif land_area >= 10:
    land_score = land_area / 25               # 0.4-4
else:
    land_score = 0

# Поголовье: 0-7 баллов
if herd_size >= 200:
    herd_score = 7
elif herd_size >= 50:
    herd_score = 3.5 + (herd_size - 50) / 42.8  # 3.5-7
elif herd_size >= 10:
    herd_score = herd_size / 14.3                 # 0.7-3.5
else:
    herd_score = 0

score = land_score + herd_score
```

**Объяснение:** "230.5 га с/х земли (собственность + аренда), 150 голов КРС — крупное хозяйство"

---

### Factor 4: Эффективность — сохранность поголовья (max 15 баллов, weight 0.15)

**Источник:** ИАС РСЖ API → subsidy_history (obligations_met), ГИСС API

**Формула:**
```python
# Процент сохранности просубсидированного поголовья
total_heads_subsidized = sum(h["heads"] for h in subsidy_history)
returns = ias_rszh_data["pending_returns"]

if total_heads_subsidized == 0:
    score = 10  # нейтральный — нет истории
else:
    retention_rate = 1 - (returns / total_heads_subsidized)
    if retention_rate >= 0.98:
        score = 15
    elif retention_rate >= 0.90:
        score = 11 + (retention_rate - 0.90) * 50  # 11-15
    elif retention_rate >= 0.80:
        score = 7 + (retention_rate - 0.80) * 40   # 7-11
    else:
        score = retention_rate * 8.75                # 0-7
```

**Объяснение:** "Сохранность 98% — за 3 года 0 возвратов из 40 просубсидированных голов"

---

### Factor 5: Соответствие нормативу (max 10 баллов, weight 0.10)

**Источник:** ИС ЭСФ API → total_amount, Application → total_amount, SubsidyType → rate

**Формула:**
```python
esf_total = is_esf_data["total_amount"]
requested = application.total_amount
expected = application.quantity * application.rate

# Проверка: запрашиваемая сумма соответствует нормативу
rate_match = (requested == expected)

# Проверка: ЭСФ покрывает фактическую стоимость
esf_covers = (esf_total >= application.quantity * application.unit_price)

if rate_match and esf_covers:
    score = 10
elif rate_match and not esf_covers:
    score = 6  # норматив ОК, но ЭСФ не полностью
elif not rate_match and esf_covers:
    score = 4  # ЭСФ ОК, но сумма не по нормативу
else:
    score = 2
```

**Объяснение:** "Запрошено 5,200,000 тг (20 голов × 260,000) — точно по нормативу. ЭСФ на 7,800,000 тг покрывает стоимость"

---

### Factor 6: Региональный приоритет (max 10 баллов, weight 0.10)

**Источник:** справочник регионов + направление субсидирования

**Формула:**
```python
# Приоритет региона по данному направлению (из справочника)
# Учитывает: импортозависимость, специализацию, % освоения бюджета
region_priority = get_region_priority(region, direction)  # 0.0-1.0

score = region_priority * 10
```

**Объяснение:** "Акмолинская область — приоритетный регион для мясного скотоводства (8/10)"

---

### Factor 7: Тип заявителя (max 5 баллов, weight 0.05)

**Источник:** Applicant → entity_type, ЕАСУ API → is_spk

**Формула:**
```python
if entity_type == "cooperative":  # СПК
    score = 5   # максимальный приоритет — кооперация
elif entity_type == "legal":
    score = 4   # юрлицо — стабильное
elif entity_type == "individual":
    score = 3   # физлицо — ниже стабильность
```

**Объяснение:** "Юридическое лицо (ТОО) — стабильная организационная форма"

---

### Factor 8: Первичность заявителя (max 5 баллов, weight 0.05)

**Источник:** ИАС РСЖ API → subsidy_history

**Формула:**
```python
total_subsidies = len(subsidy_history)
has_same_direction = any(h["type"] matches current direction for h in subsidy_history)

if total_subsidies == 0:
    score = 4   # первичный — приоритет поддержки новых
elif not has_same_direction:
    score = 5   # диверсификация — новое направление
elif total_subsidies <= 3:
    score = 3   # умеренный повторный
else:
    score = 2   # частый заявитель
```

**Объяснение:** "Повторный заявитель (5 субсидий), но надежный — все обязательства выполнены"

---

## Сводная таблица весов

| # | Фактор | Max | Вес | Weighted Max |
|---|--------|-----|-----|-------------|
| 1 | История субсидий | 20 | 0.20 | 20 |
| 2 | Рост валовой продукции | 20 | 0.20 | 20 |
| 3 | Размер хозяйства | 15 | 0.15 | 15 |
| 4 | Эффективность (сохранность) | 15 | 0.15 | 15 |
| 5 | Соответствие нормативу | 10 | 0.10 | 10 |
| 6 | Региональный приоритет | 10 | 0.10 | 10 |
| 7 | Тип заявителя | 5 | 0.05 | 5 |
| 8 | Первичность заявителя | 5 | 0.05 | 5 |
| **ИТОГО** | | **100** | **1.00** | **100** |

---

## Рекомендация AI

На основе итогового балла:

| Диапазон | Рекомендация | Описание |
|----------|-------------|----------|
| 70-100 | `approve` | Рекомендовано к одобрению |
| 40-69 | `review` | Требует внимания комиссии |
| 0-39 | `reject` | Высокий риск, рекомендован отказ |

---

## Explainability Report

Для каждой заявки генерируется JSON-отчет:

```json
{
  "total_score": 94.0,
  "recommendation": "approve",
  "recommendation_reason": "Высокий балл по всем факторам. Заявитель с безупречной историей, стабильный рост продукции, крупное хозяйство с высокой сохранностью поголовья.",
  "factors": [
    {
      "factor_code": "subsidy_history",
      "factor_name": "История субсидий",
      "value": 18.0,
      "max_value": 20.0,
      "weight": 0.20,
      "weighted_value": 18.0,
      "explanation": "5 успешных заявок за 3 года, все обязательства выполнены (100%), 0 возвратов",
      "data_source": "ias_rszh",
      "impact": "positive"
    }
  ],
  "hard_filters": {
    "all_passed": true,
    "results": [
      {"name": "Регистрация в ГИСС", "passed": true},
      {"name": "Учётный номер ИАС РСЖ", "passed": true}
    ]
  },
  "comparison": {
    "avg_score_region": 68.5,
    "avg_score_direction": 71.2,
    "percentile": 95
  }
}
```

---

## Настраиваемые параметры (admin)

Администратор может изменить:
- Веса факторов (weight) — через админ-панель
- Пороги рекомендаций (70/40)
- Региональные приоритеты
- Формулы расчета факторов (через конфиг)
