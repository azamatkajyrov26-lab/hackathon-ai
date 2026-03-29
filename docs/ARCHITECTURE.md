# Архитектура SubsidyAI

## 1. Общая схема системы

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ПОЛЬЗОВАТЕЛИ                                 │
│  Заявитель  Специалист МИО  Комиссия  Руководитель  Аудитор  Админ │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTPS
                           ▼
                    ┌──────────────┐
                    │    Nginx     │  SSL termination + reverse proxy
                    │   (host)     │
                    └──────┬───────┘
                           │ :8000
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Docker Compose                                │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    Django 5.1 + Gunicorn                    │  │
│  │                                                             │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │  │
│  │  │   Views &    │  │   Scoring    │  │    Emulator      │  │  │
│  │  │  Templates   │  │   Engine     │  │  (7 InfoSystems) │  │  │
│  │  └─────────────┘  └──────┬───────┘  └──────────────────┘  │  │
│  │                          │                                  │  │
│  │         ┌────────────────┼────────────────┐                │  │
│  │         ▼                ▼                ▼                │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────┐      │  │
│  │  │   Hard      │  │   Soft     │  │  ML Model      │      │  │
│  │  │  Filters    │  │  Factors   │  │  (Gradient     │      │  │
│  │  │  (11 шт.)   │  │  (8 шт.)   │  │   Boosting)    │      │  │
│  │  └────────────┘  └────────────┘  └────────────────┘      │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│              ┌───────────┼───────────┐                            │
│              ▼                       ▼                            │
│      ┌──────────────┐       ┌──────────────┐                    │
│      │ PostgreSQL 16 │       │   Redis 7    │                    │
│      │   (данные)    │       │ (кеш+сессии) │                    │
│      └──────────────┘       └──────────────┘                    │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Модели данных (ER-диаграмма)

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User (Django)  │────│   UserProfile     │     │ EmulatedEntity  │
│                  │ 1:1│                   │     │                 │
│ username         │    │ role              │     │ iin_bin (PK)    │
│ password         │    │ region            │     │ name            │
│ first_name       │    │ organization      │     │ entity_type     │
│ last_name        │    │ iin_bin           │     │ region          │
└─────────────────┘    │ phone             │     │ giss_data (JSON)│
                        └──────────────────┘     │ ias_data  (JSON)│
                                                  │ easu_data (JSON)│
┌─────────────────┐                               │ is_iszh   (JSON)│
│ SubsidyDirection │◄──────────┐                  │ is_esf    (JSON)│
│                  │           │                  │ egkn_data (JSON)│
│ code             │    ┌──────┴──────────┐       │ treasury  (JSON)│
│ name             │    │  SubsidyType    │       └─────────────────┘
└────────┬─────────┘    │                 │
         │              │ name            │       ┌─────────────────┐
         │              │ form_number     │       │    Budget       │
         │              │ unit            │       │                 │
         │              │ rate            │       │ year            │
         │              │ origin          │       │ region          │
         │              │ min_age_months  │       │ direction ──────┤►
         │              │ max_age_months  │       │ planned_amount  │
         │              │ min_herd_size   │       │ spent_amount    │
         │              └────────┬────────┘       └─────────────────┘
         │                       │
         │              ┌────────┴────────┐
         │              │  Application    │◄──────────────────────────┐
         │              │                 │                           │
         │              │ number          │       ┌─────────────────┐ │
         │              │ applicant ──────┤──────►│   Applicant     │ │
         │              │ subsidy_type ───┤       │                 │ │
         │              │ status          │       │ iin_bin         │ │
         │              │ quantity         │       │ name            │ │
         │              │ total_amount    │       │ entity_type     │ │
         │              │ region          │       │ region          │ │
         │              │ animals_data    │       │ bank_account    │ │
         │              │ plots_data      │       └─────────────────┘ │
         │              │ invoices_data   │                           │
         │              │ submitted_at    │                           │
         │              └────────┬────────┘                           │
         │                       │                                    │
         │          ┌────────────┼────────────┬──────────────┐       │
         │          ▼            ▼            ▼              ▼       │
         │   ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
         │   │   Score    │ │HardFilter│ │ Decision │ │ Payment  │  │
         │   │           │ │ Result   │ │          │ │          │  │
         │   │total_score│ │          │ │decided_by│ │amount    │  │
         │   │ml_score   │ │all_passed│ │decided_at│ │status    │  │
         │   │rule_score │ │results   │ │decision  │ │treasury  │  │
         │   │recommend. │ │ (JSON)   │ │reason    │ │  _number │  │
         │   │confidence │ │failed_   │ │confirmed │ └──────────┘  │
         │   │rank       │ │ reasons  │ │  _by     │               │
         │   │explanation│ │ (JSON)   │ └──────────┘               │
         │   └─────┬─────┘ └──────────┘                            │
         │         │                                                │
         │         ▼                                                │
         │   ┌───────────┐      ┌──────────────────┐              │
         │   │ScoreFactor│      │  Notification     │              │
         │   │(8 per app)│      │                   │──────────────┘
         │   │           │      │ application       │
         │   │name       │      │ type              │
         │   │value      │      │ title             │
         │   │max_value  │      │ message           │
         │   │weight     │      │ is_read           │
         │   │explanation│      └──────────────────┘
         │   │data_source│
         │   └───────────┘
