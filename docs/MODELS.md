# Модели базы данных

## ER-диаграмма (связи)

```
User (Django) ──1:1──► UserProfile (роль, регион)
                            │
                            ▼
Applicant ──1:N──► Application ──1:1──► HardFilterResult
    │                   │                      │
    │                   ├──1:1──► Score ──1:N──► ScoreFactor
    │                   │
    │                   ├──1:N──► ApplicationDocument
    │                   │
    │                   └──1:N──► Decision
    │
    └──── iin_bin ────► EmulatedEntity (emulator app)
                            │
                            ├──► GISSData
                            ├──► IASRSZHData
                            ├──► EASUData
                            ├──► ISISZHData (livestock)
                            ├──► ISESFData (invoices)
                            ├──► EGKNData (land)
                            └──► TreasuryData (payments)
```

---

## App: scoring

### UserProfile
Расширение Django User для ролей и региональной привязки.

| Поле | Тип | Описание |
|------|-----|----------|
| user | OneToOne → User | Django user |
| role | CharField choices | applicant, mio_specialist, commission_member, mio_head, admin, auditor |
| region | CharField | Область (для фильтрации) |
| district | CharField null | Район (опционально) |
| organization | CharField null | Название организации (Акимат и т.д.) |
| phone | CharField null | Контактный телефон |

---

### Applicant
Заявитель — физлицо, юрлицо или СПК.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| iin_bin | CharField(12) unique | ИИН (12 цифр) или БИН (12 цифр) |
| name | CharField(500) | ФИО или наименование юрлица |
| entity_type | CharField choices | individual (физлицо), legal (юрлицо), cooperative (СПК) |
| region | CharField(200) | Область |
| district | CharField(200) | Район |
| address | TextField null | Полный адрес |
| phone | CharField(20) null | Телефон |
| email | EmailField null | Email |
| bank_account | CharField(34) null | IBAN (KZxxxxxxxxxx) |
| bank_name | CharField(200) null | Название банка |
| registration_date | DateField | Дата регистрации в системе |
| is_blocked | BooleanField default=False | Блокировка за невыполнение обязательств |
| block_reason | TextField null | Причина блокировки |
| block_until | DateField null | Дата окончания блокировки |
| created_at | DateTimeField auto | Дата создания записи |

---

### SubsidyDirection
Справочник направлений субсидирования.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| code | CharField(20) unique | Код направления (cattle_breeding, dairy, sheep...) |
| name | CharField(500) | Название: "Мясное скотоводство" |
| description | TextField | Описание |
| is_active | BooleanField | Активно ли направление |

---

### SubsidyType
Справочник конкретных видов субсидий с нормативами.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| direction | FK → SubsidyDirection | Направление |
| form_number | IntegerField | Номер формы заявки (1-16) |
| name | CharField(500) | "Приобретение племенного маточного поголовья КРС — отечественный" |
| unit | CharField(50) | Единица: голова, кг, доза, штука |
| rate | DecimalField | Норматив в тенге на 1 единицу |
| origin | CharField choices | domestic (отечественный), cis (СНГ), import (дальнее зарубежье) |
| min_age_months | IntegerField null | Мин. возраст животного (мес.) |
| max_age_months | IntegerField null | Макс. возраст животного (мес.) |
| min_herd_size | IntegerField null | Мин. поголовье (для молочных) |
| requires_commission | BooleanField | Требуется заключение спецкомиссии |
| is_active | BooleanField | Активен |

---

### Application
Заявка на субсидию.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| number | CharField(20) unique | Номер заявки: 01300100258072 |
| applicant | FK → Applicant | Заявитель |
| subsidy_type | FK → SubsidyType | Вид субсидии |
| status | CharField choices | draft, submitted, checking, approved, rejected, waiting_list, partially_paid, paid |
| quantity | IntegerField | Количество (голов / кг / доз) |
| unit_price | DecimalField | Цена за единицу (фактическая) |
| rate | DecimalField | Норматив субсидии за единицу |
| total_amount | DecimalField | Причитающаяся сумма (quantity x rate) |
| submitted_at | DateTimeField | Дата/время подачи |
| region | CharField(200) | Область хозяйства |
| district | CharField(200) | Район хозяйства |
| akimat | CharField(500) | Управление сельского хозяйства |
| animals_data | JSONField null | Данные о животных [{tag, breed, age, sex, category}] |
| esf_number | CharField null | Номер ЭСФ |
| esf_amount | DecimalField null | Сумма по ЭСФ |
| counterparty_bin | CharField(12) null | БИН продавца |
| counterparty_name | CharField(500) null | Наименование продавца |
| land_cadastral | CharField null | Кадастровый номер участка |
| spk_name | CharField null | Название СПК (если кооператив) |
| spk_membership_doc | CharField null | Документ о членстве в СПК |
| notes | TextField null | Примечания |
| created_at | DateTimeField auto | Создана |
| updated_at | DateTimeField auto | Обновлена |

