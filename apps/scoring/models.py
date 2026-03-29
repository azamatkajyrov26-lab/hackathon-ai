from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('applicant', 'Заявитель'),
        ('mio_specialist', 'Специалист МИО'),
        ('commission_member', 'Член комиссии'),
        ('mio_head', 'Руководитель МИО'),
        ('admin', 'Администратор'),
        ('auditor', 'Аудитор'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField('Роль', max_length=30, choices=ROLE_CHOICES, default='applicant')
    iin_bin = models.CharField('ИИН/БИН', max_length=12, blank=True, db_index=True)
    region = models.CharField('Область', max_length=200, blank=True)
    district = models.CharField('Район', max_length=200, blank=True)
    organization = models.CharField('Организация', max_length=500, blank=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)

    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'

    def __str__(self):
        return f'{self.user.get_full_name()} ({self.get_role_display()})'


class Applicant(models.Model):
    ENTITY_CHOICES = [
        ('individual', 'Физическое лицо'),
        ('legal', 'Юридическое лицо'),
        ('cooperative', 'С/х кооператив (СПК)'),
    ]

    iin_bin = models.CharField('ИИН/БИН', max_length=12, unique=True, db_index=True)
    name = models.CharField('Наименование', max_length=500)
    entity_type = models.CharField('Тип', max_length=20, choices=ENTITY_CHOICES)
    region = models.CharField('Область', max_length=200)
    district = models.CharField('Район', max_length=200)
    address = models.TextField('Адрес', blank=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    email = models.EmailField('Email', blank=True)
    bank_account = models.CharField('IBAN', max_length=34, blank=True)
    bank_name = models.CharField('Банк', max_length=200, blank=True)
    registration_date = models.DateField('Дата регистрации')
    is_blocked = models.BooleanField('Заблокирован', default=False)
    block_reason = models.TextField('Причина блокировки', blank=True)
    block_until = models.DateField('Блокировка до', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Заявитель'
        verbose_name_plural = 'Заявители'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.iin_bin})'


class SubsidyDirection(models.Model):
    code = models.CharField('Код', max_length=30, unique=True)
    name = models.CharField('Название', max_length=500)
    description = models.TextField('Описание', blank=True)
    is_active = models.BooleanField('Активно', default=True)

    class Meta:
        verbose_name = 'Направление субсидирования'
        verbose_name_plural = 'Направления субсидирования'

    def __str__(self):
        return self.name


class SubsidyType(models.Model):
    ORIGIN_CHOICES = [
        ('domestic', 'Отечественный'),
        ('cis', 'Импорт СНГ'),
        ('import', 'Импорт дальнее зарубежье'),
        ('na', 'Не применимо'),
    ]

    direction = models.ForeignKey(SubsidyDirection, on_delete=models.CASCADE, related_name='types')
    form_number = models.IntegerField('Номер формы')
    name = models.CharField('Название', max_length=500)
    unit = models.CharField('Единица измерения', max_length=50)
    rate = models.DecimalField('Норматив (тг)', max_digits=12, decimal_places=2)
    origin = models.CharField('Происхождение', max_length=20, choices=ORIGIN_CHOICES, default='na')
    min_age_months = models.IntegerField('Мин. возраст (мес.)', null=True, blank=True)
    max_age_months = models.IntegerField('Макс. возраст (мес.)', null=True, blank=True)
    min_herd_size = models.IntegerField('Мин. поголовье', null=True, blank=True)
    requires_commission = models.BooleanField('Требует заключения комиссии', default=False)
    is_active = models.BooleanField('Активен', default=True)

    class Meta:
        verbose_name = 'Вид субсидии'
        verbose_name_plural = 'Виды субсидий'

    def __str__(self):
        return f'{self.name} ({self.rate} тг/{self.unit})'


class Application(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('submitted', 'Подана'),
        ('checking', 'На проверке'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отказ'),
        ('waiting_list', 'Лист ожидания'),
        ('partially_paid', 'Частично выплачена'),
        ('paid', 'Выплачена'),
    ]

    number = models.CharField('Номер заявки', max_length=20, unique=True, db_index=True)
    applicant = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name='applications')
    subsidy_type = models.ForeignKey(SubsidyType, on_delete=models.CASCADE, related_name='applications')
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
    quantity = models.IntegerField('Количество')
    unit_price = models.DecimalField('Цена за единицу', max_digits=12, decimal_places=2, default=0)
    rate = models.DecimalField('Норматив', max_digits=12, decimal_places=2)
    total_amount = models.DecimalField('Причитающаяся сумма', max_digits=15, decimal_places=2)
    submitted_at = models.DateTimeField('Дата подачи', null=True, blank=True, db_index=True)
    region = models.CharField('Область', max_length=200, db_index=True)
    district = models.CharField('Район', max_length=200)
    akimat = models.CharField('Акимат', max_length=500, blank=True)
    animals_data = models.JSONField('Данные о животных', default=list, blank=True)
    plots_data = models.JSONField('Данные о земельных участках', default=list, blank=True)
    invoices_data = models.JSONField('Данные о ЭСФ', default=list, blank=True)
    esf_number = models.CharField('Номер ЭСФ', max_length=50, blank=True)
    esf_amount = models.DecimalField('Сумма ЭСФ', max_digits=15, decimal_places=2, null=True, blank=True)
    counterparty_bin = models.CharField('БИН продавца', max_length=12, blank=True)
    counterparty_name = models.CharField('Продавец', max_length=500, blank=True)
    land_cadastral = models.CharField('Кадастровый номер', max_length=50, blank=True)
    bank_account = models.CharField('Банковский счёт', max_length=50, blank=True)
    ecp_signed = models.BooleanField('Подписано ЭЦП', default=False)
    ecp_signed_at = models.DateTimeField('Дата подписи ЭЦП', null=True, blank=True)
    spk_name = models.CharField('Название СПК', max_length=500, blank=True)
    notes = models.TextField('Примечания', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'Заявка {self.number} — {self.applicant.name}'


class ApplicationDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ('contract', 'Договор купли-продажи'),
        ('esf', 'ЭСФ'),
        ('customs_declaration', 'Таможенная декларация'),
        ('quarantine_act', 'Акт карантинирования'),
        ('commission_conclusion', 'Заключение спецкомиссии'),
        ('spk_membership', 'Членство в СПК'),
        ('payment_confirmation', 'Подтверждение оплаты'),
        ('veterinary_certificate', 'Ветеринарный сертификат'),
        ('pedigree_certificate', 'Племенное свидетельство'),
        ('weighing_act', 'Акт взвешивания'),
        ('bonitation_act', 'Акт бонитировки'),
        ('other', 'Прочее'),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='documents')
    doc_type = models.CharField('Тип', max_length=30, choices=DOC_TYPE_CHOICES)
    name = models.CharField('Название', max_length=500)
    file = models.FileField('Файл', upload_to='documents/%Y/%m/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField('Проверен', default=False)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Документ'
        verbose_name_plural = 'Документы'

    def __str__(self):
        return f'{self.get_doc_type_display()} — {self.application.number}'


class HardFilterResult(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='hard_filter_result')
    giss_registered = models.BooleanField('ГИСС', default=False)
    has_eds = models.BooleanField('ЭЦП', default=False)
    ias_rszh_registered = models.BooleanField('ИАС РСЖ', default=False)
    has_agricultural_land = models.BooleanField('Земля ЕГКН', default=False)
    is_iszh_registered = models.BooleanField('ИС ИСЖ', default=False)
    ibspr_registered = models.BooleanField('ИБСПР', default=False)
    esf_confirmed = models.BooleanField('ЭСФ', default=False)
    no_unfulfilled_obligations = models.BooleanField('Обязательства', default=False)
    no_block = models.BooleanField('Нет блокировки', default=False)
    animals_age_valid = models.BooleanField('Возраст', default=False)
    animals_not_subsidized = models.BooleanField('Не субсидировались', default=False)
    all_passed = models.BooleanField('Все пройдены', default=False)
    failed_reasons = models.JSONField('Причины отказа', default=list)
    checked_at = models.DateTimeField(auto_now_add=True)
    raw_responses = models.JSONField('Сырые ответы', default=dict)

    class Meta:
        verbose_name = 'Результат Hard Filters'
        verbose_name_plural = 'Результаты Hard Filters'

    def __str__(self):
        status = 'PASS' if self.all_passed else 'FAIL'
        return f'{self.application.number} — {status}'


class Score(models.Model):
    RECOMMENDATION_CHOICES = [
        ('approve', 'Одобрить'),
        ('review', 'На усмотрение'),
        ('reject', 'Отклонить'),
    ]

    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='score')
    total_score = models.DecimalField('Балл', max_digits=5, decimal_places=2)
    rank = models.IntegerField('Позиция в рейтинге', null=True, blank=True)
    recommendation = models.CharField('Рекомендация', max_length=10, choices=RECOMMENDATION_CHOICES)
    recommendation_reason = models.TextField('Обоснование')
    calculated_at = models.DateTimeField(auto_now_add=True)
    model_version = models.CharField('Версия модели', max_length=20, default='1.0')

    class Meta:
        verbose_name = 'Скоринг'
        verbose_name_plural = 'Скоринг'
        ordering = ['-total_score']

    def __str__(self):
        return f'{self.application.number} — {self.total_score} баллов'


class ScoreFactor(models.Model):
    score = models.ForeignKey(Score, on_delete=models.CASCADE, related_name='factors')
    factor_code = models.CharField('Код фактора', max_length=30)
    factor_name = models.CharField('Название', max_length=200)
    value = models.DecimalField('Значение', max_digits=5, decimal_places=2)
    max_value = models.DecimalField('Максимум', max_digits=5, decimal_places=2)
    weight = models.DecimalField('Вес', max_digits=3, decimal_places=2)
    weighted_value = models.DecimalField('Взвешенное', max_digits=5, decimal_places=2)
    explanation = models.TextField('Объяснение')
    data_source = models.CharField('Источник', max_length=30)
    raw_data = models.JSONField('Исходные данные', default=dict, blank=True)

    class Meta:
        verbose_name = 'Фактор скоринга'
        verbose_name_plural = 'Факторы скоринга'
        ordering = ['-weighted_value']

    def __str__(self):
        return f'{self.factor_name}: {self.value}/{self.max_value}'


class Decision(models.Model):
    DECISION_CHOICES = [
        ('approved', 'Одобрено'),
        ('rejected', 'Отказ'),
        ('review', 'Доп. проверка'),
        ('partially_approved', 'Частично одобрено'),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='decisions')
    decision = models.CharField('Решение', max_length=20, choices=DECISION_CHOICES)
    decided_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='decisions')
    reason = models.TextField('Обоснование')
    rejection_grounds = models.JSONField('Основания отказа', default=list, blank=True)
    approved_amount = models.DecimalField('Одобренная сумма', max_digits=15, decimal_places=2, null=True, blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_decisions')
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Решение'
        verbose_name_plural = 'Решения'
        ordering = ['-decided_at']

    def __str__(self):
        return f'{self.application.number} — {self.get_decision_display()}'


class Budget(models.Model):
    year = models.IntegerField('Год')
    region = models.CharField('Область', max_length=200)
    direction = models.ForeignKey(SubsidyDirection, on_delete=models.CASCADE, related_name='budgets')
    planned_amount = models.DecimalField('План', max_digits=15, decimal_places=2)
    spent_amount = models.DecimalField('Факт', max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Бюджет'
        verbose_name_plural = 'Бюджеты'
        unique_together = ['year', 'region', 'direction']

    @property
    def remaining_amount(self):
        return self.planned_amount - self.spent_amount

    def __str__(self):
        return f'{self.region} — {self.direction.name} — {self.year}'


class Notification(models.Model):
    TYPE_CHOICES = [
        ('submitted', 'Заявка принята'),
        ('hard_filter_fail', 'Проверки не пройдены'),
        ('scored', 'Скоринг завершён'),
        ('approved', 'Заявка одобрена'),
        ('rejected', 'Заявка отклонена'),
        ('waiting_list', 'Лист ожидания'),
        ('payment_initiated', 'Платёж инициирован'),
        ('paid', 'Выплата произведена'),
        ('review', 'Доп. проверка'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    notification_type = models.CharField('Тип', max_length=30, choices=TYPE_CHOICES)
    title = models.CharField('Заголовок', max_length=300)
    message = models.TextField('Сообщение')
    is_read = models.BooleanField('Прочитано', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} → {self.user.get_full_name()}'


class Payment(models.Model):
    STATUS_CHOICES = [
        ('initiated', 'Инициирован'),
        ('sent_to_treasury', 'Отправлен в Казначейство'),
        ('processing', 'В обработке'),
        ('completed', 'Выплачен'),
        ('failed', 'Ошибка'),
    ]

    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='payment')
    amount = models.DecimalField('Сумма', max_digits=15, decimal_places=2)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='initiated')
    treasury_ref = models.CharField('Номер Казначейства', max_length=50, blank=True)
    initiated_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField('Отправлен', null=True, blank=True)
    completed_at = models.DateTimeField('Выплачен', null=True, blank=True)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'

    def __str__(self):
        return f'Платёж {self.application.number} — {self.get_status_display()}'
