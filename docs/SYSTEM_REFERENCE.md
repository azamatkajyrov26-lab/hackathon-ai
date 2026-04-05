# SubsidyAI — Справочник системы

Подробный справочник всех сущностей, интеграций, параметров скоринга и ролей системы SubsidyAI.

---

## 1. Сущности базы данных

### 1.1 UserProfile — Профиль пользователя

| Поле | Тип | Описание |
|------|-----|----------|
| user | OneToOne → User | Django-пользователь |
| role | CharField(30) | Роль: `applicant`, `mio_specialist`, `commission_member`, `mio_head`, `admin`, `auditor` |
| iin_bin | CharField(12) | ИИН/БИН (связь с заявителем) |
| region | CharField(200) | Область |
| district | CharField(200) | Район |
| organization | CharField(500) | Организация |
| phone | CharField(20) | Телефон |

### 1.2 Applicant — Заявитель

| Поле | Тип | Описание |
|------|-----|----------|
| iin_bin | CharField(12) | ИИН/БИН (уникальный, индекс) |
| name | CharField(500) | Наименование хозяйства |
| entity_type | CharField(20) | Тип: `individual` (ФЛ), `legal` (ЮЛ), `cooperative` (СПК) |
| region | CharField(200) | Область |
| district | CharField(200) | Район |
| address | TextField | Адрес |
| phone | CharField(20) | Телефон |
| email | EmailField | Email |
| bank_account | CharField(34) | IBAN |
| bank_name | CharField(200) | Банк |
| registration_date | DateField | Дата регистрации |
| is_blocked | BooleanField | Заблокирован (Приказ №108) |
| block_reason | TextField | Причина блокировки |
| block_until | DateField | Дата окончания блокировки |

### 1.3 SubsidyDirection — Направление субсидирования

| Поле | Тип | Описание |
|------|-----|----------|
| code | CharField(30) | Код: `cattle_meat`, `cattle_dairy`, `sheep`, `horse`, `pig`, `poultry`, `camel`, `beekeeping`, `aquaculture`, `feed_production` |
| name | CharField(500) | Название |
| description | TextField | Описание |
| is_active | BooleanField | Активно |

### 1.4 SubsidyType — Вид субсидии

| Поле | Тип | Описание |
|------|-----|----------|
| direction | FK → SubsidyDirection | Направление |
| form_number | IntegerField | Номер формы (1-8 = племенные) |
| name | CharField(500) | Название вида |
| unit | CharField(50) | Единица измерения (голова, кг, литр) |
| rate | Decimal(12,2) | Норматив субсидии (тенге) |
| origin | CharField(20) | Происхождение: `domestic`, `cis`, `import`, `na` |
| min_age_months | IntegerField | Мин. возраст животного (мес.) |
| max_age_months | IntegerField | Макс. возраст животного (мес.) |
| min_herd_size | IntegerField | Мин. поголовье |
| requires_commission | BooleanField | Требует заключения комиссии |

### 1.5 ApplicationPeriod — Сроки приёма заявок

| Поле | Тип | Описание |
|------|-----|----------|
| direction | OneToOne → SubsidyDirection | Направление |
| start_day / start_month | IntegerField | Начало приёма |
| end_day / end_month | IntegerField | Конец приёма |
| is_year_round | BooleanField | Круглогодичный приём |

### 1.6 Application — Заявка

| Поле | Тип | Описание |
|------|-----|----------|
| number | CharField(20) | Номер заявки (уникальный) |
| applicant | FK → Applicant | Заявитель |
| subsidy_type | FK → SubsidyType | Вид субсидии |
| status | CharField(20) | Статус: `draft`, `submitted`, `checking`, `approved`, `rejected`, `waiting_list`, `partially_paid`, `paid` |
| quantity | IntegerField | Количество голов/единиц |
| unit_price | Decimal(12,2) | Цена за единицу (факт. стоимость) |
| rate | Decimal(12,2) | Норматив субсидии |
| total_amount | Decimal(15,2) | Причитающаяся сумма субсидии |
| submitted_at | DateTimeField | Дата подачи |
| region | CharField(200) | Область |
| district | CharField(200) | Район |
| akimat | CharField(500) | Акимат |
| animals_data | JSONField | Выбранные животные (из ИС ИСЖ) |
| plots_data | JSONField | Земельные участки (из ЕГКН) |
| invoices_data | JSONField | ЭСФ (из ИС ЭСФ) |
| esf_number | CharField(50) | Номер ЭСФ |
| esf_amount | Decimal(15,2) | Сумма ЭСФ |
| counterparty_bin | CharField(12) | БИН продавца |
| counterparty_name | CharField(500) | Продавец |
| land_cadastral | CharField(50) | Кадастровый номер |
| bank_account | CharField(50) | Банковский счёт |
| ecp_signed | BooleanField | Подписано ЭЦП |
| ecp_signed_at | DateTimeField | Дата подписи ЭЦП |
| spk_name | CharField(500) | Название СПК |
| notes | TextField | Примечания |

### 1.7 ApplicationDocument — Документ заявки

