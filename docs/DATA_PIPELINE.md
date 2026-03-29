# Data Pipeline — Загрузка и генерация данных

## Источник: Excel-выгрузка

**Файл:** `Выгрузка по выданным субсидиям 2025 год (обезлич).xlsx`
**Записей:** 36,658
**Колонки:** № п/п, Дата поступления, Область, Акимат, Номер заявки, Направление, Наименование субсидирования, Статус заявки, Норматив, Причитающая сумма, Район хозяйства

## Pipeline (3 этапа)

### Этап 1: Загрузка Excel → БД

**Management command:** `python manage.py load_excel`

1. Читаем Excel через pandas + openpyxl
2. Парсим каждую строку:
   - `Область` → region
   - `Район хозяйства` → district
   - `Акимат` → akimat
   - `Направление водства` → direction (маппинг на SubsidyDirection)
   - `Наименование субсидирования` → subsidy_type (маппинг на SubsidyType)
   - `Норматив` → rate
   - `Причитающая сумма` → total_amount
   - `quantity` = total_amount / rate (расчет количества)
   - `Статус заявки` → status маппинг
   - `Дата поступления` → submitted_at
   - `Номер заявки` → number
3. Группируем по (Область, Район, Направление) → это одно "хозяйство"
4. Создаем уникальные EmulatedEntity для каждой группы

**Маппинг статусов:**
| Excel | Модель |
|-------|--------|
| Исполнена | paid |
| На рассмотрении | submitted |
| Отказано | rejected |
| В листе ожидания | waiting_list |
| Частично выплачена | partially_paid |

**Маппинг направлений:**
| Excel | code |
|-------|------|
| Субсидирование в скотоводстве | cattle_breeding |
| Субсидирование молочного скотоводства | dairy |
| Субсидирование в овцеводстве | sheep_breeding |
| Субсидирование в птицеводстве | poultry |
| Субсидирование в коневодстве | horse_breeding |
| Субсидирование в свиноводстве | pig_breeding |

---

### Этап 2: Генерация синтетических данных

**Management command:** `python manage.py generate_data`

Для каждой EmulatedEntity генерируем данные, которых нет в Excel:

#### 2.1 Генерация ИИН/БИН
```python
# БИН (юрлицо): YYMMxxxxxxxx — 12 цифр
# ИИН (физлицо): YYMMDDxxxxxxxx — 12 цифр
# 60% юрлица, 30% физлица, 10% СПК
```

#### 2.2 Генерация ГИСС данных (giss_data)
```python
{
    "registered": True,
    "gross_production_previous_year": random(5_000_000, 200_000_000),
    "gross_production_year_before": calculate_from_growth(),
    "growth_rate": random(-10, 25),  # реалистичный разброс
    "obligations_met": True/False,  # зависит от risk_profile
    "total_subsidies_received": sum(history),
    "obligations_required": total >= 100_000_000,
    "blocked": False/True,  # только для risky/fraudulent
    "block_reason": null or "Невыполнение встречных обязательств 2 года подряд"
}
```

#### 2.3 Генерация ИАС РСЖ данных (ias_rszh_data)
```python
{
    "registered": True,
    "registration_date": random_date(2015, 2024),
    "entity_type": "legal" / "individual" / "cooperative",
    "name": generated_name,
    "region": from_excel,
    "district": from_excel,
    "subsidy_history": [
        {
            "year": 2024,
            "type": from_excel_direction,
            "amount": from_excel_amount,
            "heads": calculated,
            "status": "executed" / "pending",
            "obligations_met": True/False
        }
    ],
    "total_subsidies_history": sum,
    "pending_returns": 0 or random_small
}
```

#### 2.4 Генерация ЕАСУ данных (easu_data)
```python
{
    "has_account_number": True,
    "account_numbers": ["KZ-AGR-{random:6}"],
    "is_spk": entity_type == "cooperative",
    "spk_members": [] or [list of member iin_bins],
    "spk_name": null or "СПК '{name}'"
}
```