```

### Статусы заявки (Application.status)

```
draft → submitted → checking → approved → paid
                       │           │
                       │           └─→ partially_paid → paid
                       │
                       ├─→ rejected
                       │
                       └─→ waiting_list → approved (при освобождении бюджета)
```

### Роли пользователей

| Роль | Код | Доступные страницы |
|------|-----|-------------------|
| Заявитель | `applicant` | Подача заявки, мои заявки, уведомления |
| Специалист МИО | `mio_specialist` | Все заявки, скоринг рейтинг, эмулятор, аналитика |
| Член комиссии | `commission_member` | Комиссия, решения по заявкам, рейтинг |
| Руководитель МИО | `mio_head` | Все + подтверждение решений, аналитика |
| Администратор | `admin` | Полный доступ + Django Admin |
| Аудитор | `auditor` | Только просмотр всех данных (read-only) |

## 3. Пайплайн AI-скоринга

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ScoringEngine.run_scoring(application)                │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  1. Загрузка данных субъекта     │
                    │     EmulatedEntity.get(iin_bin)  │
                    │     → JSON из 7 систем           │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
              ┌──────────────────────────────────────────┐
              │  2. ЖЁСТКИЕ ФИЛЬТРЫ (11 бинарных)       │
              │     HardFilterChecker.check_all()         │
              │                                           │
              │  ГИСС регистрация ─────── pass/fail      │
              │  ЭЦП (ЕАСУ) ──────────── pass/fail      │
              │  ИАС РСЖ регистрация ─── pass/fail      │
              │  С/х земля (ЕГКН) ─────── pass/fail      │
              │  ИС ИСЖ регистрация ──── pass/fail      │
              │  ИБСПР регистрация ────── pass/fail      │
              │  ЭСФ подтверждены ─────── pass/fail      │
              │  Нет невыполн. обязат. ── pass/fail      │
              │  Нет блокировки ────────── pass/fail      │
              │  Возраст животных ─────── pass/fail      │
              │  Не субсидированы ──────── pass/fail      │
              └───────────────┬──────────┬───────────────┘
                              │          │
                     all_passed=true   all_passed=false
                              │          │
                              │          ▼
                              │    ┌──────────────┐
                              │    │ ОТКАЗ        │
                              │    │ status=reject│
                              │    │ + причины    │
                              │    └──────────────┘
                              ▼
         ┌────────────────────────────────────────────────┐
         │  3. МЯГКИЕ ФАКТОРЫ (8 взвешенных)              │
         │     SoftFactorCalculator.calculate_all()        │
         │                                                 │
         │  ┌─────────────────────────────┬─────┬──────┐  │
         │  │ Фактор                      │ Макс│  Вес │  │
         │  ├─────────────────────────────┼─────┼──────┤  │
         │  │ 1. История субсидий         │  20 │ 0.20 │  │
         │  │ 2. Рост производства        │  20 │ 0.20 │  │
         │  │ 3. Размер хозяйства         │  15 │ 0.15 │  │
         │  │ 4. Эффективность            │  15 │ 0.15 │  │
         │  │ 5. Соответствие нормативам  │  10 │ 0.10 │  │
         │  │ 6. Региональный приоритет   │  10 │ 0.10 │  │
         │  │ 7. Тип субъекта             │   5 │ 0.05 │  │
         │  │ 8. Первичность заявителя    │   5 │ 0.05 │  │
         │  ├─────────────────────────────┼─────┼──────┤  │
         │  │ ИТОГО                       │ 100 │ 1.00 │  │
         │  └─────────────────────────────┴─────┴──────┘  │
         │                                                 │
         │  rule_score = сумма значений факторов (0-100)   │
         └───────────────────────┬─────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │  4. ML МОДЕЛЬ (Gradient Boosting)              │
         │                                                 │
         │  20 признаков → GradientBoostingRegressor      │
         │                  (200 деревьев, depth=4)        │
         │                                                 │
         │  20 признаков → GradientBoostingClassifier     │
         │                  (150 деревьев, depth=3)        │
         │                                                 │
         │  Выход: ml_score (0-100)                       │
         │         ml_recommendation (approve/review/reject)│
         │         confidence (0-1)                        │
         │         feature_contributions (top-10)          │
         └───────────────────────┬─────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │  5. ГИБРИДНЫЙ БАЛЛ                             │
         │                                                 │
         │  total_score = 0.6 × ml_score + 0.4 × rule_score│
         │                                                 │
         │  Рекомендация:                                  │
         │    ≥ 70 баллов → "approve" (одобрить)          │
         │    ≥ 40 баллов → "review"  (на усмотрение)     │
         │    < 40 баллов → "reject"  (отклонить)         │
         └───────────────────────┬─────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │  6. РЕЗУЛЬТАТ                                   │
         │                                                 │
         │  • Объяснение на русском языке                 │
         │  • Вклад каждого признака (feature importance) │
         │  • Проверка бюджета региона                    │
         │  • Обновление ранга в рейтинге                 │
         │  • Уведомление заявителю                       │
         │                                                 │
         │  approve + бюджет есть  → status = "approved"  │
         │  approve + бюджета нет  → status = "waiting_list"│
         │  review                → status = "checking"    │
         │  reject                → status = "rejected"    │
         └────────────────────────────────────────────────┘
```