| Поле | Тип | Описание |
|------|-----|----------|
| application | FK → Application | Заявка |
| doc_type | CharField(30) | Тип: `contract`, `esf`, `customs_declaration`, `quarantine_act`, `commission_conclusion`, `spk_membership`, `payment_confirmation`, `veterinary_certificate`, `pedigree_certificate`, `weighing_act`, `bonitation_act`, `other` |
| name | CharField(500) | Название |
| file | FileField | Файл |
| verified | BooleanField | Проверен |
| verified_by | FK → User | Кем проверен |
| verified_at | DateTimeField | Дата проверки |

### 1.8 HardFilterResult — Результат жёстких проверок

18 бинарных полей (BooleanField) — каждое = один hard-filter:

| # | Поле | Описание | Источник |
|---|------|----------|----------|
| 1 | giss_registered | Регистрация в ГИСС | ГИСС |
| 2 | has_eds | Наличие ЭЦП | ЕАСУ |
| 3 | ias_rszh_registered | Учётный номер в ИАС РСЖ | ИАС РСЖ |
| 4 | has_agricultural_land | Земля с/х назначения | ЕГКН |
| 5 | is_iszh_registered | Верифицированные животные | ИС ИСЖ |
| 6 | ibspr_registered | Регистрация в ИБСПР | ИАС РСЖ |
| 7 | esf_confirmed | Подтверждённые ЭСФ | ИС ЭСФ |
| 8 | no_unfulfilled_obligations | Нет невыполненных обязательств | ГИСС |
| 9 | no_block | Нет блокировки | ГИСС + Applicant |
| 10 | animals_age_valid | Возраст животных в диапазоне | ИС ИСЖ |
| 11 | animals_not_subsidized | Животные не субсидировались | ИС ИСЖ |
| 12 | application_period_valid | Подана в допустимый период | Приказ №108 |
| 13 | subsidy_amount_valid | Сумма ≤ 50% стоимости | Приказ №108 |
| 14 | min_herd_size_met | Минимальное поголовье | Приказ №108 |
| 15 | no_duplicate_application | Нет дубликатов в текущем году | БД |
| 16 | mortality_within_norm | Падёж в пределах нормы | Приказ №3-3/1061 |
| 17 | pasture_load_valid | Нагрузка на пастбища в норме | Приказ №3-3/332 |
| 18 | pedigree_valid | Племенное свидетельство | Приказ №108 |

Дополнительные поля:
- `all_passed` — все 18 пройдены
- `failed_reasons` — JSON список причин отказа
- `raw_responses` — сырые данные из внешних систем

### 1.9 Score — Скоринг заявки

| Поле | Тип | Описание |
|------|-----|----------|
| application | OneToOne → Application | Заявка |
| total_score | Decimal(5,2) | Итоговый балл (0-100) |
| rank | IntegerField | Позиция в рейтинге по региону+направлению |
| recommendation | CharField(10) | `approve` (≥70), `review` (40-69), `reject` (<40) |
| recommendation_reason | TextField | Текстовое обоснование |
| explanation | JSONField | SHAP-объяснение (визуализация факторов) |
| model_version | CharField(20) | Версия: `2.0-ml` |

### 1.10 ScoreFactor — Фактор скоринга

| Поле | Тип | Описание |
|------|-----|----------|
| score | FK → Score | Скоринг |
| factor_code | CharField(30) | Код фактора |
| factor_name | CharField(200) | Название |
| value | Decimal(5,2) | Значение (0 — max_value) |
| max_value | Decimal(5,2) | Максимум |
| weight | Decimal(3,2) | Вес фактора |
| weighted_value | Decimal(5,2) | Взвешенное значение |
| explanation | TextField | Объяснение расчёта |
| data_source | CharField(30) | Источник данных (гос. система) |
| raw_data | JSONField | Исходные данные для расчёта |

### 1.11 Decision — Решение комиссии

| Поле | Тип | Описание |
|------|-----|----------|
| application | FK → Application | Заявка |
| decision | CharField(20) | `approved`, `rejected`, `review`, `partially_approved` |
| decided_by | FK → User | Кто принял |
| reason | TextField | Обоснование |
| rejection_grounds | JSONField | Основания отказа |
| approved_amount | Decimal(15,2) | Одобренная сумма |
| confirmed_by | FK → User | Подтвердивший |
| confirmed_at | DateTimeField | Дата подтверждения |

### 1.12 Budget — Бюджет

| Поле | Тип | Описание |
|------|-----|----------|
| year | IntegerField | Год |
| region | CharField(200) | Область |
| direction | FK → SubsidyDirection | Направление |
| planned_amount | Decimal(15,2) | Плановый бюджет |
| spent_amount | Decimal(15,2) | Факт. расход |
| remaining_amount | @property | planned - spent |

### 1.13 Payment — Платёж

| Поле | Тип | Описание |
|------|-----|----------|
| application | OneToOne → Application | Заявка |
| amount | Decimal(15,2) | Сумма к выплате |
| status | CharField(20) | `initiated`, `sent_to_treasury`, `processing`, `completed`, `failed` |
| treasury_ref | CharField(50) | Номер Казначейства |
| **merit_score** | **Decimal(5,2)** | **Merit Score для приоритизации выплат** |
| **merit_breakdown** | **JSONField** | **Разбивка: farm_scale, financial, history, direction_priority** |
| initiated_by | FK → User | Инициатор |
| initiated_at / sent_at / completed_at | DateTimeField | Даты |

