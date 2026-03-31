# UI/UX Redesign Plan — Форма подачи заявки

## ТЕКУЩИЙ ПОРЯДОК (неправильный)
1. Категория → 2. Направление → 3. Вид субсидии → 4. Регион → 5. Заявитель (ИИН) → 6. Показатели → 7. Количество → 8. Документы → 9. ЭЦП → 10. Отправка

## НОВЫЙ ПОРЯДОК (по Приказу №108)

### ШАГ 1: Идентификация заявителя
- Пользователь УЖЕ вошёл через ИИН/ЭЦП на login page
- ИИН/БИН берём из `request.user.profile.iin_bin`
- Автоматически загружаем данные из EmulatedEntity
- **Показываем**: ФИО, ИИН/БИН, тип (ИП/ТОО/СПК), регион, район
- **Если СПК**: показать название кооператива и членов из ЕАСУ
- **НЕ редактируемое** — данные из госсистем

### ШАГ 2: Проверка в 7 системах (Hard Filters Preview)
- Отображаем статус по КАЖДОЙ системе:
  - ✅/❌ ГИСС — зарегистрирован, не заблокирован
  - ✅/❌ ИАС РСЖ — учётный номер
  - ✅/❌ ЕАСУ — ЭЦП, учётный номер
  - ✅/❌ ИС ИСЖ — есть верифицированные животные
  - ✅/❌ ИС ЭСФ — есть подтверждённые ЭСФ
  - ✅/❌ ЕГКН — есть с/х земля
  - ✅/❌ Казначейство — история платежей
- Показать общее: "6 из 7 систем — OK" или "3 из 7 — ПРОБЛЕМЫ"
- **Если критичные фильтры не пройдены** (ГИСС не зарег, заблокирован):
  → Показать ОТКАЗ с причинами и рекомендациями
  → Кнопка "Подать заявку" неактивна
- **Если пройдены с замечаниями** → предупреждения, но можно продолжить

### ШАГ 3: Показатели хозяйства
- Статистика из ГИСС: валовая продукция, рост, обязательства
- Животные из ИС ИСЖ: кол-во, породы, статус
- Земля из ЕГКН: участки, площадь
- ЭСФ из ИС ЭСФ: счёт-фактуры, суммы
- История субсидий из ИАС РСЖ
- **Всё нередактируемое** — данные из госсистем, просто для обзора

### ШАГ 4: Выбор субсидии
- Категория (животноводство / растениеводство / оборудование)
- Направление (мясной КРС / молочный КРС / овцы...)
- Вид субсидии (конкретная форма с нормативом)
- Фильтрация по доступным направлениям (на основе данных ИС ИСЖ)

### ШАГ 5: Выбор животных (если животноводство)
- Список животных из ИС ИСЖ
- Фильтры: по возрасту, по статусу субсидирования, по породе
- Checkbox выбор конкретных животных
- **Возрастной фильтр**: показать допустимый/недопустимый возраст
- **Ранее субсидированные**: помечены, нельзя выбрать
- Кросс-валидация: ИСЖ ↔ ИБСПР (если данные расходятся — предупреждение)
- **RFID мониторинг**: показать статус RFID для каждого животного
  - 🟢 Метка активна, последнее сканирование: [дата]
  - 🟡 Метка есть, давно не сканировалось
  - ⚪ Нет RFID метки

### ШАГ 6: Расчёт суммы
- Количество × Ставка = Сумма субсидии
- Проверка: сумма ≤ 50% от стоимости (Приказ №108)
- Поле unit_price для ввода фактической стоимости
- Автоматический расчёт с предупреждениями

### ШАГ 7: Документы
- Базовые (всегда): договор купли-продажи, акт приёма-передачи
- **Импорт**: таможенная декларация, карантинный акт, вет. сертификат
- **Отечественный**: племенное свидетельство (pedigree)
- **СПК**: документ о членстве
- ЭСФ (заблокированные) — показать из ИС ЭСФ
- Выбор земельных участков из ЕГКН

### ШАГ 8: Обзор и подтверждение
- Полный обзор всех данных в табличном виде
- Checkbox: "Подтверждаю достоверность данных"
- Checkbox: "Обязуюсь выполнять встречные обязательства (Приказ №108)"
  → Показать конкретные обязательства:
  - Сохранность поголовья: [срок] с даты подачи
  - Рост/сохранение валовой продукции
  - Регистрация потомства в ИБСПР и ИСЖ

### ШАГ 9: Подписание ЭЦП и отправка
- Анимация подписания (NCALayer эмуляция)
- Подача в региональное управление с/х
- Получение номера заявки
- Позиция в очереди
- Срок рассмотрения: 2 рабочих дня

