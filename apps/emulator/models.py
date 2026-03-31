from django.db import models


class EmulatedEntity(models.Model):
    ENTITY_CHOICES = [
        ('individual', 'Физическое лицо'),
        ('legal', 'Юридическое лицо'),
        ('cooperative', 'С/х кооператив (СПК)'),
    ]
    RISK_CHOICES = [
        ('clean', 'Чистый (70%)'),
        ('minor_issues', 'Мелкие проблемы (15%)'),
        ('risky', 'Рисковый (10%)'),
        ('fraudulent', 'Подозрительный (5%)'),
    ]

    iin_bin = models.CharField('ИИН/БИН', max_length=12, unique=True, db_index=True)
    name = models.CharField('Наименование', max_length=500)
    entity_type = models.CharField('Тип', max_length=20, choices=ENTITY_CHOICES)
    region = models.CharField('Область', max_length=200)
    district = models.CharField('Район', max_length=200)
    registration_date = models.DateField('Дата регистрации')
    risk_profile = models.CharField('Профиль риска', max_length=20, choices=RISK_CHOICES, default='clean')
    giss_data = models.JSONField('ГИСС', default=dict)
    ias_rszh_data = models.JSONField('ИАС РСЖ', default=dict)
    easu_data = models.JSONField('ЕАСУ', default=dict)
    is_iszh_data = models.JSONField('ИС ИСЖ', default=dict)
    is_esf_data = models.JSONField('ИС ЭСФ', default=dict)
    egkn_data = models.JSONField('ЕГКН', default=dict)
    treasury_data = models.JSONField('Казначейство', default=dict)
    source_row = models.IntegerField('Строка Excel', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Эмулированная сущность'
        verbose_name_plural = 'Эмулированные сущности'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.iin_bin}) [{self.risk_profile}]'


class RFIDMonitoring(models.Model):
    """RFID-мониторинг сохранности животных на ферме."""
    STATUS_CHOICES = [
        ('active', 'Активна'),
        ('inactive', 'Неактивна — давно не считывалась'),
        ('missing', 'Не найдена'),
    ]

    entity = models.ForeignKey(EmulatedEntity, on_delete=models.CASCADE, related_name='rfid_records')
    animal_tag = models.CharField('Бирка животного', max_length=50, db_index=True)
    rfid_tag = models.CharField('RFID-метка', max_length=100)
    last_scan_date = models.DateTimeField('Последнее считывание')
    scan_location = models.CharField('Место считывания', max_length=200)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='active')
    scan_count_30d = models.IntegerField('Считываний за 30 дней', default=0)
    animal_type = models.CharField('Вид животного', max_length=50, blank=True)
    reader_type = models.CharField('Тип считывателя', max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'RFID-мониторинг'
        verbose_name_plural = 'RFID-мониторинг'
        ordering = ['-last_scan_date']
        unique_together = [('entity', 'animal_tag')]

    def __str__(self):
        return f'RFID {self.rfid_tag} → {self.animal_tag} ({self.get_status_display()})'