### 1.14 Notification — Уведомление

| Поле | Тип | Описание |
|------|-----|----------|
| user | FK → User | Получатель |
| application | FK → Application | Заявка |
| notification_type | CharField(30) | `submitted`, `info`, `hard_filter_fail`, `scored`, `approved`, `rejected`, `waiting_list`, `payment_initiated`, `paid`, `review` |
| title | CharField(300) | Заголовок |
| message | TextField | Сообщение |
| is_read | BooleanField | Прочитано |

### 1.15 AuditLog — Журнал аудита

| Поле | Тип | Описание |
|------|-----|----------|
| user | FK → User | Пользователь |
| action | CharField(20) | `create`, `update`, `score`, `decide`, `confirm`, `payment`, `block`, `login` |
| entity_type | CharField(100) | Тип сущности |
| entity_id | IntegerField | ID сущности |
| description | TextField | Описание действия |
| ip_address | GenericIPAddressField | IP-адрес |
| metadata | JSONField | Метаданные |

---

## 2. Эмулятор внешних систем

### 2.1 EmulatedEntity — Эмулированная сущность

Хранит данные из 7 государственных систем в JSON-полях:

| Поле | Тип | Описание |
|------|-----|----------|
| iin_bin | CharField(12) | ИИН/БИН |
| name | CharField(500) | Наименование |
| entity_type | CharField(20) | `individual`, `legal`, `cooperative` |
| region | CharField(200) | Область |
| district | CharField(200) | Район |
| risk_profile | CharField(20) | `clean` (70%), `minor_issues` (15%), `risky` (10%), `fraudulent` (5%) |
| giss_data | JSONField | ГИСС |
| ias_rszh_data | JSONField | ИАС РСЖ |
| easu_data | JSONField | ЕАСУ |
| is_iszh_data | JSONField | ИС ИСЖ |
| is_esf_data | JSONField | ИС ЭСФ |
| egkn_data | JSONField | ЕГКН |
| treasury_data | JSONField | Казначейство |

### 2.2 RFIDMonitoring — RFID-мониторинг

| Поле | Тип | Описание |
|------|-----|----------|
| entity | FK → EmulatedEntity | Сущность |
| animal_tag | CharField(50) | Бирка животного |
| rfid_tag | CharField(100) | RFID-метка |
| last_scan_date | DateTimeField | Последнее считывание |
| scan_location | CharField(200) | Место считывания |
| status | CharField(20) | `active`, `inactive`, `missing` |
| scan_count_30d | IntegerField | Считываний за 30 дней |
| animal_type | CharField(50) | Вид животного |
| reader_type | CharField(50) | Тип считывателя |

---

## 3. Интеграции — 7 государственных информационных систем

### 3.1 ГИСС — Государственная информационная система субсидирования

**Источник:** `EmulatedEntity.giss_data`
**Используется в:** Hard Filters (1, 8, 9), Soft Factors (1, 2, 4)

```json
{
  "registered": true,                           // Регистрация в ГИСС
  "gross_production_previous_year": 75000000,   // Валовая продукция за прошлый год (тг)
  "gross_production_year_before": 65000000,     // Валовая продукция за позапрошлый год (тг)
  "growth_rate": 15.38,                         // Рост продукции (%)
  "obligations_met": true,                      // Встречные обязательства выполнены
  "obligations_required": false,                // Требуются ли обязательства (>100М тг)
  "total_subsidies_received": 45000000,         // Всего получено субсидий (тг)
  "consecutive_decline_years": 0,               // Лет подряд снижения продукции
  "repeat_violation": false,                    // Повторное нарушение (бан 2 года)
  "blocked": false,                             // Блокировка
  "block_reason": null                          // Причина блокировки
}
```

**Ключевые проверки:**
- `registered` → Hard Filter #1
- `obligations_met` → Hard Filter #8
- `blocked` → Hard Filter #9
- `growth_rate`, `gross_production_*` → Soft Factor #2 (Рост продукции)
- `total_subsidies_received` > 100М → штраф в Soft Factor #1, #4 (встречные обязательства Приказ №108)
- `consecutive_decline_years` ≥ 2 → блокировка 1-2 года

### 3.2 ИАС РСЖ — Информационно-аналитическая система развития сельского хозяйства

**Источник:** `EmulatedEntity.ias_rszh_data`
**Используется в:** Hard Filters (3, 6), Soft Factors (1, 4, 8)

```json
{
  "registered": true,                          // Регистрация
  "registration_date": "2018-03-15",           // Дата регистрации
  "entity_type": "legal",                      // Тип субъекта
  "name": "ТОО \"Береке Астана\"",             // Наименование
  "region": "Акмолинская область",             // Область
  "district": "Целиноградский район",          // Район
  "subsidy_history": [                         // История субсидий
    {
      "year": 2024,                            // Год
      "type": "Приобретение маточного поголовья КРС", // Тип субсидии
      "amount": 5000000,                       // Сумма (тг)
      "heads": 50,                             // Голов
      "status": "executed",                    // Статус: executed/pending
      "obligations_met": true                  // Обязательства выполнены
    }
  ],
  "total_subsidies_history": 15000000,         // Всего субсидий за всю историю
  "pending_returns": 0,                        // Невозвращённые головы
  "ibspr_registered": true                     // Регистрация в ИБСПР
}
```

