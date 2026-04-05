# Задача: Генерация 36,651 заявок из Excel

## Цель

Создать management command `generate_from_excel.py`, который читает реальную выгрузку из ИСС (subsidy.plem.kz) и генерирует полный набор данных в БД SubsidyAI: заявители, заявки, скоринг, решения, платежи.

## Входные данные

**Файл:** `docs/Выгрузка по выданным субсидиям 2025 год (обезлич).xlsx`

| Колонка | Индекс | Пример |
|---------|--------|--------|
| № п/п | 0 | 58358 |
| Дата поступления | 1 | 21.01.2025 11:15:40 |
| Область | 4 | область Абай |
| Акимат | 5 | ГУ "Управление сельского хозяйства области Абай" |
| Номер заявки | 6 | 01300100258072 |
| Направление | 7 | Субсидирование в скотоводстве |
| Наименование субсидирования | 8 | Заявка на получение субсидий на ведение селекционной... |
| Статус заявки | 9 | Исполнена |
| Норматив | 10 | 15000 |
| Причитающая сумма | 11 | 4635000 |
| Район хозяйства | 12 | Жарминский район |

**Строки данных:** начиная со строки 6 (строка 5 = заголовки). Всего 36,651 записей.

## Запуск

```bash
python3 manage.py generate_from_excel --file docs/Выгрузка\ по\ выданным\ субсидиям\ 2025\ год\ \(обезлич\).xlsx --clear
```

Флаг `--clear` — удаляет все старые данные перед генерацией (EmulatedEntity, Applicant, Application и т.д.). Оставляет только: SubsidyDirection, SubsidyType, демо-аккаунты (bereke, specialist, commission, head, admin).

---

## Шаги выполнения

### Шаг 0: Подготовка — SubsidyDirection и SubsidyType

Перед генерацией нужны справочники. Создать/обновить если нет:

**SubsidyDirection (9 направлений из Excel):**

| code | name (из Excel) |
|------|----------------|
| cattle_meat | Субсидирование в скотоводстве |
| poultry | Субсидирование в птицеводстве |
| sheep | Субсидирование в овцеводстве |
| camel | Субсидирование в верблюдоводстве |
| horse | Субсидирование в коневодстве |
| insemination | Субсидирование затрат по искусственному осеменению |
| beekeeping | Субсидирование в пчеловодстве |
| pig | Субсидирование в свиноводстве |
| goat | Субсидирование в козоводстве |

**SubsidyType:** Создавать динамически из уникальных комбинаций (направление + наименование + норматив) в Excel. Примерно ~40-50 уникальных видов.

### Шаг 1: Парсинг Excel

1. Открыть xlsx через openpyxl (read_only=True для экономии памяти)
2. Читать все строки начиная с 6-й
3. Фильтровать пустые строки (где колонка 0 = None)
4. Для каждой строки создать словарь:
   ```python
   {
       'row_num': int(row[0]),
       'date_str': str(row[1]),          # "21.01.2025 11:15:40"
       'region': str(row[4]).strip(),     # "область Абай"
       'akimat': str(row[5]).strip(),
       'app_number': str(row[6]).strip(), # "01300100258072"
       'direction_name': str(row[7]).strip(),
       'subsidy_name': str(row[8]).strip(),
       'status': str(row[9]).strip(),     # "Исполнена"
       'rate': float(row[10]) if row[10] else 0,
       'amount': float(row[11]) if row[11] else 0,
       'district': str(row[12]).strip(),
   }
   ```
5. Парсить дату: `datetime.strptime(date_str, '%d.%m.%Y %H:%M:%S')`

**Результат:** список из ~36,651 словарей.

### Шаг 2: Группировка заявителей

Один фермер может подать несколько заявок. Группируем по: **район + первые 10 цифр номера заявки** (гипотеза: первые цифры — код субсидии, последние — порядковый номер, привязка к заявителю через район).

Альтернативный подход (проще и надёжнее): **каждая заявка = отдельный заявитель**. Это даёт 36,651 фермеров. Для демо это приемлемо — больше данных для скоринга и аналитики.

**Решение:** 1 заявка = 1 заявитель (36,651 фермеров).

Для каждого заявителя генерируем:
- ИИН/БИН (синтетический, уникальный)
- Название хозяйства (генератор)
- Тип (individual/legal/cooperative) — по сумме заявки

### Шаг 3: Маппинг статусов и risk_profile

| Статус Excel | status в Application | risk_profile | Скоринг? |
|-------------|---------------------|-------------|----------|
| Исполнена | paid | clean | Да |
| Одобрена | approved | clean/minor_issues (90/10) | Да |
| Сформировано поручение | approved | clean | Да |
| Отклонена | rejected | risky/fraudulent (60/40) | Да |
| Отозвано | draft | minor_issues | Нет |
| Получена | submitted | random (clean 70%, minor 20%, risky 10%) | Да |