## 4. 20 признаков ML модели

| # | Признак | Тип | Источник |
|---|---------|-----|----------|
| 1 | giss_registered | binary | ГИСС |
| 2 | growth_rate | float (%) | ГИСС |
| 3 | gross_production_prev | float (млн ₸) | ГИСС |
| 4 | gross_production_before | float (млн ₸) | ГИСС |
| 5 | obligations_met | binary | ГИСС |
| 6 | total_subsidies_received | float (млн ₸) | ГИСС |
| 7 | ias_registered | binary | ИАС РСЖ |
| 8 | subsidy_history_count | int | ИАС РСЖ |
| 9 | subsidy_success_rate | float (0-1) | ИАС РСЖ |
| 10 | pending_returns | int | ИАС РСЖ |
| 11 | total_verified_animals | int | ИС ИСЖ |
| 12 | total_rejected_animals | int | ИС ИСЖ |
| 13 | animal_age_valid_ratio | float (0-1) | ИС ИСЖ |
| 14 | esf_total_amount | float (млн ₸) | ИС ЭСФ |
| 15 | esf_invoice_count | int | ИС ЭСФ |
| 16 | esf_confirmed_ratio | float (0-1) | ИС ЭСФ |
| 17 | has_agricultural_land | binary | ЕГКН |
| 18 | total_agricultural_area | float (га) | ЕГКН |
| 19 | entity_type_encoded | int (0/1/2) | ЕАСУ |
| 20 | treasury_payment_count | int | Казначейство |

## 5. 7 Информационных систем (интеграции)

```
┌────────────────────────────────────────────────────────────────────┐
│                    EmulatedEntity (JSON хранилище)                  │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │     ГИСС     │  │  ИАС РСЖ    │  │    ЕАСУ      │             │
│  │              │  │              │  │              │             │
│  │ registered   │  │ registered   │  │ has_account  │             │
│  │ growth_rate  │  │ ibspr_reg    │  │   _number    │             │
│  │ production   │  │ subsidy_     │  └──────────────┘             │
│  │ obligations  │  │   history[]  │                                │
│  │ blocked      │  │ pending_     │  ┌──────────────┐             │
│  │ subsidies    │  │   returns    │  │   ИС ИСЖ     │             │
│  └──────────────┘  └──────────────┘  │              │             │
│                                       │ total_verified│             │
│  ┌──────────────┐  ┌──────────────┐  │ total_rejected│             │
│  │   ИС ЭСФ    │  │    ЕГКН      │  │ animals[]    │             │
│  │              │  │              │  │  age_valid   │             │
│  │ total_amount │  │ has_agri_land│  │  subsidized  │             │
│  │ invoice_count│  │ total_area   │  └──────────────┘             │
│  │ invoices[]   │  └──────────────┘                                │
│  │  confirmed   │                     ┌──────────────┐             │
│  └──────────────┘                     │ Казначейство │             │
│                                       │              │             │
│                                       │ payments[]   │             │
│                                       │   status     │             │
│                                       └──────────────┘             │
└────────────────────────────────────────────────────────────────────┘

В хакатон-версии все 7 систем эмулируются через JSON-поля EmulatedEntity.
В продакшене каждая система заменяется реальным API-коннектором.
```