**Статусы заявки:**
- `draft` — черновик, не отправлена
- `submitted` — подана, ожидает проверки
- `checking` — на автоматической проверке (hard filters)
- `approved` — прошла проверку, в ранжированном списке
- `rejected` — отказ (hard filter или комиссия)
- `waiting_list` — в листе ожидания (бюджет)
- `partially_paid` — частично выплачена
- `paid` — полностью выплачена

---

### ApplicationDocument
Загруженные документы к заявке.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| application | FK → Application | Заявка |
| doc_type | CharField choices | contract, esf, customs_declaration, quarantine_act, commission_conclusion, spk_membership, payment_confirmation, veterinary_certificate, pedigree_certificate, other |
| name | CharField(500) | Название документа |
| file | FileField | Файл (upload) |
| uploaded_at | DateTimeField auto | Дата загрузки |
| verified | BooleanField default=False | Проверен специалистом |
| verified_by | FK → User null | Кто проверил |
| verified_at | DateTimeField null | Когда проверен |

**Типы документов:**
- `contract` — Договор купли-продажи
- `esf` — Электронная счет-фактура (ЭСФ)
- `customs_declaration` — Таможенная декларация (при импорте)
- `quarantine_act` — Акт карантинирования у продавца (при импорте)
- `commission_conclusion` — Заключение специальной комиссии (Приложение 5)
- `spk_membership` — Документ о членстве в СПК
- `payment_confirmation` — Подтверждение оплаты
- `veterinary_certificate` — Ветеринарный сертификат
- `pedigree_certificate` — Племенное свидетельство
- `other` — Прочие документы

---

### HardFilterResult
Результат проверки 10 hard filters для заявки.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| application | OneToOne → Application | Заявка |
| giss_registered | BooleanField | Регистрация в ГИСС |
| has_eds | BooleanField | Наличие ЭЦП |
| ias_rszh_registered | BooleanField | Учётный номер в ИАС "РСЖ" |
| has_agricultural_land | BooleanField | Земельный участок с/х назначения (ЕГКН) |
| is_iszh_registered | BooleanField | Регистрация в ИС ИСЖ |
| ibspr_registered | BooleanField | Регистрация в ИБСПР |
| esf_confirmed | BooleanField | Подтверждение затрат через ЭСФ |
| no_unfulfilled_obligations | BooleanField | Нет невыполненных обязательств |
| no_block | BooleanField | Нет блокировки за встречные обязательства |
| animals_age_valid | BooleanField | Возраст животных в допустимом диапазоне |
| animals_not_subsidized | BooleanField | Животные не субсидировались ранее |
| all_passed | BooleanField | Все проверки пройдены |
| failed_reasons | JSONField default=list | Список причин отказа ["Нет регистрации в ГИСС", ...] |
| checked_at | DateTimeField auto | Дата проверки |
| raw_responses | JSONField default=dict | Сырые ответы от 7 систем |

---

### Score
Результат AI-скоринга заявки.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| application | OneToOne → Application | Заявка |
| total_score | DecimalField(5,2) | Итоговый балл 0-100 |
| rank | IntegerField null | Позиция в рейтинге (по области + направлению) |
| recommendation | CharField choices | approve, review, reject |
| recommendation_reason | TextField | Текстовое обоснование рекомендации AI |
| calculated_at | DateTimeField auto | Дата расчета |
| model_version | CharField | Версия модели скоринга |

**Рекомендации:**
- `approve` — балл >= 70, рекомендовано к одобрению
- `review` — балл 40-69, требует внимания комиссии
- `reject` — балл < 40, высокий риск

---