---

## ALPINE.JS STATE

```javascript
{
  // Step control
  currentStep: 1,
  maxStep: 9,

  // Step 1: Auto from login
  iinBin: '{{ user_iin }}',
  applicantName: '{{ user_name }}',
  entityType: '',
  region: '',
  district: '',
  phone: '',
  bankAccount: '',

  // Entity data (from API)
  entityFound: false,
  entityData: {},

  // Step 2: System checks
  systemChecks: {
    giss: { status: null, label: 'ГИСС', details: {} },
    ias_rszh: { status: null, label: 'ИАС РСЖ', details: {} },
    easu: { status: null, label: 'ЕАСУ', details: {} },
    is_iszh: { status: null, label: 'ИС ИСЖ', details: {} },
    is_esf: { status: null, label: 'ИС ЭСФ', details: {} },
    egkn: { status: null, label: 'ЕГКН', details: {} },
    treasury: { status: null, label: 'Казначейство', details: {} },
  },
  hardFiltersPassed: false,
  failedReasons: [],

  // Step 3: Farm indicators (read-only from entity)
  farm: {
    grossProdPrev: 0,
    grossProdBefore: 0,
    growthRate: 0,
    obligationsMet: true,
    totalSubsidiesReceived: 0,
    landArea: 0,
    verifiedAnimals: 0,
    subsidyCount: 0,
    subsidySuccessRate: 0,
  },

  // Step 4: Subsidy selection
  category: '',
  direction: '',
  subsidyType: null,
  selectedRate: 0,

  // Step 5: Animals
  allAnimals: [],
  selectedAnimals: [],
  filterByAge: true,
  filterBySubsidized: true,

  // RFID
  rfidAnimals: [],  // Animals with RFID data

  // Step 6: Calculation
  quantity: 0,
  unitPrice: 0,
  totalAmount: 0,

  // Step 7: Documents
  documents: [],
  requiredDocs: [],

  // Step 8: Confirmation
  confirmedData: false,
  confirmedObligations: false,

  // Step 9: ECP
  ecpSigned: false,
  submitting: false,
  applicationNumber: '',
  queuePosition: 0,
}
```

---

## API ENDPOINTS NEEDED

### Existing (keep):
- `GET /api/entity-data/?iin_bin=...` — fetch entity from emulator

### Modify:
- Return system check results in response
- Return RFID data for animals (new field)

### New:
- `GET /api/hard-filter-preview/?iin_bin=...` — run hard filters without creating application
- `GET /api/rfid-status/?iin_bin=...` — get RFID monitoring data for animals

---

## VIEW CHANGES

### `application_create` view:
- Auto-fill applicant data from `request.user.profile`
- Pass pre-loaded entity data to template context
- Run hard filter preview before allowing submission

### `api_entity_data` view:
- Add system check results
- Add RFID monitoring data
- Add hard filter preview results

---

## MODEL CHANGES

### New model: `RFIDMonitoring`
```python
class RFIDMonitoring(models.Model):
    entity = ForeignKey(EmulatedEntity)
    animal_tag = CharField(max_length=50)
    rfid_tag = CharField(max_length=100)
    last_scan_date = DateTimeField()
    scan_location = CharField(max_length=200)
    status = CharField(choices=[
        ('active', 'Активна'),
        ('inactive', 'Неактивна'),
        ('missing', 'Не найдена'),
    ])
    scan_count_30d = IntegerField(default=0)
```

### EmulatedEntity: Add RFID data to `is_iszh_data`
```json
{
  "animals": [
    {
      "tag_number": "KZ001234",
      "rfid_tag": "RFID-0001234",
      "rfid_active": true,
      "rfid_last_scan": "2026-03-28T10:30:00",
      "rfid_scan_count_30d": 45
    }
  ]
}
```

---

## IMPLEMENTATION ORDER

1. Create UI_REDESIGN_PLAN.md ✅ (this file)
2. Create new application_form_v2.html template
3. Update views.py — api_entity_data to include system checks
4. Add hard filter preview endpoint
5. Add RFID model and data
6. Update create_demo_users to include RFID data
7. Test all flows
8. Deploy to production

---

## DESIGN PRINCIPLES

- Dark theme header (#1A1A2E) with lime accents (#C1FF00)
- Each system check = card with status icon
- Progressive disclosure: complete step → collapse → show summary
- Mobile responsive (2-col → 1-col)
- Animation on step transitions
- Clear error states with action recommendations
