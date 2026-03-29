"""
Create test applications from EmulatedEntity data and run scoring on them.
"""
import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.emulator.models import EmulatedEntity
from apps.scoring.models import (
    Applicant, Application, SubsidyType, SubsidyDirection,
)


class Command(BaseCommand):
    help = 'Create test applications from emulated entities and run scoring'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=200, help='Number of applications')
        parser.add_argument('--clear', action='store_true', help='Clear existing applications')

    def handle(self, *args, **options):
        count = options['count']

        if options['clear']:
            Application.objects.all().delete()
            Applicant.objects.all().delete()
            self.stdout.write('Cleared existing applications')

        entities = list(EmulatedEntity.objects.all()[:count * 2])
        if not entities:
            self.stdout.write(self.style.ERROR('No emulated entities. Run: python manage.py generate_data'))
            return

        subsidy_types = list(SubsidyType.objects.filter(is_active=True))
        if not subsidy_types:
            self.stdout.write(self.style.ERROR('No subsidy types. Run: python manage.py seed_data'))
            return

        statuses = ['submitted'] * 40 + ['approved'] * 25 + ['paid'] * 15 + ['rejected'] * 10 + ['waiting_list'] * 10

        created = 0
        for i in range(min(count, len(entities))):
            entity = entities[i]

            # Create or get applicant
            applicant, _ = Applicant.objects.get_or_create(
                iin_bin=entity.iin_bin,
                defaults={
                    'name': entity.name,
                    'entity_type': entity.entity_type,
                    'region': entity.region,
                    'district': entity.district,
                    'phone': f'+7 (7{random.randint(00,99):02d}) {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}',
                    'email': f'{entity.iin_bin}@mail.kz',
                    'bank_account': f'KZ{random.randint(10**17, 10**18 - 1)}',
                    'bank_name': random.choice(['АО "Халык Банк"', 'АО "Каспи Банк"', 'АО "Народный Банк"', 'АО "Сбербанк"']),
                    'registration_date': entity.registration_date,
                    'is_blocked': entity.giss_data.get('blocked', False),
                },
            )

            stype = random.choice(subsidy_types)
            quantity = random.randint(5, 100)
            rate = stype.rate
            total = quantity * rate
            status = random.choice(statuses)

            # Animals data from emulator
            animals_data = entity.is_iszh_data.get('animals', [])[:quantity]

            esf_data = entity.is_esf_data.get('invoices', [{}])
            esf = esf_data[0] if esf_data else {}

            submitted = timezone.now() - timedelta(days=random.randint(1, 300))

            number = f'{random.randint(10, 99)}{random.randint(100, 999)}{random.randint(100, 999)}{random.randint(100000, 999999)}'

            app = Application.objects.create(
                number=number,
                applicant=applicant,
                subsidy_type=stype,
                status=status,
                quantity=quantity,
                unit_price=float(rate) * random.uniform(1.0, 1.5),
                rate=rate,
                total_amount=total,
                submitted_at=submitted,
                region=entity.region,
                district=entity.district,
                akimat=f'ГУ "Управление сельского хозяйства {entity.region}"',
                animals_data=animals_data,
                esf_number=esf.get('esf_number', ''),
                esf_amount=esf.get('total_amount', 0),
                counterparty_bin=esf.get('seller_bin', ''),
                counterparty_name=esf.get('seller_name', ''),
            )
            created += 1

            if created % 50 == 0:
                self.stdout.write(f'  Created {created}/{count} applications...')

        self.stdout.write(self.style.SUCCESS(f'Created {created} applications'))

        # Run scoring
        self.stdout.write('Running scoring...')
        try:
            from apps.scoring.scoring_engine import ScoringEngine
            engine = ScoringEngine()
            scored = 0
            for app in Application.objects.all():
                try:
                    engine.run_scoring(app)
                    scored += 1
                except Exception as e:
                    pass  # Skip errors for individual apps
                if scored % 50 == 0 and scored > 0:
                    self.stdout.write(f'  Scored {scored} applications...')

            self.stdout.write(self.style.SUCCESS(f'Scored {scored} applications'))
        except ImportError:
            self.stdout.write(self.style.WARNING('Scoring engine not found, skipping scoring'))