## 6. Структура проекта

```
hackathon-ai/
├── config/                     # Конфигурация Django
│   ├── settings.py             # Настройки (PostgreSQL, Redis, DRF)
│   ├── urls.py                 # Главный роутинг
│   └── wsgi.py                 # WSGI точка входа
│
├── apps/
│   ├── scoring/                # Основное приложение
│   │   ├── models.py           # 12 моделей данных
│   │   ├── views.py            # 20+ views (dashboard, заявки, комиссия)
│   │   ├── urls.py             # 23 маршрута
│   │   ├── scoring_engine.py   # Оркестрация пайплайна скоринга
│   │   ├── hard_filters.py     # 11 бинарных проверок
│   │   ├── soft_factors.py     # 8 взвешенных факторов
│   │   ├── ml_model.py         # Gradient Boosting (train + predict)
│   │   ├── context_processors.py # Роль пользователя в контексте
│   │   └── management/commands/
│   │       ├── seed_data.py        # Справочники + демо-пользователи
│   │       ├── generate_history.py # Генерация из Excel-датасета
│   │       ├── create_test_applications.py # Тестовые заявки + скоринг
│   │       └── train_model.py      # Обучение ML модели
│   │
│   └── emulator/               # Эмулятор 7 госсистем
│       ├── models.py           # EmulatedEntity (JSON)
│       ├── views.py            # REST API эмулятора
│       ├── serializers.py      # DRF сериализаторы
│       └── management/commands/
│           └── generate_data.py # Генерация 500 синтетических сущностей
│
├── templates/                  # Django-шаблоны (16 страниц)
│   ├── base.html               # Базовый layout + навигация
│   ├── index.html              # Лендинг
│   ├── auth/
│   │   └── login.html          # Вход (ЭЦП + пароль)
│   └── scoring/
│       ├── dashboard.html      # Дашборд со статистикой
│       ├── application_list.html    # Список заявок
│       ├── application_detail.html  # Детали + скоринг
│       ├── application_form.html    # Подача заявки (conversational UI)
│       ├── scoring_ranking.html     # AI-рейтинг
│       ├── commission.html          # Заседание комиссии
│       ├── analytics.html           # Аналитика (графики, карта)
│       ├── emulator_panel.html      # Панель эмулятора
│       ├── entity_detail.html       # Данные сущности
│       ├── entity_edit.html         # Редактор данных
│       ├── model_info.html          # Информация о ML модели
│       └── notifications.html       # Уведомления
│
├── docs/                       # Документация
│   └── ARCHITECTURE.md         # Этот документ
├── docker-compose.yml          # Docker Compose (авто-инициализация)
├── docker-compose.prod.yml     # Продакшен конфигурация
├── Dockerfile                  # Python 3.12-slim
├── entrypoint.sh               # Скрипт инициализации
├── requirements.txt            # 14 зависимостей
└── .env.example                # Шаблон переменных окружения
```

## 7. 11 жёстких фильтров (Hard Filters)

| # | Фильтр | Источник | Условие прохождения |
|---|--------|----------|---------------------|
| 1 | Регистрация в ГИСС | ГИСС | `registered == true` |
| 2 | Наличие ЭЦП | ЕАСУ | `has_account_number == true` |
| 3 | Регистрация в ИАС РСЖ | ИАС РСЖ | `registered == true` OR кооператив |
| 4 | Наличие с/х земли | ЕГКН | `has_agricultural_land == true` |
| 5 | Регистрация в ИС ИСЖ | ИС ИСЖ | `total_verified > 0` |
| 6 | Регистрация в ИБСПР | ИАС РСЖ | `ibspr_registered == true` |
| 7 | Подтверждённые ЭСФ | ИС ЭСФ | `invoice_count > 0` AND есть confirmed |
| 8 | Нет невыполненных обязательств | ГИСС | `obligations_met == true` |
| 9 | Нет блокировки | ГИСС + БД | NOT `blocked` AND NOT `is_blocked` |
| 10 | Валидный возраст животных | ИС ИСЖ | все `age_valid == true` |
| 11 | Животные не субсидированы | ИС ИСЖ | все `previously_subsidized == false` |