**Ключевые проверки:**
- `registered` → Hard Filter #3 (исключение: СПК освобождены)
- `ibspr_registered` → Hard Filter #6
- `subsidy_history` → Soft Factor #1 (История субсидий): подсчёт success_rate
- `pending_returns` → Soft Factor #4 (Эффективность): сохранность поголовья
- Количество субсидий → Soft Factor #8 (Первичность заявителя)

### 3.3 ЕАСУ — Единая автоматизированная система учёта

**Источник:** `EmulatedEntity.easu_data`
**Используется в:** Hard Filter (2), Soft Factor (7)

```json
{
  "has_account_number": true,                  // Учётный номер (= наличие ЭЦП)
  "account_numbers": ["KZ-AGR-123456"],        // Номера учётных записей
  "is_spk": false,                             // Является СПК
  "spk_members": [],                           // Члены кооператива
  "spk_name": null                             // Название СПК
}
```

**Ключевые проверки:**
- `has_account_number` → Hard Filter #2 (ЭЦП)
- `is_spk` → Soft Factor #7 (Тип заявителя): СПК = макс. приоритет

### 3.4 ИС ИСЖ — Информационная система идентификации сельскохозяйственных животных

**Источник:** `EmulatedEntity.is_iszh_data`
**Используется в:** Hard Filters (5, 10, 11, 16, 18), Soft Factors (3, 4)

```json
{
  "verified": true,                            // Верификация пройдена
  "total_verified": 35,                        // Верифицированных голов
  "total_rejected": 5,                         // Отклонённых голов
  "rejection_reasons": [],                     // Причины отклонения
  "animals": [                                 // Список животных
    {
      "tag_number": "KZ12345678",              // Номер бирки
      "type": "cattle",                        // Вид: cattle/sheep/horse/camel
      "breed": "Ангусская",                    // Порода
      "category": "heifer",                    // Категория: heifer/bull/ewe/ram
      "sex": "female",                         // Пол
      "birth_date": "2023-06-15",              // Дата рождения
      "age_months": 18,                        // Возраст (мес.)
      "age_valid": true,                       // Возраст в допустимом диапазоне
      "owner_iin_bin": "123456789012",         // ИИН/БИН владельца
      "owner_match": true,                     // Совпадение владельца
      "previously_subsidized": false,          // Субсидировалось ранее
      "subsidy_details": [],                   // Детали предыдущих субсидий
      "meat_kg": 220.5,                        // Продуктивность: мясо (кг)
      "milk_liters": 5500,                     // Продуктивность: молоко (л)
      "seller": {                              // Продавец
        "name": "ТОО \"АгроСнаб Казахстан\"",
        "iin_bin": "123456789012",
        "purchase_date": "2024-01-15",
        "purchase_price": 450000
      },
      "vet_status": "healthy",                 // Вет. статус: healthy/quarantine
      "last_vet_check": "2025-03-01",          // Дата последней вет. проверки
      "registration_date": "2024-02-01",       // Дата регистрации
      "pedigree_certificate": true,            // Племенное свидетельство
      "rfid_tag": "RFID-1234567",             // RFID-метка
      "rfid_active": true,                     // RFID активна
      "rfid_last_scan": "2025-04-02",          // Последнее сканирование
      "rfid_scan_count_30d": 42                // Сканирований за 30 дней
    }
  ],
  "mortality_data": {                          // Данные о падеже (Приказ №3-3/1061)
    "records": [
      {
        "animal_type": "cattle",               // Вид
        "category": "adult",                   // Категория
        "total_count": 30,                     // Всего голов
        "fallen_count": 0,                     // Павших голов
        "mortality_pct": 0.5,                  // % падежа
        "period": "2025"                       // Период
      }
    ],
    "total_mortality_pct": 0.5,                // Общий % падежа
    "reporting_year": 2025
  }
}
```

**Ключевые проверки:**
- `total_verified` > 0 → Hard Filter #5
- `animals[].age_valid` → Hard Filter #10
- `animals[].previously_subsidized` → Hard Filter #11
- `animals[].pedigree_certificate` → Hard Filter #18 (для форм 1-8)
- `mortality_data.records[].mortality_pct` > нормы → Hard Filter #16
- Поголовье + площадь пастбищ → Hard Filter #17 (нагрузка)
- `total_verified`, животные → Soft Factor #3 (Размер хозяйства)
- `pending_returns` / `total_heads_subsidized` → Soft Factor #4 (Эффективность)

### 3.5 ИС ЭСФ — Информационная система электронных счетов-фактур

**Источник:** `EmulatedEntity.is_esf_data`
**Используется в:** Hard Filter (7), Soft Factor (5)

