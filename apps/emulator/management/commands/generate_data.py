"""
Generate synthetic EmulatedEntity data from Excel + random generation.
Creates entities with realistic data for all 7 external system APIs.
"""
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from faker import Faker

from apps.emulator.models import EmulatedEntity, RFIDMonitoring
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

# Центры регионов для генерации полигонов земельных участков
REGION_CENTERS = {
    'Акмолинская область': (51.15, 69.40),
    'Алматинская область': (43.35, 77.00),
    'Костанайская область': (53.20, 63.60),
    'Туркестанская область': (42.30, 68.25),
    'Карагандинская область': (49.80, 73.10),
    'область Абай': (50.42, 80.23),
    'Павлодарская область': (52.30, 76.95),
    'Северо-Казахстанская область': (54.87, 69.15),
    'Восточно-Казахстанская область': (49.95, 82.60),
    'Актюбинская область': (50.30, 57.20),
    'Западно-Казахстанская область': (51.35, 51.36),
    'Жамбылская область': (42.90, 71.40),
    'Атырауская область': (47.10, 51.92),
    'Кызылординская область': (44.85, 65.50),
    'Мангистауская область': (43.35, 52.06),
    'область Жетісу': (44.85, 79.00),
    'область Ұлытау': (48.00, 67.50),
}


