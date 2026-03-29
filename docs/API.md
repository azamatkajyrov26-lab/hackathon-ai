# REST API Endpoints

## Base URL: `/api/v1/`

---

## Scoring App API

### Заявки (Applications)

#### `GET /api/v1/applications/`
Список заявок с фильтрацией и пагинацией.

**Доступ:** mio_specialist, commission_member, mio_head, admin, auditor

**Query params:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| status | string | Фильтр по статусу: submitted, approved, rejected, waiting_list, paid |
| region | string | Фильтр по области |
| district | string | Фильтр по району |
| direction | string | Фильтр по направлению субсидирования |
| score_min | float | Минимальный балл |
| score_max | float | Максимальный балл |
| date_from | date | Дата подачи от |
| date_to | date | Дата подачи до |
| ordering | string | Сортировка: -score__total_score, submitted_at, total_amount |
| search | string | Поиск по номеру заявки, ИИН/БИН, имени |
| page | int | Страница |
| page_size | int | Размер страницы (default 20) |

**Response 200:**
```json
{
  "count": 1247,
  "next": "/api/v1/applications/?page=2",
  "results": [
    {
      "id": 1,
      "number": "01300100258072",
      "applicant": {
        "iin_bin": "123456789012",
        "name": "ТОО 'Агрофирма Астана'",
        "entity_type": "legal"
      },
      "subsidy_type": {
        "name": "Приобретение маточного поголовья КРС — отечественный",
        "direction": "Мясное скотоводство",
        "form_number": 1
      },
      "status": "approved",
      "quantity": 20,
      "rate": 260000,
      "total_amount": 5200000,
      "region": "Акмолинская область",
      "district": "Целиноградский район",
      "submitted_at": "2025-01-21T11:15:40Z",
      "score": {
        "total_score": 94.0,
        "rank": 1,
        "recommendation": "approve"
      }
    }
  ]
}
```

---

#### `POST /api/v1/applications/`
Создание новой заявки (подача).

**Доступ:** applicant

**Request:**
```json
{
  "subsidy_type_id": 1,
  "quantity": 20,
  "unit_price": 390000,
  "region": "Акмолинская область",
  "district": "Целиноградский район",
  "akimat": "ГУ 'Управление сельского хозяйства Акмолинской области'",
  "animals_data": [
    {"tag_number": "KZ00123456", "type": "cattle", "category": "heifer", "breed": "Ангусская", "age_months": 12}
  ],
  "esf_number": "ESF-2025-0001234",
  "esf_amount": 7800000,
  "counterparty_bin": "987654321098",
  "counterparty_name": "ТОО 'Племенное хозяйство Алтай'",
  "land_cadastral": "01-234-567-890"
}
```

**Response 201:** Объект заявки с присвоенным номером и статусом `submitted`.

---

#### `GET /api/v1/applications/{id}/`
Полная карточка заявки.

**Доступ:** applicant (своя), mio_specialist (свой регион), commission_member, mio_head, admin, auditor

**Response 200:**
```json
{
  "id": 1,
  "number": "01300100258072",
  "applicant": { "...полные данные заявителя..." },
  "subsidy_type": { "...тип субсидии с нормативом..." },
  "status": "approved",
  "quantity": 20,
  "total_amount": 5200000,
  "animals_data": [ "...данные о животных..." ],
  "documents": [ "...загруженные документы..." ],
  "hard_filter_result": { "...результат 10 проверок..." },
  "score": {
    "total_score": 94.0,
    "rank": 1,
    "recommendation": "approve",
    "factors": [ "...8 факторов с объяснениями..." ]
  },
  "external_data": {
    "giss": { "...данные ГИСС..." },
    "ias_rszh": { "...данные ИАС РСЖ..." },
    "easu": { "...данные ЕАСУ..." },
    "is_iszh": { "...данные ИС ИСЖ..." },
    "is_esf": { "...данные ИС ЭСФ..." },
    "egkn": { "...данные ЕГКН..." },
    "treasury": { "...данные Казначейства..." }
  },
  "decisions": [ "...история решений..." ]
}
```

---

#### `POST /api/v1/applications/{id}/run-scoring/`
Запуск скоринга для заявки.

**Доступ:** mio_specialist, admin

