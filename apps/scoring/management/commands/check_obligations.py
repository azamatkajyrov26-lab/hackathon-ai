"""
Управляющая команда: проверка встречных обязательств (Приказ №108).

Сканирует всех заявителей с суммой субсидий >100 млн тенге,
проверяет динамику валовой продукции по данным ГИСС.
Автоматически блокирует при снижении 2 года подряд:
  - 1 год при первом нарушении
  - 2 года при повторном

Использование:
    python manage.py check_obligations
    python manage.py check_obligations --dry-run
"""

import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.emulator.models import EmulatedEntity
from apps.scoring.models import Applicant, Notification

logger = logging.getLogger(__name__)

SUBSIDY_THRESHOLD = 100_000_000  # 100 млн тенге


class Command(BaseCommand):
    help = 'Проверка встречных обязательств по Приказу №108 и автоблокировка'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать результаты без применения блокировок',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = date.today()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Проверка встречных обязательств — {today}'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING('Режим dry-run: изменения НЕ будут сохранены'))

        # Снимаем истекшие блокировки
        expired = Applicant.objects.filter(
            is_blocked=True,
            block_until__lte=today,
        )
        expired_count = expired.count()
        if expired_count and not dry_run:
            expired.update(is_blocked=False)
        self.stdout.write(f'Истекших блокировок снято: {expired_count}')

        # Загружаем всех заявителей с данными из ГИСС
        entities = EmulatedEntity.objects.all()
        checked = 0
        blocked = 0
        skipped = 0

        for entity in entities:
            giss = entity.giss_data or {}
            total_subsidies = giss.get('total_subsidies_received', 0)

            # Порог субсидий
            if total_subsidies <= SUBSIDY_THRESHOLD:
                continue

            checked += 1

            # Находим заявителя
            try:
                applicant = Applicant.objects.get(iin_bin=entity.iin_bin)
            except Applicant.DoesNotExist:
                continue

            # Уже заблокирован и блокировка не истекла
            if applicant.is_blocked and applicant.block_until and applicant.block_until > today:
                skipped += 1
                continue

            # Проверяем снижение валовой продукции
            prod_prev = giss.get('gross_production_previous_year', 0)
            prod_before = giss.get('gross_production_year_before', 0)
            growth_rate = giss.get('growth_rate', 0)
            obligations_met = giss.get('obligations_met', True)

            # Условия блокировки: отрицательный рост + продукция снижается + обязательства не выполнены
            if growth_rate >= 0 or prod_prev >= prod_before or obligations_met:
                continue

            # Определяем срок
            had_previous_block = bool(applicant.block_reason)
            block_years = 2 if had_previous_block else 1
            reason = (
                f'{"Повторное н" if had_previous_block else "Н"}'
                f'евыполнение встречных обязательств по субсидиям '
                f'(снижение валовой продукции 2 года подряд, '
                f'рост {growth_rate}%, субсидий {total_subsidies:,.0f} тг). '
                f'Блокировка на {block_years} год(а) согласно Приказу №108.'
            )

            self.stdout.write(
                f'  {applicant.iin_bin} {applicant.name}: '
                f'рост={growth_rate}%, субсидии={total_subsidies:,.0f} тг '
                f'-> блокировка {block_years} год(а)'
            )

            if not dry_run:
                applicant.is_blocked = True
                applicant.block_reason = reason
                applicant.block_until = today + timedelta(days=365 * block_years)
                applicant.save(update_fields=['is_blocked', 'block_reason', 'block_until'])

                # Уведомление (если есть привязанный пользователь)
                from apps.scoring.models import UserProfile
                profile = UserProfile.objects.filter(
                    iin_bin=applicant.iin_bin,
                    role='applicant',
                ).select_related('user').first()
                if profile:
                    Notification.objects.create(
                        user=profile.user,
                        notification_type='rejected',
                        title=f'Блокировка: {applicant.name}',
                        message=reason,
                    )

            blocked += 1

        self.stdout.write('')
        self.stdout.write(f'Проверено (>100 млн тг): {checked}')
        self.stdout.write(f'Уже заблокированы: {skipped}')
        self.stdout.write(
            self.style.SUCCESS(f'Заблокировано: {blocked}')
            if blocked
            else f'Заблокировано: 0'
        )

        if dry_run and blocked:
            self.stdout.write(self.style.WARNING(
                f'dry-run: {blocked} заявителей были бы заблокированы'
            ))

        logger.info(
            'check_obligations: checked=%d, blocked=%d, skipped=%d, dry_run=%s',
            checked, blocked, skipped, dry_run,
        )