### ScoreFactor
Детализация по каждому фактору скоринга (explainability).

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| score | FK → Score | Скоринг |
| factor_code | CharField | subsidy_history, production_growth, farm_size, efficiency, rate_compliance, region_priority, entity_type, applicant_history |
| factor_name | CharField | "История субсидий" |
| value | DecimalField(5,2) | Полученное значение (напр. 18.0) |
| max_value | DecimalField(5,2) | Максимум по фактору (напр. 20.0) |
| weight | DecimalField(3,2) | Вес фактора (напр. 0.20) |
| weighted_value | DecimalField(5,2) | value * weight |
| explanation | TextField | "5 успешных заявок за 3 года, все обязательства выполнены, 0 возвратов" |
| data_source | CharField | Из какой системы данные: giss, ias_rszh, easu, is_iszh, is_esf, egkn, treasury |
| raw_data | JSONField null | Исходные данные для расчета |

---

### Decision
Решение комиссии по заявке.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| application | FK → Application | Заявка |
| decision | CharField choices | approved, rejected, review, partially_approved |
| decided_by | FK → User | Кто принял решение |
| reason | TextField | Обоснование решения |
| rejection_grounds | JSONField null | Основания отказа (из списка 10 оснований) |
| approved_amount | DecimalField null | Одобренная сумма (если частично) |
| decided_at | DateTimeField auto | Дата решения |
| confirmed_by | FK → User null | Руководитель МИО (утверждение) |
| confirmed_at | DateTimeField null | Дата утверждения |

**Решения:**
- `approved` — одобрено, направлено на выплату
- `rejected` — отказ с мотивированным обоснованием (Приложение 7)
- `review` — отправлено на дополнительную проверку
- `partially_approved` — частичное одобрение (нехватка бюджета)

---

### Budget
Бюджет по регионам и направлениям.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| year | IntegerField | Год |
| region | CharField(200) | Область |
| direction | FK → SubsidyDirection | Направление |
| planned_amount | DecimalField | Плановый бюджет (тг) |
| spent_amount | DecimalField default=0 | Освоенный бюджет (тг) |
| remaining_amount | DecimalField | Остаток |

---

## App: emulator

### EmulatedEntity
Базовая сущность, сгенерированная из Excel-данных.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BigAutoField | PK |
| iin_bin | CharField(12) unique | Синтетический ИИН/БИН |
| name | CharField(500) | Название хозяйства |
| entity_type | CharField | individual, legal, cooperative |
| region | CharField(200) | Область (из Excel) |
| district | CharField(200) | Район (из Excel) |
| registration_date | DateField | Дата регистрации |
| giss_data | JSONField | Данные ГИСС (валовая продукция, обязательства) |
| ias_rszh_data | JSONField | Данные ИАС РСЖ (история субсидий) |
| easu_data | JSONField | Данные ЕАСУ (учетные номера) |
| is_iszh_data | JSONField | Данные ИС ИСЖ (животные) |
| is_esf_data | JSONField | Данные ИС ЭСФ (счета-фактуры) |
| egkn_data | JSONField | Данные ЕГКН (земельные участки) |
| treasury_data | JSONField | Данные Казначейства (платежи) |
| risk_profile | CharField choices | clean, minor_issues, risky, fraudulent |
| source_row | IntegerField null | Номер строки из Excel |
| created_at | DateTimeField auto | Создана |

**risk_profile** — для генерации реалистичных данных:
- `clean` (70%) — идеальный заявитель, все ОК
- `minor_issues` (15%) — мелкие проблемы (просрочки, неполные данные)
- `risky` (10%) — серьезные проблемы (невыполненные обязательства, маленькое хозяйство)
- `fraudulent` (5%) — подозрительный (повторные субсидии, несоответствие данных)

---

## Индексы

```sql
-- Быстрый поиск по ИИН/БИН
CREATE INDEX idx_applicant_iin_bin ON scoring_applicant(iin_bin);
CREATE INDEX idx_emulated_iin_bin ON emulator_emulatedentity(iin_bin);

-- Фильтрация заявок
CREATE INDEX idx_application_status ON scoring_application(status);
CREATE INDEX idx_application_region ON scoring_application(region);
CREATE INDEX idx_application_submitted ON scoring_application(submitted_at);

-- Скоринг
CREATE INDEX idx_score_total ON scoring_score(total_score DESC);
CREATE INDEX idx_score_rank ON scoring_score(rank);
```