### Шаг 4: Генерация EmulatedEntity (7 JSON)

Для каждого заявителя генерируем JSON данные из 7 систем. Данные **калибруются по Excel**:

#### 4.1 ГИСС (giss_data)

```python
quantity = amount / rate  # кол-во голов из Excel
prev_year_prod = amount * random.uniform(5, 15)  # валовая продукция

if risk == 'clean':
    growth_rate = random.uniform(3, 18)
    obligations_met = True
elif risk == 'minor_issues':
    growth_rate = random.uniform(-3, 8)
    obligations_met = random.random() > 0.3
elif risk == 'risky':
    growth_rate = random.uniform(-15, 0)
    obligations_met = False
else:  # fraudulent
    growth_rate = random.uniform(-25, -5)
    obligations_met = False
```

#### 4.2 ИАС РСЖ (ias_rszh_data)

- `subsidy_history`: 1-4 записи для clean, 0-2 для risky
- Суммы пропорциональны `amount` из Excel
- `pending_returns`: 0 для clean, 1-5 для risky

#### 4.3 ЕАСУ (easu_data)

- `has_account_number`: True (всегда, кроме fraudulent с шансом 30%)
- `is_spk`: True если entity_type == 'cooperative'

#### 4.4 ИС ИСЖ (is_iszh_data)

- Количество животных = `min(quantity, 200)` (ограничение для размера JSON)
- Тип животных — по direction_code:
  - cattle_meat/cattle_dairy → cattle
  - sheep/goat → sheep
  - horse → horse
  - camel → camel
  - pig → pig
  - poultry → poultry
- `age_valid`: True для clean, случайно для fraudulent
- `previously_subsidized`: False для clean, случайно для fraudulent
- `mortality_data`: 0-1.5% для clean, 1-5% для risky

#### 4.5 ИС ЭСФ (is_esf_data)

- `total_amount`: amount × random(1.2, 2.5) — ЭСФ покрывает стоимость
- `payment_confirmed`: True для clean/minor_issues

#### 4.6 ЕГКН (egkn_data)

- `total_agricultural_area`: quantity × random(3, 10) га
- `pasture_area`: total × random(0.4, 0.8) га
- `pasture_zone`: 'restored' (обычно), 'degraded' для risky

#### 4.7 Казначейство (treasury_data)

- Есть payments если статус = Исполнена или Сформировано поручение
- `status`: 'completed' для Исполнена, 'pending' для остальных

### Шаг 5: Bulk-создание записей в БД

Порядок создания (важно для FK):

```
1. SubsidyDirection (get_or_create, 9 шт)
2. SubsidyType (get_or_create, ~40-50 шт)
3. EmulatedEntity (bulk_create, batch=1000) — 36,651 шт
4. Applicant (bulk_create, batch=1000) — 36,651 шт
5. UserProfile (bulk_create, batch=1000) — НЕ создаём User для каждого!
   Только для демо-аккаунтов (bereke, specialist и т.д.)
6. Application (bulk_create, batch=1000) — 36,651 шт
7. Budget (get_or_create, 17 регионов × 9 направлений) — для проверки бюджета
```

**Важно:** `bulk_create` не вызывает signals и не генерирует auto-поля. Поэтому:
- `number` — берём из Excel (app_number)
- `submitted_at` — парсим из Excel (date_str)
- `created_at` — auto_now_add сработает
- `total_amount` — из Excel (amount)
- `rate` — из Excel (rate)
- `quantity` — вычисляем: amount / rate

### Шаг 6: Скоринг (ScoringEngine)

Для каждой заявки (кроме статуса "Отозвано"):

```python
engine = ScoringEngine()
for app in Application.objects.exclude(status='draft').iterator():
    engine.run_scoring(app)
```

ScoringEngine автоматически:
1. Проверяет 18 hard filters
2. Считает 8 soft factors
3. Запускает ML-модель (GradientBoosting)
4. Считает SHAP-объяснение
5. Сохраняет Score, ScoreFactor, HardFilterResult
6. Отправляет Notification

**Оптимизация скоринга:**
- Отключить отправку уведомлений (или создавать в конце batch-ом)
- Использовать `iterator()` чтобы не загружать все 36K в память
- Прогресс: print каждые 500 заявок
- `transaction.atomic()` по batch-ам (по 100)

**Время:** ~20-30 мин (ML ~5мс + SHAP ~100мс = ~105мс × 34,587 = ~60 мин макс). Можно ускорить: SHAP только для 5K выборки, остальным — только ML.

**Оптимизация SHAP:** Флаг `--skip-shap` для быстрой генерации (~5 мин вместо 30).