```json
{
  "invoices": [
    {
      "esf_number": "ESF-2025-1234567",       // Номер ЭСФ
      "date": "2025-03-15",                    // Дата
      "seller_bin": "123456789012",            // БИН продавца
      "seller_name": "ТОО \"Алтын Бас\"",     // Наименование продавца
      "buyer_iin_bin": "123456789012",         // ИИН/БИН покупателя
      "total_amount": 5000000,                 // Сумма (тг)
      "items": [                               // Позиции
        {
          "description": "Племенные тёлки ангусской породы",
          "quantity": 10,
          "unit": "голова",
          "unit_price": 500000,
          "amount": 5000000
        }
      ],
      "status": "confirmed",                   // Статус: confirmed/draft
      "payment_confirmed": true                // Оплата подтверждена
    }
  ],
  "total_amount": 5000000,                     // Общая сумма ЭСФ
  "invoice_count": 1                           // Количество ЭСФ
}
```

**Ключевые проверки:**
- `payment_confirmed` = true хотя бы у одной → Hard Filter #7
- `total_amount` vs запрашиваемая сумма → Soft Factor #5 (Соответствие нормативу)

### 3.6 ЕГКН — Единый государственный кадастр недвижимости

**Источник:** `EmulatedEntity.egkn_data`
**Используется в:** Hard Filter (4, 17), Soft Factor (3)

```json
{
  "has_agricultural_land": true,               // Есть с/х земля
  "total_agricultural_area": 350.5,            // Общая площадь с/х земли (га)
  "pasture_area": 200.0,                       // Площадь пастбищ (га)
  "pasture_zone": "restored",                  // Зона: restored/degraded
  "plots": [                                   // Земельные участки
    {
      "cadastral_number": "05-123-456-789",    // Кадастровый номер
      "area_hectares": 200.0,                  // Площадь (га)
      "purpose": "сельскохозяйственное назначение", // Назначение
      "sub_purpose": "пастбище",               // Подназначение: пастбище/пашня/сенокос
      "region": "Акмолинская область",
      "district": "Целиноградский район",
      "ownership_type": "собственность",       // Тип: собственность/аренда
      "registration_date": "2018-05-20",
      "geometry": {                            // GeoJSON полигон
        "type": "Polygon",
        "coordinates": [[[69.39, 51.14], [69.41, 51.14], [69.41, 51.16], [69.39, 51.16], [69.39, 51.14]]]
      }
    }
  ]
}
```

**Ключевые проверки:**
- `has_agricultural_land` → Hard Filter #4
- `pasture_area` / поголовье → Hard Filter #17 (нагрузка на пастбища)
- `total_agricultural_area` → Soft Factor #3 (Размер хозяйства: 0-8 баллов за землю)
- `pasture_area` / условные головы КРС → Soft Factor #3 бонус/штраф за пастбища

### 3.7 Казначейство — Данные о выплатах

**Источник:** `EmulatedEntity.treasury_data`
**Используется в:** Очередь выплат

```json
{
  "payments": [
    {
      "payment_id": "PAY-2025-12345",         // ID платежа
      "amount": 5000000,                       // Сумма (тг)
      "status": "completed",                   // Статус
      "paid_date": "2025-03-20",               // Дата выплаты
      "treasury_reference": "TR-2025-12345"    // Номер Казначейства
    }
  ]
}
```

---

## 4. AI-скоринг

### 4.1 Формула итогового балла

```
Итоговый балл = ML × 0.6 + Правила × 0.4
```

- **ML-модель**: GradientBoosting (scikit-learn), обученная на 500 эмулированных хозяйствах
- **Правила**: 8 экспертных факторов, суммарно 0-100 баллов
- **Версия модели**: `2.0-ml`

### 4.2 Пороги рекомендаций

| Балл | Рекомендация | Действие |
|------|-------------|----------|
| ≥ 70 | `approve` — Одобрить | Рекомендовано к одобрению |
| 40-69 | `review` — На усмотрение | Требует внимания комиссии |
| < 40 | `reject` — Отклонить | Рекомендован отказ |
| < 20 | Автоотказ | Автоматический отказ (критически низкий балл) |

### 4.3 SHAP-объяснимость

Для каждой заявки рассчитывается SHAP-объяснение:
- `base_value` — базовый прогноз модели
- `shap_values` — вклад каждого признака (+ повышает, - снижает)
- Визуализация: горизонтальные полоски (зелёная = повышает, красная = снижает)

### 4.4 8 мягких факторов (Soft Factors)

#### Фактор 1: История субсидий (max 20, вес 0.20)

**Источник:** ИАС РСЖ + ГИСС + БД
**Формула:**
- 0 субсидий → 10 баллов (нейтральный, первичный заявитель)
- success_rate ≥ 90% → 18-20 баллов
- success_rate ≥ 70% → 14-18 баллов
- success_rate ≥ 50% → 8-14 баллов
- success_rate < 50% → 0-8 баллов
- **Штраф (Приказ №108):** если получено >100М тг и продукция падает:
  - 2+ года подряд → -6 баллов
  - 1 год → -3 балла

#### Фактор 2: Рост валовой продукции (max 20, вес 0.20)