def _generate_plot_polygon(center_lat, center_lon, area_ha, idx=0):
    """Генерирует прямоугольный полигон GeoJSON для земельного участка."""
    import math
    # Смещение для каждого участка, чтобы не накладывались
    offset_lat = (idx * 0.015) + random.uniform(-0.01, 0.01)
    offset_lon = (idx * 0.015) + random.uniform(-0.01, 0.01)
    clat = center_lat + offset_lat
    clon = center_lon + offset_lon
    # Примерный размер в градусах (1° ≈ 111 км)
    side_m = math.sqrt(area_ha * 10000)  # сторона квадрата в метрах
    dlat = side_m / 111000 / 2
    dlon = side_m / (111000 * math.cos(math.radians(clat))) / 2
    # Небольшое искажение для реалистичности
    skew = random.uniform(-0.0005, 0.0005)
    coords = [
        [round(clon - dlon, 6), round(clat - dlat, 6)],
        [round(clon + dlon + skew, 6), round(clat - dlat + skew, 6)],
        [round(clon + dlon, 6), round(clat + dlat, 6)],
        [round(clon - dlon - skew, 6), round(clat + dlat - skew, 6)],
        [round(clon - dlon, 6), round(clat - dlat, 6)],  # замыкание
    ]
    return {'type': 'Polygon', 'coordinates': [coords]}

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

            # Create RFIDMonitoring records for animals with RFID
            rfid_locations = ['Ворота загона', 'Поилка №1', 'Поилка №2', 'Кормушка', 'Доильный зал', 'Пастбище']
            rfid_readers = ['Панельный UHF', 'Станция на поилке', 'Ручной ридер', 'Станция на кормушке']
            for animal in (entity.is_iszh_data or {}).get('animals', []):
                if animal.get('rfid_tag'):
                    scan_dt = timezone.now() - timedelta(days=random.randint(0, 30))
                    if animal.get('rfid_active'):
                        status = 'active'
                    elif animal.get('rfid_scan_count_30d', 0) == 0:
                        status = 'missing'
                    else:
                        status = 'inactive'
                    RFIDMonitoring.objects.update_or_create(
                        entity=entity,
                        animal_tag=animal['tag_number'],
                        defaults={
                            'rfid_tag': animal['rfid_tag'],
                            'last_scan_date': scan_dt,
                            'scan_location': random.choice(rfid_locations),
                            'status': status,
                            'scan_count_30d': animal.get('rfid_scan_count_30d', 0),
                            'animal_type': animal.get('type', ''),
                            'reader_type': random.choice(rfid_readers),
                        },
                    )

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

        # Consecutive years of declining production (Приказ №108)
        if risk == 'fraudulent':
            consecutive_decline_years = random.choice([2, 3])
        elif risk == 'risky':
            consecutive_decline_years = random.choice([0, 1, 2])
        elif risk == 'minor_issues':
            consecutive_decline_years = random.choice([0, 0, 1])
        else:
            consecutive_decline_years = 0

        # Whether this is a repeat violation (for ban duration: 1 year vs 2 years)
        repeat_violation = risk == 'fraudulent' and random.random() > 0.5

        return {
            'registered': risk != 'fraudulent' or random.random() > 0.3,
            'gross_production_previous_year': prev,
            'gross_production_year_before': before,
            'growth_rate': round(growth, 2),
            'obligations_met': risk in ('clean', 'minor_issues'),
            'total_subsidies_received': total_subs,
            'obligations_required': total_subs >= 100_000_000,
            'consecutive_decline_years': consecutive_decline_years,
            'repeat_violation': repeat_violation,
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

            # RFID data
            has_rfid = random.random() > 0.2  # 80% animals have RFID
            rfid_tag = f'RFID-{random.randint(1000000, 9999999)}' if has_rfid else None
            if has_rfid:
                if risk == 'clean':
                    rfid_active = True
                    rfid_scan_count = random.randint(20, 60)
                    rfid_last_scan = (date.today() - timedelta(days=random.randint(0, 3))).isoformat()
                elif risk == 'minor_issues':
                    rfid_active = random.random() > 0.2
                    rfid_scan_count = random.randint(5, 30)
                    rfid_last_scan = (date.today() - timedelta(days=random.randint(1, 14))).isoformat()
                elif risk == 'risky':
                    rfid_active = random.random() > 0.5
                    rfid_scan_count = random.randint(0, 10)
                    rfid_last_scan = (date.today() - timedelta(days=random.randint(7, 45))).isoformat()
                else:  # fraudulent
                    rfid_active = random.random() > 0.7
                    rfid_scan_count = random.randint(0, 3)
                    rfid_last_scan = (date.today() - timedelta(days=random.randint(30, 90))).isoformat()
            else:
                rfid_active = False
                rfid_scan_count = 0
                rfid_last_scan = None

            sex = random.choice(['female', 'male'])
            prev_sub = risk == 'fraudulent' and random.random() > 0.5

            # Продуктивность: кг мяса / литры молока
            if animal_type == 'cattle':
                meat_kg = round(random.uniform(180, 350), 1) if sex == 'male' else round(random.uniform(150, 250), 1)
                milk_liters = round(random.uniform(3000, 8000), 0) if sex == 'female' else 0
            elif animal_type == 'sheep':
                meat_kg = round(random.uniform(15, 45), 1)
                milk_liters = round(random.uniform(50, 200), 0) if sex == 'female' else 0
            elif animal_type == 'horse':
                meat_kg = round(random.uniform(150, 280), 1)
                milk_liters = round(random.uniform(1000, 3000), 0) if sex == 'female' else 0
            else:
                meat_kg = 0
                milk_liters = 0

            # Продавец (откуда купили животное)
            seller_names = [
                'ТОО "АгроСнаб Казахстан"', 'КХ "Племхоз"', 'ТОО "Алтын Бас"',
                'ИП Нурланов А.К.', 'ТОО "Казплем"', 'КХ "Жайлау"',
                'ТОО "Астана-Агро"', 'ИП Серикбаев Б.Т.', 'ТОО "СарыАрка Агро"',
            ]
            seller = {
                'name': random.choice(seller_names),
                'iin_bin': f'{random.randint(100000000000, 999999999999)}',
                'purchase_date': (date.today() - timedelta(days=random.randint(30, 730))).isoformat(),
                'purchase_price': random.randint(150000, 800000),
            }

            # Детали предыдущих субсидий (если ранее субсидировалось)
            subsidy_details = []
            if prev_sub:
                sub_year = random.randint(2022, 2025)
                sub_types = [
                    'Приобретение маточного поголовья КРС',
                    'Ведение селекционной работы',
                    'Удешевление стоимости реализованной говядины',
                    'Приобретение племенного быка-производителя',
                ]
                subsidy_details.append({
                    'year': sub_year,
                    'type': random.choice(sub_types),
                    'amount': random.randint(100000, 400000),
                    'status': 'выплачено',
                })

            animals.append({
                'tag_number': f'KZ{random.randint(10000000, 99999999)}',
                'type': animal_type,
                'breed': breed,
                'category': random.choice(['heifer', 'bull', 'ewe', 'ram']),
                'sex': sex,
                'birth_date': (date.today() - timedelta(days=age * 30)).isoformat(),
                'age_months': age,
                'age_valid': age_valid if risk != 'fraudulent' else random.random() > 0.4,
                'owner_iin_bin': iin_bin,
                'owner_match': True,
                'previously_subsidized': prev_sub,
                'subsidy_details': subsidy_details,
                'meat_kg': meat_kg,
                'milk_liters': milk_liters,
                'seller': seller,
                'vet_status': 'healthy' if risk != 'risky' else random.choice(['healthy', 'quarantine']),
                'last_vet_check': (date.today() - timedelta(days=random.randint(1, 90))).isoformat(),
                'registration_date': (date.today() - timedelta(days=random.randint(30, 365))).isoformat(),
                'rfid_tag': rfid_tag,
                'rfid_active': rfid_active,
                'rfid_last_scan': rfid_last_scan,
                'rfid_scan_count_30d': rfid_scan_count,
            })

            # Племенное свидетельство (для племенных субсидий, Приказ №108)
            has_pedigree = random.random() > (0.3 if risk in ('clean', 'minor_issues') else 0.6)
            animals[-1]['pedigree_certificate'] = has_pedigree

        rejected = sum(1 for a in animals if not a['age_valid'] or a['previously_subsidized'])

        # --- Данные о падеже (Приказ №3-3/1061) ---
        mortality_records = []
        animal_types_in_herd = set(a['type'] for a in animals)
        for atype in animal_types_in_herd:
            type_count = sum(1 for a in animals if a['type'] == atype)
            if risk == 'clean':
                mort_pct = round(random.uniform(0.0, 1.5), 2)
            elif risk == 'minor_issues':
                mort_pct = round(random.uniform(0.5, 2.5), 2)
            elif risk == 'risky':
                mort_pct = round(random.uniform(1.0, 4.0), 2)
            else:  # fraudulent
                mort_pct = round(random.uniform(2.0, 8.0), 2)
            fallen = max(0, int(type_count * mort_pct / 100))
            mortality_records.append({
                'animal_type': atype,
                'category': 'adult',
                'total_count': type_count,
                'fallen_count': fallen,
                'mortality_pct': mort_pct,
                'period': '2025',
            })

        total_mort_pct = round(
            sum(r['fallen_count'] for r in mortality_records) / max(count, 1) * 100, 2
        )
        mortality_data = {
            'records': mortality_records,
            'total_mortality_pct': total_mort_pct,
            'reporting_year': 2025,
        }

        return {
            'verified': True,
            'animals': animals,
            'total_verified': count - rejected,
            'total_rejected': rejected,
            'rejection_reasons': [],
            'mortality_data': mortality_data,
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
        center = REGION_CENTERS.get(region, (48.0, 68.0))
        for i in range(plot_count):
            area = round(random.uniform(5, 500), 1)
            geometry = _generate_plot_polygon(center[0], center[1], area, idx=i)
            plots.append({
                'cadastral_number': f'{random.randint(1,99):02d}-{random.randint(100,999)}-{random.randint(100,999)}-{random.randint(100,999)}',
                'area_hectares': area,
                'purpose': 'сельскохозяйственное назначение',
                'sub_purpose': random.choice(['пастбище', 'пашня', 'сенокос']),
                'region': region,
                'district': district,
                'ownership_type': random.choice(['собственность', 'аренда']),
                'registration_date': f'{random.randint(2010, 2023)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
                'geometry': geometry,
            })

        # Площадь пастбищ и зона (Приказ №3-3/332)
        pasture_area = round(sum(
            p['area_hectares'] for p in plots
            if p.get('sub_purpose') in ('пастбище', 'сенокос')
        ), 1)
        pasture_zone = random.choice(['restored', 'degraded']) if risk != 'fraudulent' else 'degraded'

        return {
            'has_agricultural_land': True,
            'plots': plots,
            'total_agricultural_area': round(sum(p['area_hectares'] for p in plots), 1),
            'pasture_area': pasture_area,
            'pasture_zone': pasture_zone,
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