### Шаг 7: Post-scoring — Decision и Payment

После скоринга обновляем статусы и создаём записи:

```python
for app in Application.objects.all():
    excel_status = app.notes  # Сохраняем реальный статус Excel в notes

    if excel_status == 'Исполнена':
        app.status = 'paid'
        # Создать Decision (approved)
        # Создать Payment (completed, merit_score)
    elif excel_status == 'Одобрена':
        app.status = 'approved'
        # Создать Decision (approved)
        # Создать Payment (initiated, merit_score)
    elif excel_status == 'Сформировано поручение':
        app.status = 'approved'
        # Создать Decision (approved)
        # Создать Payment (sent_to_treasury, merit_score)
    elif excel_status == 'Отклонена':
        app.status = 'rejected'
        # Создать Decision (rejected)
    elif excel_status == 'Отозвано':
        app.status = 'draft'
        # Нет Decision/Payment
    elif excel_status == 'Получена':
        app.status = 'submitted'
        # Нет Decision/Payment (ещё не рассмотрена)
```

Merit Score считается через `calculate_merit_score(app)` из `scoring_engine.py`.

### Шаг 8: Бюджеты

Создать Budget записи по реальным суммам из Excel:

```python
for (region, direction), group in grouped_by_region_direction:
    total_amount = sum(row['amount'] for row in group)
    Budget.objects.update_or_create(
        year=2025,
        region=region,
        direction=direction,
        defaults={
            'planned_amount': total_amount * 1.2,  # план = 120% от факта
            'spent_amount': sum(amount for rows with status='Исполнена'),
        }
    )
```

### Шаг 9: Финальная проверка

После генерации выводим статистику:

```
=== РЕЗУЛЬТАТ ГЕНЕРАЦИИ ===
EmulatedEntity:   36,651
Applicant:        36,651
Application:      36,651
HardFilterResult: 34,587 (без отозванных)
Score:            34,587
ScoreFactor:      276,696 (34,587 × 8)
Decision:         34,390
Payment:          31,481
Budget:           153 (17 регионов × 9 направлений)
Notification:     ~100K

Средний AI-скор:  XX.X
Одобрено AI:      XX,XXX (XX%)
На усмотрение:    X,XXX (XX%)
Отклонено AI:     X,XXX (XX%)
```

---

## Структура файла

```
apps/emulator/management/commands/generate_from_excel.py
```

Наследует от `BaseCommand`. Аргументы:
- `--file` (обязательный) — путь к Excel
- `--clear` — удалить старые данные
- `--skip-shap` — пропустить SHAP (ускоряет в 5-6x)
- `--batch-size` (по умолчанию 1000) — размер batch для bulk_create
- `--scoring-batch` (по умолчанию 100) — batch для atomic scoring

## Зависимости

- openpyxl (уже установлен)
- Faker (уже установлен) — для генерации имён
- Все модели из apps/scoring/models.py и apps/emulator/models.py
- ScoringEngine из apps/scoring/scoring_engine.py
- calculate_merit_score из apps/scoring/scoring_engine.py

## Оценка времени

| Этап | Записей | Время |
|------|---------|-------|
| Парсинг Excel | 36,651 | ~5 сек |
| SubsidyDirection + SubsidyType | ~50 | ~1 сек |
| EmulatedEntity (bulk) | 36,651 | ~30 сек |
| Applicant (bulk) | 36,651 | ~10 сек |
| Application (bulk) | 36,651 | ~10 сек |
| Budget | ~153 | ~1 сек |
| Скоринг (ML, без SHAP) | ~34,587 | ~5 мин |
| Скоринг (ML + SHAP) | ~34,587 | ~20-30 мин |
| Decision + Payment (bulk) | ~34,390 | ~2 мин |
| **Итого (без SHAP)** | | **~8-10 мин** |
| **Итого (с SHAP)** | | **~25-35 мин** |

## Важные замечания

1. **RFID не генерируем** — экономия ~450K записей и ~2 мин
2. **Старые данные удаляются** при `--clear` (EmulatedEntity, RFIDMonitoring, Applicant, Application, Score, ScoreFactor, HardFilterResult, Decision, Payment, Notification, AuditLog, Budget). Сохраняются: User, UserProfile, SubsidyDirection, SubsidyType
3. **1 заявка = 1 заявитель** — простейший подход, даёт 36,651 фермеров
4. **Статус Excel сохраняется в Application.notes** — чтобы после скоринга восстановить реальный статус
5. **ML модель должна быть обучена** до запуска (файл ml_model существует)
6. **Django User НЕ создаётся** для каждого заявителя — только Applicant + EmulatedEntity. UserProfile создаётся без User (или пропускается)