**Источник:** ГИСС
**Формула:**
- Рост ≥ 10% → 20 баллов
- Рост 5-10% → 14-20 баллов
- Рост 0-5% → 8-14 баллов
- Снижение 0-5% → 4-8 баллов
- Снижение > 5% → 0-4 балла

#### Фактор 3: Размер хозяйства (max 15, вес 0.15)

**Источник:** ЕГКН + ИС ИСЖ
**Земля (0-8 баллов):**
- ≥ 500 га → 8
- 100-500 га → 4-8
- 10-100 га → 0.4-4
- < 10 га → 0

**Поголовье (0-7 баллов):**
- ≥ 200 голов → 7
- 50-200 → 3.5-7
- 10-50 → 0.7-3.5
- < 10 → 0

**Бонус/штраф за пастбища (Приказ №3-3/332):**
- ≥ 7 га/голову → +1.5 балла (отлично)
- 4-7 га/голову → +0.5 балла (норма)
- < 4 га/голову → -1.0 балла (перегрузка)

Пересчёт в условные головы КРС: 1 КРС = 1, 1 овца = 0.2, 1 лошадь = 1.5, 1 верблюд = 2.0

#### Фактор 4: Эффективность — сохранность поголовья (max 15, вес 0.15)

**Источник:** ИАС РСЖ + ГИСС + ИС ИСЖ
**Формула (сохранность):**
- retention_rate ≥ 98% → 15 баллов
- 90-98% → 11-15 баллов
- 80-90% → 7-11 баллов
- < 80% → 0-7 баллов

**Встречные обязательства (Приказ №108):**
- Продукция растёт/сохраняется, обязательства требуются → +2 балла
- Продукция растёт, обязательства не требуются → +1 балл
- Снижение 1 год → -2 балла (предупреждение)
- Снижение 2+ года → -5 баллов + бан (1 год первое, 2 года повторное)

**Нормы падежа (Приказ №3-3/1061):**
- ≤ 1% → +2 балла
- 1-2% → +1 балл
- 2-3% → 0 баллов
- > 3% → -2 балла

#### Фактор 5: Соответствие нормативу (max 10, вес 0.10)

**Источник:** ИС ЭСФ
**Формула:**
- Сумма по нормативу + ЭСФ покрывает → 10 баллов
- Сумма по нормативу, ЭСФ не покрывает → 6 баллов
- Расхождение с нормативом, ЭСФ покрывает → 4 балла
- Расхождение + ЭСФ не покрывает → 2 балла

#### Фактор 6: Региональный приоритет (max 10, вес 0.10)

**Источник:** Справочник REGION_PRIORITIES
**Формула:** `priority × 10`

Примеры приоритетов (0.0-1.0):
| Направление | Высокий приоритет (0.8-0.9) | Средний (0.5-0.7) | Низкий (0.3-0.4) |
|-------------|----------------------------|-------------------|-------------------|
| cattle_meat | Костанайская, Акмолинская, СКО, ВКО | Карагандинская, ЗКО, Актюбинская | Мангистауская, Кызылординская |
| cattle_dairy | Акмолинская, СКО | Алматинская, ВКО | — |
| sheep | Туркестанская, Алматинская | Жамбылская, ВКО | Кызылординская |
| horse | Костанайская | Акмолинская, Атырауская | Мангистауская |

Регион не в справочнике → 0.5 (по умолчанию)

#### Фактор 7: Тип заявителя (max 5, вес 0.05)

**Источник:** ЕАСУ
**Формула:**
- СПК (кооператив) → 5 баллов
- Юридическое лицо → 4 балла
- Физическое лицо → 3 балла

#### Фактор 8: Первичность заявителя (max 5, вес 0.05)

**Источник:** ИАС РСЖ + БД
**Формула:**
- 0 субсидий → 4 балла (приоритет новым)
- Есть субсидии, но по другим направлениям → 5 баллов (диверсификация)
- 1-3 субсидии → 3 балла (умеренный повторный)
- > 3 субсидий → 2 балла (частый заявитель)

### 4.5 Итого: максимальный балл

| # | Фактор | Max | Вес |
|---|--------|-----|-----|
| 1 | История субсидий | 20 | 0.20 |
| 2 | Рост валовой продукции | 20 | 0.20 |
| 3 | Размер хозяйства | 15 | 0.15 |
| 4 | Эффективность (сохранность) | 15 | 0.15 |
| 5 | Соответствие нормативу | 10 | 0.10 |
| 6 | Региональный приоритет | 10 | 0.10 |
| 7 | Тип заявителя | 5 | 0.05 |
| 8 | Первичность заявителя | 5 | 0.05 |
| **Итого** | | **100** | **1.00** |

---

## 5. Merit Score — Приоритизация выплат

### 5.1 Формула

```
Merit Score = 30% × масштаб хозяйства + 25% × финансовая эффективность
            + 25% × история субсидий + 20% × приоритет направления
```

### 5.2 Компоненты

| Компонент | Вес | Источник | Расчёт |
|-----------|-----|----------|--------|
| Масштаб хозяйства | 30% | ScoreFactor `farm_size` | `value / max_value × 100` |
| Финансовая эффективность | 25% | ScoreFactor `financial_stability` | `value / max_value × 100` |
| История субсидий | 25% | ScoreFactor `subsidy_history` | `value / max_value × 100` |
| Приоритет направления | 20% | Код направления | Фиксированные значения |