#### 2.5 Генерация ИС ИСЖ данных (is_iszh_data)
```python
# Генерация животных на основе направления и суммы из Excel
{
    "verified": True,
    "animals": [
        {
            "tag_number": "KZ{random:8}",
            "type": "cattle" / "sheep" / "horse",
            "breed": random_from_breed_list,
            "category": "heifer" / "bull" / "ewe",
            "sex": "female" / "male",
            "birth_date": random_within_age_range,
            "age_months": calculated,
            "age_valid": True/False,
            "owner_iin_bin": entity.iin_bin,
            "owner_match": True,
            "previously_subsidized": False/True,  # risk_profile
            "vet_status": "healthy" / "quarantine",
            "last_vet_check": recent_date,
            "registration_date": random_date
        }
    ],
    "total_verified": count,
    "total_rejected": 0 or small,
    "rejection_reasons": []
}
```

**Породы по направлениям:**
- КРС мясное: Ангусская, Герефордская, Казахская белоголовая, Шароле, Лимузинская
- КРС молочное: Голштинская, Симментальская, Черно-пестрая, Айрширская
- Овцы: Эдильбаевская, Казахская тонкорунная, Каракульская, Меринос
- Лошади: Казахская, Кустанайская, Мугалжарская
- Свиньи: Крупная белая, Ландрас, Дюрок

#### 2.6 Генерация ИС ЭСФ данных (is_esf_data)
```python
{
    "invoices": [
        {
            "esf_number": "ESF-2025-{random:7}",
            "date": random_date_2025,
            "seller_bin": random_bin,
            "seller_name": "ТОО '{random_farm}'",
            "buyer_iin_bin": entity.iin_bin,
            "total_amount": from_excel * markup,  # фактическая стоимость > субсидии
            "items": [
                {
                    "description": based_on_direction,
                    "quantity": from_excel_calculated,
                    "unit": "голова" / "кг",
                    "unit_price": calculated,
                    "amount": total
                }
            ],
            "status": "confirmed",
            "payment_confirmed": True/False  # risk_profile
        }
    ],
    "total_amount": sum,
    "invoice_count": count
}
```

#### 2.7 Генерация ЕГКН данных (egkn_data)
```python
{
    "has_agricultural_land": True/False,  # False для fraudulent
    "plots": [
        {
            "cadastral_number": "XX-XXX-XXX-XXX",
            "area_hectares": random(5, 2000),
            "purpose": "сельскохозяйственное назначение",
            "sub_purpose": "пастбище" / "пашня" / "сенокос",
            "region": from_excel,
            "district": from_excel,
            "ownership_type": "собственность" / "аренда",
            "registration_date": random_date
        }
    ],
    "total_agricultural_area": sum
}
```

#### 2.8 Генерация Treasury данных (treasury_data)
```python
{
    "payments": [
        {
            "payment_id": "PAY-2025-{random:5}",
            "amount": from_history,
            "status": "completed",
            "paid_date": random_date,
            "treasury_reference": "TR-2025-{random:5}"
        }
    ]
}
```

---

### Этап 3: Risk Profile распределение

| Profile | % | Описание | Что генерируем |
|---------|---|----------|---------------|
| clean | 70% | Идеальный заявитель | Все данные корректны, обязательства выполнены |
| minor_issues | 15% | Мелкие проблемы | Просрочка ЭСФ, неполная земля, 1 возврат |
| risky | 10% | Серьезные проблемы | Невыполненные обязательства, падение продукции, маленькое хозяйство |
| fraudulent | 5% | Подозрительный | Повторное субсидирование, несоответствие данных, нет земли, блокировка |

Это обеспечивает реалистичное распределение баллов для демо:
- ~70% заявок: 60-100 баллов (нормальные)
- ~15%: 40-60 баллов (с проблемами)
- ~10%: 20-40 баллов (рисковые)
- ~5%: 0-20 баллов (подозрительные)

---

## Запуск pipeline

```bash
# 1. Загрузка Excel
docker-compose exec web python manage.py load_excel

# 2. Генерация синтетических данных
docker-compose exec web python manage.py generate_data

# 3. Создание тестовых заявок с автоскорингом
docker-compose exec web python manage.py create_test_applications --count 500
```
