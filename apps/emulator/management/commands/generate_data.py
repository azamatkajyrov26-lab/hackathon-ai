"""
Generate synthetic EmulatedEntity data from Excel + random generation.
Creates entities with realistic data for all 7 external system APIs.
"""
import random
from datetime import date, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from faker import Faker

from apps.emulator.models import EmulatedEntity
from apps.scoring.models import SubsidyDirection

fake = Faker('ru_RU')

REGIONS_DISTRICTS = {
    'Акмолинская область': ['Целиноградский район', 'Бурабайский район', 'Аршалинский район', 'Ерейментауский район'],
    'Алматинская область': ['Алматинский район', 'Енбекшиказахский район', 'Талгарский район', 'Карасайский район'],
    'Костанайская область': ['Костанайский район', 'Житикаринский район', 'Рудненский район', 'Наурзумский район'],
    'Туркестанская область': ['Сайрамский район', 'Ордабасынский район', 'Шымкентский район', 'Отрарский район'],
    'Карагандинская область': ['Бухар-Жырауский район', 'Нуринский район', 'Осакаровский район'],
    'область Абай': ['Жарминский район', 'Аягозский район', 'Семейский район'],
    'Павлодарская область': ['Павлодарский район', 'Экибастузский район', 'Баянаульский район'],
    'Северо-Казахстанская область': ['Петропавловский район', 'Аккайынский район', 'Кызылжарский район'],
    'Восточно-Казахстанская область': ['Усть-Каменогорский район', 'Шемонаихинский район', 'Зыряновский район'],
    'Актюбинская область': ['Мугалжарский район', 'Хромтауский район', 'Алгинский район'],
    'Западно-Казахстанская область': ['Бурлинский район', 'Теректинский район'],
    'Жамбылская область': ['Жамбылский район', 'Кордайский район', 'Байзакский район'],
    'Атырауская область': ['Жылыойский район', 'Макатский район'],
    'Кызылординская область': ['Кызылординский район', 'Аральский район'],
    'Мангистауская область': ['Мунайлинский район', 'Каракиянский район'],
    'область Жетісу': ['Аксуский район', 'Панфиловский район'],
    'область Ұлытау': ['Жанааркинский район', 'Улытауский район'],
}

BREEDS_CATTLE = ['Ангусская', 'Герефордская', 'Казахская белоголовая', 'Шароле', 'Лимузинская', 'Голштинская', 'Симментальская']
BREEDS_SHEEP = ['Эдильбаевская', 'Казахская тонкорунная', 'Каракульская', 'Меринос', 'Гиссарская']
BREEDS_HORSE = ['Казахская', 'Кустанайская', 'Мугалжарская', 'Донская']

FARM_PREFIXES_LEGAL = ['ТОО', 'КХ', 'ТОО']
FARM_NAMES = [
    'Агрофирма', 'Байтерек', 'Дала', 'Жулдыз', 'Нур', 'Степь', 'Асыл', 'Тулпар',
    'Береке', 'Достык', 'Шанырак', 'Жайлау', 'Кокше', 'Арман', 'Мерей', 'Алтын',
    'Саулет', 'Тулпар', 'Кенже', 'Акбота', 'Самал', 'Отрар', 'Сарыарка', 'Табиғат',
]


def generate_iin():
    """Generate a realistic Kazakh IIN (12 digits)."""
    year = random.randint(60, 99)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    rest = random.randint(100000, 999999)
    return f'{year:02d}{month:02d}{day:02d}{rest}'


def generate_bin():
    """Generate a realistic Kazakh BIN (12 digits)."""
    year = random.randint(10, 25)
    month = random.randint(1, 12)
    rest = random.randint(10000000, 99999999)
    return f'{year:02d}{month:02d}{rest}'