### 5.3 Приоритеты направлений

| Направление | Код | Приоритет |
|-------------|-----|-----------|
| Племенное | breeding | 90 |
| Кормопроизводство | feed_production | 80 |
| Животноводство | livestock | 75 |
| Ветеринария | veterinary | 70 |
| Растениеводство | crop | 60 |
| Прочие | — | 50 |

---

## 6. 18 Hard Filters — подробное описание

### Фильтры 1-11: Базовые проверки

| # | Фильтр | Логика | Нормативный акт |
|---|--------|--------|-----------------|
| 1 | ГИСС | `giss_data.registered == true` | Приказ №108 |
| 2 | ЭЦП | `easu_data.has_account_number == true` | Закон об ЭЦП |
| 3 | ИАС РСЖ | `ias_rszh_data.registered == true` (СПК освобождены) | Приказ №108 |
| 4 | Земля ЕГКН | `egkn_data.has_agricultural_land == true` | Земельный кодекс |
| 5 | ИС ИСЖ | `is_iszh_data.total_verified > 0` | Закон о ветеринарии |
| 6 | ИБСПР | `ias_rszh_data.ibspr_registered == true` | Приказ №108 |
| 7 | ЭСФ | Хотя бы одна ЭСФ с `payment_confirmed == true` | НК РК |
| 8 | Обязательства | `obligations_met == true` или `obligations_required == false` | Приказ №108 |
| 9 | Блокировка | Нет блокировки в ГИСС и Applicant (проверка даты) | Приказ №108 |
| 10 | Возраст | Все выбранные животные: `age_valid == true` | Приказ №108 |
| 11 | Не субсидировались | Все выбранные: `previously_subsidized == false` | Приказ №108 |

### Фильтры 12-15: Приказ №108

| # | Фильтр | Логика |
|---|--------|--------|
| 12 | Период подачи | Дата подачи в пределах ApplicationPeriod |
| 13 | Лимит 50% | Для форм 1-8: `total_amount ≤ estimated_cost × 0.5` |
| 14 | Мин. поголовье | По SubsidyType.min_herd_size или спец. требования (откормплощадки: КРС≥1000, овцы≥5000; МТФ≥50) |
| 15 | Нет дубликатов | Нет одобренных/оплаченных заявок того же типа в текущем году |

### Фильтры 16-18: Нормативные документы

| # | Фильтр | Логика | Нормативный акт |
|---|--------|--------|-----------------|
| 16 | Падёж | Фактический % ≤ нормативного по виду/категории | Приказ №3-3/1061 от 26.12.2018 |
| 17 | Нагрузка на пастбища | `pasture_area ≥ cattle_equiv × regional_norm` | Приказ №3-3/332 |
| 18 | Племенное свид-во | Для форм 1-8: все животные имеют `pedigree_certificate` | Приказ №108 |

### Нормы падежа (Приказ №3-3/1061)

| Вид | Категория | Макс. % падежа |
|-----|-----------|----------------|
| КРС мясное | телята | 2.0% |
| КРС мясное | молодняк | 2.0% |
| КРС мясное | маточное | 2.0% |
| КРС мясное | импорт авиа | 2.5% |
| КРС мясное | импорт авто/жд | 5.0% |
| КРС молочное | телята до 20 дней | 3.5% |
| КРС молочное | маточное | 3.0% |
| Овцы | взрослые | 3.0% |
| Овцы | ягнята | 5.0% |
| Лошади (табунное) | жеребята | 2.3% |
| Лошади | взрослые | 2.0% |
| Верблюды | взрослые | 2.0% |
| Верблюды | молодняк | 3.0% |

### Нормы нагрузки на пастбища (Приказ №3-3/332)

| Регион | Восстановленные (га/гол КРС) | Деградированные (га/гол КРС) |
|--------|-------------------------------|-------------------------------|
| Акмолинская | 5.0 | 8.0 |
| Костанайская | 5.5 | 8.5 |
| Павлодарская | 6.0 | 10.0 |
| Северо-Казахстанская | 4.5 | 7.0 |
| Алматинская | 5.0 | 9.0 |
| ВКО | 5.0 | 8.0 |
| Карагандинская | 7.0 | 12.0 |
| Туркестанская | 8.0 | 14.0 |
| Жамбылская | 7.0 | 12.0 |
| ЗКО | 6.0 | 10.0 |
| Актюбинская | 7.0 | 12.0 |
| Кызылординская | 10.0 | 18.0 |
| Атырауская | 12.0 | 20.0 |
| Мангистауская | 14.0 | 22.0 |
| Абай | 6.0 | 10.0 |
| Жетісу | 5.5 | 9.0 |
| Ұлытау | 8.0 | 14.0 |

---

## 7. Роли и доступ

### 7.1 Фермер (applicant)

**Видит:**
- Свои заявки (список + детали)
- AI-скоринг как РЕКОМЕНДАЦИЮ (не решение)
- SHAP-визуализацию (объяснение каждого фактора)
- Статус-баннер: Подана → Специалист → Комиссия → Решение
- Уведомления о результатах