> Фильтры 10-11 применяются только для животноводческих направлений.

## 8. Маршруты (23 эндпоинта)

| URL | Метод | Роли | Описание |
|-----|-------|------|----------|
| `/` | GET | Все | Лендинг |
| `/auth/login/` | GET/POST | Все | Авторизация (ЭЦП + пароль) |
| `/auth/logout/` | GET | Auth | Выход |
| `/dashboard/` | GET | Auth | Дашборд со статистикой |
| `/applications/` | GET | Auth | Список заявок с фильтрами |
| `/applications/new/` | GET/POST | applicant | Подача заявки |
| `/applications/draft/` | POST | applicant | Сохранение черновика (AJAX) |
| `/applications/<id>/` | GET | Auth | Детали заявки + AI-скоринг |
| `/applications/<id>/decide/` | POST | commission | Решение комиссии |
| `/applications/<id>/payment/` | POST | mio_head | Инициация выплаты |
| `/scoring/` | GET | specialist+ | Рейтинг по AI-баллу |
| `/commission/` | GET | commission | Очередь на рассмотрение |
| `/analytics/` | GET | specialist+ | Аналитические дашборды |
| `/emulator/` | GET | specialist+ | Эмулированные сущности |
| `/emulator/<id>/` | GET | specialist+ | Данные сущности (JSON) |
| `/emulator/<id>/edit/` | GET/POST | specialist+ | Редактор данных |
| `/notifications/` | GET | Auth | Центр уведомлений |
| `/notifications/<id>/read/` | POST | Auth | Пометить прочитанным |
| `/model-info/` | GET | specialist+ | Информация о ML модели |
| `/api/entity-data/<iin>/` | GET | Auth | JSON данных по ИИН/БИН |
| `/api/form-progress/` | POST | applicant | Прогресс формы (AJAX) |
| `/api/docs/` | GET | Все | Swagger UI |

## 9. Инфраструктура

```
┌─────────────────────────────────────────────────────┐
│                  Сервер (Ubuntu)                     │
│                                                      │
│  ┌────────────────────────────────────────────────┐ │
│  │           Nginx (host)                          │ │
│  │  SSL: Let's Encrypt (certbot)                   │ │
│  │  subsidyai.domain.com → localhost:8000          │ │
│  └────────────────────┬───────────────────────────┘ │
│                        │                             │
│  ┌─────────────────────┴──────────────────────────┐ │
│  │           Docker Compose                        │ │
│  │                                                  │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │ │
│  │  │  web     │  │   db     │  │    redis     │ │ │
│  │  │ Gunicorn │  │ Postgres │  │   Redis 7    │ │ │
│  │  │ :8000    │  │  16      │  │   :6379      │ │ │
│  │  └──────────┘  └──────────┘  └──────────────┘ │ │
│  └──────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## 10. Ключевые архитектурные решения

| # | Решение | Обоснование |
|---|---------|------------|
| 1 | Гибридный скоринг 60% ML + 40% правила | ML обеспечивает точность, правила — прозрачность и контроль |
| 2 | Gradient Boosting (scikit-learn) | Лучший баланс точности и интерпретируемости для табличных данных |
| 3 | Explainability в каждом скоринге | Обязательное требование — каждый балл обоснован текстом на русском |
| 4 | 11 жёстких фильтров как gates | Автоматическая проверка нормативных требований до ML-скоринга |
| 5 | Эмулятор 7 госсистем | Позволяет разрабатывать без доступа к реальным API МСХ РК |
| 6 | Redis кеш + сессии | Быстрый дашборд (5 мин кеш) и масштабируемые сессии |
| 7 | Ролевая модель (6 ролей) | Отражает реальную структуру процесса субсидирования |
| 8 | AI помогает, не заменяет | Комиссия принимает финальное решение, AI даёт рекомендацию |
| 9 | Бюджетный контроль | Лист ожидания при исчерпании регионального бюджета |
| 10 | Аудит-трейл | Все решения комиссии логируются: кто, когда, почему |