class Command(BaseCommand):
    help = 'Generate synthetic emulated entities with data for 7 external systems'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=500, help='Number of entities to generate')
        parser.add_argument('--clear', action='store_true', help='Clear existing data first')

    def handle(self, *args, **options):
        count = options['count']

        if options['clear']:
            deleted = EmulatedEntity.objects.all().delete()
            self.stdout.write(f'Cleared {deleted[0]} entities')

        existing = set(EmulatedEntity.objects.values_list('iin_bin', flat=True))

        # Risk profile distribution
        profiles = (
            ['clean'] * 70 +
            ['minor_issues'] * 15 +
            ['risky'] * 10 +
            ['fraudulent'] * 5
        )

        created = 0
        for i in range(count):
            risk = random.choice(profiles)
            region = random.choice(list(REGIONS_DISTRICTS.keys()))
            district = random.choice(REGIONS_DISTRICTS[region])

            # Entity type
            entity_roll = random.random()
            if entity_roll < 0.6:
                entity_type = 'legal'
                iin_bin = generate_bin()
                name = f"{random.choice(FARM_PREFIXES_LEGAL)} \"{random.choice(FARM_NAMES)} {fake.city_name()}\""
            elif entity_roll < 0.9:
                entity_type = 'individual'
                iin_bin = generate_iin()
                name = f"ИП {fake.last_name()} {fake.first_name()[0]}."
            else:
                entity_type = 'cooperative'
                iin_bin = generate_bin()
                name = f"СПК \"{random.choice(FARM_NAMES)}\""

            if iin_bin in existing:
                continue
            existing.add(iin_bin)

            reg_date = date(random.randint(2015, 2023), random.randint(1, 12), random.randint(1, 28))

            entity = EmulatedEntity(
                iin_bin=iin_bin,
                name=name,
                entity_type=entity_type,
                region=region,
                district=district,
                registration_date=reg_date,
                risk_profile=risk,
                giss_data=self._gen_giss(risk),
                ias_rszh_data=self._gen_ias_rszh(risk, reg_date, region, district, name, entity_type),
                easu_data=self._gen_easu(entity_type, name),
                is_iszh_data=self._gen_is_iszh(risk, iin_bin),
                is_esf_data=self._gen_is_esf(risk, iin_bin),
                egkn_data=self._gen_egkn(risk, region, district),
                treasury_data=self._gen_treasury(risk),
            )
            entity.save()
            created += 1

            if created % 100 == 0:
                self.stdout.write(f'  Created {created}/{count}...')

        self.stdout.write(self.style.SUCCESS(f'Generated {created} entities'))

    def _gen_giss(self, risk):
        prev = random.randint(5_000_000, 200_000_000)
        if risk == 'clean':
            growth = random.uniform(2, 20)
        elif risk == 'minor_issues':
            growth = random.uniform(-3, 10)
        elif risk == 'risky':
            growth = random.uniform(-15, 3)
        else:
            growth = random.uniform(-25, -5)

        before = int(prev / (1 + growth / 100))
        total_subs = random.randint(0, 200_000_000)

        return {
            'registered': risk != 'fraudulent' or random.random() > 0.3,
            'gross_production_previous_year': prev,
            'gross_production_year_before': before,
            'growth_rate': round(growth, 2),
            'obligations_met': risk in ('clean', 'minor_issues'),
            'total_subsidies_received': total_subs,
            'obligations_required': total_subs >= 100_000_000,
            'blocked': risk == 'fraudulent' and random.random() > 0.5,
            'block_reason': 'Невыполнение встречных обязательств 2 года подряд' if risk == 'fraudulent' else None,
        }

    def _gen_ias_rszh(self, risk, reg_date, region, district, name, entity_type):
        history_count = random.randint(0, 5) if risk != 'fraudulent' else random.randint(3, 8)
        history = []
        types = [
            'Приобретение маточного поголовья КРС',
            'Приобретение племенных овец',
            'Удешевление производства молока',
            'Удешевление стоимости шерсти',
            'Селекционная работа с лошадьми',
        ]
        for y in range(history_count):
            year = 2024 - y
            amount = random.randint(100_000, 10_000_000)
            heads = random.randint(5, 100)
            met = True if risk == 'clean' else (random.random() > 0.3 if risk == 'minor_issues' else random.random() > 0.6)
            history.append({
                'year': year,
                'type': random.choice(types),
                'amount': amount,
                'heads': heads,
                'status': 'executed' if met else 'pending',
                'obligations_met': met,
            })

        return {
            'registered': risk != 'fraudulent' or random.random() > 0.2,
            'registration_date': reg_date.isoformat(),
            'entity_type': entity_type,
            'name': name,
            'region': region,
            'district': district,
            'subsidy_history': history,
            'total_subsidies_history': sum(h['amount'] for h in history),
            'pending_returns': 0 if risk == 'clean' else random.randint(0, 5),
        }

    def _gen_easu(self, entity_type, name):
        return {
            'has_account_number': True,
            'account_numbers': [f'KZ-AGR-{random.randint(100000, 999999)}'],
            'is_spk': entity_type == 'cooperative',
            'spk_members': [],
            'spk_name': name if entity_type == 'cooperative' else None,
        }

    def _gen_is_iszh(self, risk, iin_bin):
        count = random.randint(5, 50)
        animals = []
        for j in range(count):
            animal_type = random.choice(['cattle', 'sheep', 'horse'])
            breed = random.choice(
                BREEDS_CATTLE if animal_type == 'cattle' else
                BREEDS_SHEEP if animal_type == 'sheep' else BREEDS_HORSE
            )
            age = random.randint(4, 24)
            age_valid = 6 <= age <= 18

            animals.append({
                'tag_number': f'KZ{random.randint(10000000, 99999999)}',
                'type': animal_type,
                'breed': breed,
                'category': random.choice(['heifer', 'bull', 'ewe', 'ram']),
                'sex': random.choice(['female', 'male']),
                'birth_date': (date.today() - timedelta(days=age * 30)).isoformat(),
                'age_months': age,
                'age_valid': age_valid if risk != 'fraudulent' else random.random() > 0.4,
                'owner_iin_bin': iin_bin,
                'owner_match': True,
                'previously_subsidized': risk == 'fraudulent' and random.random() > 0.5,
                'vet_status': 'healthy' if risk != 'risky' else random.choice(['healthy', 'quarantine']),
                'last_vet_check': (date.today() - timedelta(days=random.randint(1, 90))).isoformat(),
                'registration_date': (date.today() - timedelta(days=random.randint(30, 365))).isoformat(),
            })

        rejected = sum(1 for a in animals if not a['age_valid'] or a['previously_subsidized'])
        return {
            'verified': True,
            'animals': animals,
            'total_verified': count - rejected,
            'total_rejected': rejected,
            'rejection_reasons': [],
        }

    def _gen_is_esf(self, risk, iin_bin):
        inv_count = random.randint(1, 3)
        invoices = []
        for _ in range(inv_count):
            amount = random.randint(500_000, 15_000_000)
            invoices.append({
                'esf_number': f'ESF-2025-{random.randint(1000000, 9999999)}',
                'date': f'2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
                'seller_bin': generate_bin(),
                'seller_name': f"ТОО \"{random.choice(FARM_NAMES)} {fake.city_name()}\"",
                'buyer_iin_bin': iin_bin,
                'total_amount': amount,
                'items': [{
                    'description': random.choice([
                        'Племенные тёлки ангусской породы',
                        'Племенные овцы эдильбаевской породы',
                        'Молоко коровье',
                        'Шерсть полутонкая',
                    ]),
                    'quantity': random.randint(5, 100),
                    'unit': random.choice(['голова', 'кг']),
                    'unit_price': random.randint(5000, 500000),
                    'amount': amount,
                }],
                'status': 'confirmed' if risk != 'fraudulent' else random.choice(['confirmed', 'draft']),
                'payment_confirmed': risk in ('clean', 'minor_issues'),
            })

        return {
            'invoices': invoices,
            'total_amount': sum(i['total_amount'] for i in invoices),
            'invoice_count': len(invoices),
        }

    def _gen_egkn(self, risk, region, district):
        if risk == 'fraudulent' and random.random() > 0.6:
            return {'has_agricultural_land': False, 'plots': [], 'total_agricultural_area': 0}

        plot_count = random.randint(1, 3)
        plots = []
        for _ in range(plot_count):
            area = round(random.uniform(5, 500), 1)
            plots.append({
                'cadastral_number': f'{random.randint(1,99):02d}-{random.randint(100,999)}-{random.randint(100,999)}-{random.randint(100,999)}',
                'area_hectares': area,
                'purpose': 'сельскохозяйственное назначение',
                'sub_purpose': random.choice(['пастбище', 'пашня', 'сенокос']),
                'region': region,
                'district': district,
                'ownership_type': random.choice(['собственность', 'аренда']),
                'registration_date': f'{random.randint(2010, 2023)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
            })

        return {
            'has_agricultural_land': True,
            'plots': plots,
            'total_agricultural_area': round(sum(p['area_hectares'] for p in plots), 1),
        }

    def _gen_treasury(self, risk):
        if risk in ('risky', 'fraudulent'):
            return {'payments': []}
        payment_count = random.randint(0, 3)
        payments = []
        for _ in range(payment_count):
            payments.append({
                'payment_id': f'PAY-2025-{random.randint(10000, 99999)}',
                'amount': random.randint(100_000, 10_000_000),
                'status': 'completed',
                'paid_date': f'2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
                'treasury_reference': f'TR-2025-{random.randint(10000, 99999)}',
            })
        return {'payments': payments}