**Может:**
- Подать новую заявку (выбрать направление, вид, количество, приложить ЭСФ)
- Просматривать историю заявок

### 7.2 Специалист МИО (mio_specialist)

**Видит:**
- Все заявки в статусе `submitted` (отсортированы по AI-скору, не по дате!)
- Панель проверки: данные заявителя, документы, суммы, скоринг, земля, животные
- Очередь выплат с Merit Score

**Может:**
- Проверить заявку по чек-листу (6 пунктов)
- Передать комиссии (статус submitted → checking)
- Управлять очередью выплат

### 7.3 Комиссия (commission_member)

**Видит:**
- Заявки в статусе `checking` (только проверенные специалистом!)
- Ранжирование по AI-скору

**Может:**
- Одобрить заявку (→ формируется платёж)
- Отклонить заявку с обоснованием
- Запросить доп. проверку

### 7.4 Руководитель МИО (mio_head)

**Видит:**
- Все заявки всех статусов
- Аналитику и статистику
- Очередь выплат

**Может:**
- Подтвердить решения комиссии
- Управлять бюджетами

### 7.5 Администратор (admin)

**Видит:** Всё

**Может:**
- Все действия всех ролей
- Управление пользователями
- Настройки системы
- Управление SubsidyType, SubsidyDirection, ApplicationPeriod

### 7.6 Аудитор (auditor)

**Видит:**
- Все заявки (только чтение)
- Журнал аудита (AuditLog)
- Статистику и аналитику

**Может:**
- Просматривать (без права изменения)

---

## 8. Процесс обработки заявки (полный flow)

```
1. Фермер подаёт заявку → status: submitted
   ↓
2. AI-скоринг запускается автоматически:
   a) Hard Filters (18 проверок) → если FAIL → status: rejected + уведомление
   b) Soft Factors (8 факторов) → 0-100 баллов (правила)
   c) ML-модель GradientBoosting → 0-100 баллов
   d) Итого: ML × 0.6 + Правила × 0.4 = total_score
   e) Рекомендация: approve / review / reject
   f) SHAP-объяснение
   ↓
3. Специалист МИО видит заявку (отсортирована по скору):
   a) Проверяет чек-лист (6 пунктов)
   b) Передаёт комиссии → status: checking
   ↓
4. Комиссия видит проверенные заявки:
   a) Ранжирование по баллам
   b) Одобряет → status: approved + создаётся Payment
   ↓
5. Очередь выплат (Merit Score вместо FIFO):
   a) Payment.merit_score рассчитывается
   b) Сортировка по Merit Score (не по дате!)
   c) Бюджет: красная линия отсечки
   d) Если бюджет < суммы → дефицит, возможна частичная выплата
   ↓
6. Выплата:
   a) Полная → status: paid
   b) Частичная → status: partially_paid + остаток в waiting_list
   c) Нехватка бюджета → status: waiting_list
```

### 6 точек замены FIFO на Merit-based

| # | Точка | Было (FIFO) | Стало (SubsidyAI) |
|---|-------|-------------|-------------------|
| 1 | Проверка специалистом | По дате подачи | По AI-скору |
| 2 | Рассмотрение комиссией | По дате | По AI-баллу |
| 3 | Очередь на выплату | По дате | По Merit Score |
| 4 | Нехватка бюджета | Перенос по дате | Перенос по Merit Score |
| 5 | Частичная выплата | По дате | По Merit Score |
| 6 | Перераспределение между регионами | Вручную | На основе дефицитов и Merit Score |

---

## 9. Данные для демо

- **500** эмулированных хозяйств (EmulatedEntity)
- **~300** тестовых заявок
- **11** демо-аккаунтов, **5** ролей
- **17** регионов Казахстана
- **4** профиля риска: clean (70%), minor_issues (15%), risky (10%), fraudulent (5%)

### Демо-аккаунты

| Логин | Роль | Описание |
|-------|------|----------|
| bereke | applicant | СПК «Береке Астана» |
| specialist | mio_specialist | Специалист МИО |
| commission | commission_member | Член комиссии |
| head | mio_head | Руководитель МИО |
| admin | admin | Администратор |

Пароль для всех: `demo123`

---

## 10. Нормативная база

| Документ | Что регулирует |
|----------|---------------|
| **Приказ №108 МСХ РК** | Правила субсидирования АПК: формы, нормативы, встречные обязательства, блокировка |
| **Приказ №3-3/1061 от 26.12.2018** | Нормы естественной убыли (падежа) животных |
| **Приказ №3-3/332** | Предельно допустимые нормы нагрузки на пастбища по регионам |
| **Налоговый кодекс РК** | ЭСФ (электронные счета-фактуры) |
| **Закон об ЭЦП** | Электронная цифровая подпись |
| **Земельный кодекс** | Кадастр, целевое назначение земель |

---

## 11. Технический стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Django 5.1, Python 3.12 |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| ML | scikit-learn (GradientBoosting), SHAP |
| Frontend | Django Templates, Tailwind CSS, Alpine.js |
| Deployment | Docker Compose, Gunicorn, Nginx |
| Server | 109.235.119.92 (VPS) |