**Response 200:**
```json
{
  "hard_filters_passed": true,
  "score": {
    "total_score": 94.0,
    "factors": [
      {
        "factor_code": "subsidy_history",
        "factor_name": "История субсидий",
        "value": 18.0,
        "max_value": 20.0,
        "explanation": "5 успешных заявок, все обязательства выполнены"
      }
    ],
    "recommendation": "approve"
  }
}
```

---

#### `POST /api/v1/applications/{id}/decide/`
Принятие решения комиссией.

**Доступ:** commission_member, mio_head

**Request:**
```json
{
  "decision": "approved",
  "reason": "Заявитель соответствует всем критериям, высокий балл скоринга",
  "approved_amount": 5200000
}
```

---

#### `POST /api/v1/applications/{id}/upload-document/`
Загрузка документа к заявке.

**Доступ:** applicant

**Request:** multipart/form-data
| Поле | Тип | Описание |
|------|-----|----------|
| doc_type | string | Тип документа (contract, esf, customs_declaration...) |
| name | string | Название |
| file | file | Файл (PDF, JPG, PNG) |

---

### Скоринг (Scoring)

#### `GET /api/v1/scoring/ranking/`
Ранжированный список заявок по баллам.

**Доступ:** commission_member, mio_head, admin, auditor

**Query params:** region, direction, score_min, score_max

**Response 200:**
```json
{
  "total_applications": 342,
  "total_budget_needed": 890000000,
  "available_budget": 750000000,
  "results": [
    {
      "rank": 1,
      "application_number": "01300100258072",
      "applicant_name": "ТОО 'Агрофирма Астана'",
      "total_score": 94.0,
      "total_amount": 5200000,
      "cumulative_amount": 5200000,
      "within_budget": true,
      "recommendation": "approve"
    }
  ]
}
```

---

### Аналитика (Analytics)

#### `GET /api/v1/analytics/summary/`
Сводная статистика.

**Доступ:** mio_specialist, commission_member, mio_head, admin, auditor

**Response 200:**
```json
{
  "total_applications": 1247,
  "by_status": {
    "submitted": 89,
    "checking": 12,
    "approved": 342,
    "rejected": 156,
    "waiting_list": 298,
    "paid": 350
  },
  "total_budget": 2500000000,
  "spent_budget": 1950000000,
  "budget_utilization_pct": 78.0,
  "avg_score": 72.4,
  "avg_processing_days": 3.2,
  "by_region": [ {"region": "Акмолинская область", "count": 156, "amount": 450000000} ],
  "by_direction": [ {"direction": "Мясное скотоводство", "count": 423, "amount": 890000000} ],
  "score_distribution": [ {"range": "90-100", "count": 45}, {"range": "80-89", "count": 112} ]
}
```

#### `GET /api/v1/analytics/by-region/`
Аналитика по регионам.

#### `GET /api/v1/analytics/by-direction/`
Аналитика по направлениям.

#### `GET /api/v1/analytics/score-distribution/`
Распределение баллов.

#### `GET /api/v1/analytics/budget/`
Бюджет план/факт по регионам и направлениям.

---

## Emulator App API

Полные контракты описаны в `05_ИНТЕГРАЦИИ_ЭМУЛЯЦИЯ.md`. Краткий список:

| # | Endpoint | Метод | Система |
|---|----------|-------|---------|
| 1 | `/api/emulator/giss/check-obligations/` | POST | ГИСС — встречные обязательства |
| 2 | `/api/emulator/ias-rszh/check-registration/` | POST | ИАС "РСЖ" — регистрация, история |
| 3 | `/api/emulator/easu/get-account-numbers/` | POST | ЕАСУ — учётные номера |
| 4 | `/api/emulator/is-iszh/verify-livestock/` | POST | ИС "ИСЖ" — идентификация животных |
| 5 | `/api/emulator/is-esf/get-invoices/` | POST | ИС "ЭСФ" — счета-фактуры |
| 6 | `/api/emulator/egkn/get-land-plots/` | POST | ЕГКН — земельный кадастр |
| 7 | `/api/emulator/treasury/submit-payment/` | POST | Казначейство — подача платежа |
| 8 | `/api/emulator/treasury/payment-status/{id}/` | GET | Казначейство — статус платежа |

---

## Аутентификация (MVP)

Для хакатона: session-based auth через Django. Выбор роли при логине.

```
POST /api/v1/auth/login/    — вход (username + password + role)
POST /api/v1/auth/logout/   — выход
GET  /api/v1/auth/me/       — текущий пользователь и его роль
```
