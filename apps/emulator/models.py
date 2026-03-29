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
