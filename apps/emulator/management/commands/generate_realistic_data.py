"""
Generate realistic synthetic dataset for Kazakhstan agricultural subsidy system.

Based on real statistics:
- stat.gov.kz (Bureau of National Statistics 2023-2024)
- Ministry of Agriculture subsidy rates (Приказ №108)
- Regional livestock distribution patterns

Total budget cap: 118.4 billion tenge across 17 oblasts.
"""
import random
import math
from datetime import date, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from faker import Faker

from apps.emulator.models import EmulatedEntity, RFIDMonitoring
from apps.scoring.models import (
    SubsidyDirection, SubsidyType, Budget,
    Applicant, Application,
)

fake = Faker('ru_RU')

# ============================================================
# REAL STATISTICS: Regions with livestock & entity estimates
# ============================================================

REGION_STATS = {
    # region: {
    #   budget_cap: max sum of applications (from user data),
    #   entities: approximate total farming entities,
    #   cattle: thousands of heads,
    #   sheep: thousands (МРС),
    #   horse: thousands,
    #   camel: thousands,
    #   poultry: thousands,
    #   pasture_ha: thousands of hectares,
    #   arable_ha: thousands of hectares,
    #   districts: [...],
    #   center_lat_lon: (lat, lon),
    # }
    'Акмолинская область': {
        'budget_cap': 5_287_589_364,
        'entities': 13500,
        'cattle': 500, 'sheep': 700, 'horse': 225, 'camel': 1.5, 'poultry': 5500,
        'pasture_ha': 8000, 'arable_ha': 4200,
        'districts': ['Целиноградский район', 'Бурабайский район', 'Аршалинский район',
                      'Ерейментауский район', 'Атбасарский район', 'Коргалжынский район'],
        'center': (51.15, 69.40),
    },
    'Актюбинская область': {
        'budget_cap': 5_096_659_539,
        'entities': 9000,
        'cattle': 385, 'sheep': 1350, 'horse': 225, 'camel': 10, 'poultry': 1200,
        'pasture_ha': 17000, 'arable_ha': 1350,
        'districts': ['Мугалжарский район', 'Хромтауский район', 'Алгинский район',
                      'Мартукский район', 'Айтекебийский район', 'Темирский район'],
        'center': (50.30, 57.20),
    },
    'Алматинская область': {
        'budget_cap': 4_319_686_138,
        'entities': 30000,
        'cattle': 900, 'sheep': 3000, 'horse': 375, 'camel': 10, 'poultry': 6000,
        'pasture_ha': 6000, 'arable_ha': 1750,
        'districts': ['Алматинский район', 'Енбекшиказахский район', 'Талгарский район',
                      'Карасайский район', 'Илийский район', 'Жамбылский район'],
        'center': (43.35, 77.00),
    },
    'Атырауская область': {
        'budget_cap': 8_377_009_139,
        'entities': 4800,
        'cattle': 175, 'sheep': 700, 'horse': 100, 'camel': 25, 'poultry': 400,
        'pasture_ha': 10200, 'arable_ha': 75,
        'districts': ['Жылыойский район', 'Макатский район', 'Индерский район',
                      'Исатайский район', 'Курмангазинский район'],
        'center': (47.10, 51.92),
    },
    'Западно-Казахстанская область': {
        'budget_cap': 5_562_229_948,
        'entities': 8000,
        'cattle': 385, 'sheep': 1150, 'horse': 225, 'camel': 6.5, 'poultry': 1000,
        'pasture_ha': 9200, 'arable_ha': 1150,
        'districts': ['Бурлинский район', 'Теректинский район', 'Зеленовский район',
                      'Жанибекский район', 'Казталовский район'],
        'center': (51.35, 51.36),
    },
    'Жамбылская область': {
        'budget_cap': 4_313_694_890,
        'entities': 20000,
        'cattle': 550, 'sheep': 2000, 'horse': 225, 'camel': 17.5, 'poultry': 1750,
        'pasture_ha': 7750, 'arable_ha': 900,
        'districts': ['Жамбылский район', 'Кордайский район', 'Байзакский район',
                      'Меркенский район', 'Шуский район', 'Мойынкумский район'],
        'center': (42.90, 71.40),
    },
    'Карагандинская область': {
        'budget_cap': 7_680_751_970,
        'entities': 11500,
        'cattle': 450, 'sheep': 1000, 'horse': 225, 'camel': 6.5, 'poultry': 3750,
        'pasture_ha': 14000, 'arable_ha': 1750,
        'districts': ['Бухар-Жырауский район', 'Нуринский район', 'Осакаровский район',
                      'Шетский район', 'Абайский район'],
        'center': (49.80, 73.10),
    },
    'Костанайская область': {
        'budget_cap': 6_664_870_290,
        'entities': 15500,
        'cattle': 550, 'sheep': 900, 'horse': 275, 'camel': 1.5, 'poultry': 4500,
        'pasture_ha': 9200, 'arable_ha': 5000,
        'districts': ['Костанайский район', 'Житикаринский район', 'Наурзумский район',
                      'Мендыкаринский район', 'Карабалыкский район', 'Федоровский район'],
        'center': (53.20, 63.60),
    },
    'Кызылординская область': {
        'budget_cap': 10_752_411_803,
        'entities': 8000,
        'cattle': 285, 'sheep': 900, 'horse': 125, 'camel': 35, 'poultry': 650,
        'pasture_ha': 10750, 'arable_ha': 275,
        'districts': ['Кызылординский район', 'Аральский район', 'Казалинский район',
                      'Жалагашский район', 'Шиелийский район'],
        'center': (44.85, 65.50),
    },
    'Мангистауская область': {
        'budget_cap': 6_708_457_897,
        'entities': 3000,
        'cattle': 65, 'sheep': 600, 'horse': 50, 'camel': 30, 'poultry': 150,
        'pasture_ha': 10000, 'arable_ha': 5,
        'districts': ['Мунайлинский район', 'Каракиянский район', 'Тупкараганский район',
                      'Мангистауский район', 'Бейнеуский район'],
        'center': (43.35, 52.06),
    },
    'Павлодарская область': {
        'budget_cap': 10_817_069_759,
        'entities': 9000,
        'cattle': 385, 'sheep': 575, 'horse': 200, 'camel': 2.5, 'poultry': 2750,
        'pasture_ha': 8200, 'arable_ha': 2000,
        'districts': ['Павлодарский район', 'Экибастузский район', 'Баянаульский район',
                      'Аксуский район', 'Иртышский район', 'Щербактинский район'],
        'center': (52.30, 76.95),
    },
    'Северо-Казахстанская область': {
        'budget_cap': 4_848_737_059,
        'entities': 11000,
        'cattle': 440, 'sheep': 450, 'horse': 175, 'camel': 0.5, 'poultry': 5000,
        'pasture_ha': 4000, 'arable_ha': 4200,
        'districts': ['Аккайынский район', 'Кызылжарский район', 'Есильский район',
                      'Мамлютский район', 'Тайыншинский район'],
        'center': (54.87, 69.15),
    },
    'Туркестанская область': {
        'budget_cap': 9_124_961_358,
        'entities': 27500,
        'cattle': 950, 'sheep': 3750, 'horse': 275, 'camel': 30, 'poultry': 2250,
        'pasture_ha': 9500, 'arable_ha': 900,
        'districts': ['Сайрамский район', 'Ордабасынский район', 'Отрарский район',
                      'Арысский район', 'Тюлькубасский район', 'Казыгуртский район'],
        'center': (42.30, 68.25),
    },
    'Восточно-Казахстанская область': {
        'budget_cap': 2_425_151_885,
        'entities': 16500,
        'cattle': 600, 'sheep': 1650, 'horse': 275, 'camel': 3, 'poultry': 3250,
        'pasture_ha': 5200, 'arable_ha': 1750,
        'districts': ['Усть-Каменогорский район', 'Шемонаихинский район', 'Зыряновский район',
                      'Глубоковский район', 'Катон-Карагайский район'],
        'center': (49.95, 82.60),
    },
    'область Абай': {
        'budget_cap': 10_190_630_137,
        'entities': 9000,
        'cattle': 385, 'sheep': 900, 'horse': 175, 'camel': 2, 'poultry': 1750,
        'pasture_ha': 5200, 'arable_ha': 1000,
        'districts': ['Жарминский район', 'Аягозский район', 'Семейский район',
                      'Абайский район', 'Бескарагайский район'],
        'center': (50.42, 80.23),
    },
    'область Жетісу': {
        'budget_cap': 7_174_295_802,
        'entities': 11500,
        'cattle': 550, 'sheep': 1650, 'horse': 225, 'camel': 6.5, 'poultry': 1750,
        'pasture_ha': 4200, 'arable_ha': 1000,
        'districts': ['Аксуский район', 'Панфиловский район', 'Каратальский район',
                      'Сарканский район', 'Алакольский район'],
        'center': (44.85, 79.00),
    },
    'область Ұлытау': {
        'budget_cap': 9_029_500_739,
        'entities': 3500,
        'cattle': 175, 'sheep': 600, 'horse': 125, 'camel': 4, 'poultry': 650,
        'pasture_ha': 10000, 'arable_ha': 400,
        'districts': ['Жанааркинский район', 'Улытауский район', 'Сарысуский район'],
        'center': (48.00, 67.50),
    },
}

# Breed lists
BREEDS = {
    'cattle': ['Ангусская', 'Герефордская', 'Казахская белоголовая', 'Шароле',
               'Лимузинская', 'Голштинская', 'Симментальская', 'Аулиекольская'],
    'sheep': ['Эдильбаевская', 'Казахская тонкорунная', 'Каракульская', 'Меринос',
              'Гиссарская', 'Дегересская', 'Казахская грубошёрстная'],
    'horse': ['Казахская', 'Кустанайская', 'Мугалжарская', 'Донская', 'Кушумская'],
    'camel': ['Казахский бактриан', 'Калмыцкая', 'Туркменский дромедар', 'Арвана'],
    'poultry': ['Кросс Росс-308', 'Кросс Кобб-500', 'Ломан Браун', 'Хай-Лайн', 'Кросс ИСА'],
}

FARM_NAMES = [
    'Агрофирма', 'Байтерек', 'Дала', 'Жулдыз', 'Нур', 'Степь', 'Асыл', 'Тулпар',
    'Береке', 'Достык', 'Шанырак', 'Жайлау', 'Кокше', 'Арман', 'Мерей', 'Алтын',
    'Саулет', 'Кенже', 'Акбота', 'Самал', 'Отрар', 'Сарыарка', 'Табиғат', 'Жалын',
    'Тоғай', 'Мирас', 'Думан', 'Алға', 'Өнер', 'Жанар', 'Шыңғыс', 'Ордабасы',
]

SELLER_NAMES = [
    'ТОО "АгроСнаб Казахстан"', 'КХ "Племхоз"', 'ТОО "Алтын Бас"',
    'ИП Нурланов А.К.', 'ТОО "Казплем"', 'КХ "Жайлау"',
    'ТОО "Астана-Агро"', 'ИП Серикбаев Б.Т.', 'ТОО "СарыАрка Агро"',
    'ТОО "ЮгАгро"', 'КХ "Береке Плем"', 'ТОО "Костанай Плем"',
]


def generate_iin():
    year = random.randint(60, 99)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    rest = random.randint(100000, 999999)
    return f'{year:02d}{month:02d}{day:02d}{rest}'


def generate_bin():
    year = random.randint(10, 25)
    month = random.randint(1, 12)
    rest = random.randint(10000000, 99999999)
    return f'{year:02d}{month:02d}{rest}'


def _generate_plot_polygon(center_lat, center_lon, area_ha, idx=0):
    offset_lat = (idx * 0.015) + random.uniform(-0.01, 0.01)
    offset_lon = (idx * 0.015) + random.uniform(-0.01, 0.01)
    clat = center_lat + offset_lat
    clon = center_lon + offset_lon
    side_m = math.sqrt(area_ha * 10000)
    dlat = side_m / 111000 / 2
    dlon = side_m / (111000 * max(math.cos(math.radians(clat)), 0.01)) / 2
    skew = random.uniform(-0.0005, 0.0005)
    coords = [
        [round(clon - dlon, 6), round(clat - dlat, 6)],
        [round(clon + dlon + skew, 6), round(clat - dlat + skew, 6)],
        [round(clon + dlon, 6), round(clat + dlat, 6)],
        [round(clon - dlon - skew, 6), round(clat + dlat - skew, 6)],
        [round(clon - dlon, 6), round(clat - dlat, 6)],
    ]
    return {'type': 'Polygon', 'coordinates': [coords]}


class Command(BaseCommand):
    help = 'Generate realistic dataset based on real KZ agricultural statistics'

    def add_arguments(self, parser):
        parser.add_argument('--entities', type=int, default=3000,
                            help='Total entities to generate (default 3000)')
        parser.add_argument('--clear', action='store_true',
                            help='Clear existing entities, applications, applicants')
        parser.add_argument('--no-apps', action='store_true',
                            help='Only generate entities, skip applications')
        parser.add_argument('--no-score', action='store_true',
                            help='Skip scoring after app creation')

    def handle(self, *args, **options):
        total_entities = options['entities']

        if options['clear']:
            Application.objects.all().delete()
            Applicant.objects.all().delete()
            RFIDMonitoring.objects.all().delete()
            # Keep demo entities (hardcoded IINs)
            demo_iins = {'880720300456', '901105200789', '950315400123',
                         '850930100234', '920812500567', '870325100890'}
            deleted = EmulatedEntity.objects.exclude(iin_bin__in=demo_iins).delete()
            self.stdout.write(f'Cleared {deleted[0]} entities (kept {len(demo_iins)} demo)')

        existing_iins = set(EmulatedEntity.objects.values_list('iin_bin', flat=True))

        # ---- Step 1: Distribute entities across regions proportionally ----
        total_real_entities = sum(r['entities'] for r in REGION_STATS.values())
        region_entity_counts = {}
        for region, stats in REGION_STATS.items():
            proportion = stats['entities'] / total_real_entities
            region_entity_counts[region] = max(5, int(total_entities * proportion))

        # Adjust to match total
        diff = total_entities - sum(region_entity_counts.values())
        sorted_regions = sorted(REGION_STATS.keys(),
                                key=lambda r: REGION_STATS[r]['entities'], reverse=True)
        for i in range(abs(diff)):
            r = sorted_regions[i % len(sorted_regions)]
            region_entity_counts[r] += 1 if diff > 0 else -1

        self.stdout.write(f'Generating {total_entities} entities across {len(REGION_STATS)} regions...')

        # ---- Step 2: Generate entities per region ----
        all_entities = []
        for region, count in region_entity_counts.items():
            stats = REGION_STATS[region]
            self.stdout.write(f'  {region}: {count} entities...')

            for i in range(count):
                entity = self._create_entity(region, stats, existing_iins)
                if entity:
                    all_entities.append(entity)
                    existing_iins.add(entity.iin_bin)

                if len(all_entities) % 500 == 0 and len(all_entities) > 0:
                    self.stdout.write(f'    Total created: {len(all_entities)}')

        self.stdout.write(self.style.SUCCESS(
            f'Generated {len(all_entities)} entities'))

        # ---- Step 3: Create RFID records ----
        self._create_rfid_records(all_entities)

        if options['no_apps']:
            return

        # ---- Step 4: Create applications (budget-controlled) ----
        self._create_applications(all_entities)

        # ---- Step 5: Update budgets to match ----
        self._update_budgets()

        if not options['no_score']:
            self._run_scoring()

    def _create_entity(self, region, stats, existing_iins):
        """Create a single EmulatedEntity with realistic data for the region."""
        district = random.choice(stats['districts'])

        # Entity type distribution: 55% КХ (legal), 33% ИП (individual), 12% СПК/ТОО
        roll = random.random()
        if roll < 0.45:
            entity_type = 'legal'  # КХ / ТОО
            iin_bin = generate_bin()
            # 80% КХ, 20% ТОО
            if random.random() < 0.8:
                name = f'КХ "{fake.last_name()} {fake.first_name()[0]}."'
                farm_size = 'small'  # КХ = small
            else:
                name = f'ТОО "{random.choice(FARM_NAMES)} {fake.city_name()}"'
                farm_size = random.choice(['medium'] * 7 + ['large'] * 3)
        elif roll < 0.88:
            entity_type = 'individual'  # ИП
            iin_bin = generate_iin()
            name = f'ИП {fake.last_name()} {fake.first_name()[0]}.'
            farm_size = 'small'
        else:
            entity_type = 'cooperative'  # СПК
            iin_bin = generate_bin()
            name = f'СПК "{random.choice(FARM_NAMES)}"'
            farm_size = random.choice(['medium'] * 6 + ['large'] * 4)

        if iin_bin in existing_iins:
            return None

        # Risk profile: 70% clean, 15% minor, 10% risky, 5% fraud
        risk = random.choices(
            ['clean', 'minor_issues', 'risky', 'fraudulent'],
            weights=[70, 15, 10, 5]
        )[0]

        reg_date = date(random.randint(2010, 2023), random.randint(1, 12), random.randint(1, 28))

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
            is_iszh_data=self._gen_is_iszh(risk, iin_bin, farm_size, region, stats),
            is_esf_data=self._gen_is_esf(risk, iin_bin, farm_size),
            egkn_data=self._gen_egkn(risk, region, district, farm_size, stats),
            treasury_data=self._gen_treasury(risk, farm_size),
        )
        entity.save()
        return entity

    # ==============================================================
    # DATA GENERATORS - Realistic per region and farm size
    # ==============================================================

    def _gen_giss(self, risk):
        """ГИСС — государственная информационная система сельского хозяйства."""
        prev = random.randint(5_000_000, 300_000_000)
        if risk == 'clean':
            growth = random.uniform(2, 25)
        elif risk == 'minor_issues':
            growth = random.uniform(-5, 12)
        elif risk == 'risky':
            growth = random.uniform(-20, 3)
        else:
            growth = random.uniform(-30, -5)

        before = int(prev / (1 + growth / 100))
        total_subs = random.randint(0, 300_000_000)

        consecutive_decline_years = {
            'clean': 0,
            'minor_issues': random.choice([0, 0, 1]),
            'risky': random.choice([0, 1, 2]),
            'fraudulent': random.choice([2, 3]),
        }[risk]

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
        """ИАС РСЖ — история субсидий."""
        history_count = random.randint(0, 5) if risk != 'fraudulent' else random.randint(3, 8)
        subsidy_types = [
            'Приобретение маточного поголовья КРС',
            'Приобретение племенных овец',
            'Удешевление производства молока',
            'Удешевление стоимости шерсти',
            'Селекционная работа с лошадьми',
            'Приобретение племенного быка-производителя',
            'Удешевление стоимости реализованной говядины',
            'Ведение селекционной работы с маточным поголовьем',
        ]
        history = []
        for y in range(history_count):
            year = 2024 - y
            amount = random.randint(200_000, 15_000_000)
            heads = random.randint(5, 300)
            met = True if risk == 'clean' else (random.random() > 0.3 if risk == 'minor_issues' else random.random() > 0.6)
            history.append({
                'year': year,
                'type': random.choice(subsidy_types),
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

    def _gen_is_iszh(self, risk, iin_bin, farm_size, region, stats):
        """ИС ИЖС — данные о животных. Realistic counts based on farm size and region."""

        # Determine animal counts based on farm size
        if farm_size == 'small':
            cattle_count = random.randint(5, 50)
            sheep_count = random.randint(20, 200)
            horse_count = random.randint(3, 30)
            camel_count = random.randint(0, 10) if stats['camel'] > 5 else 0
            poultry_count = random.randint(0, 300)
        elif farm_size == 'medium':
            cattle_count = random.randint(50, 500)
            sheep_count = random.randint(200, 2000)
            horse_count = random.randint(30, 200)
            camel_count = random.randint(10, 80) if stats['camel'] > 5 else random.randint(0, 5)
            poultry_count = random.randint(500, 10000)
        else:  # large
            cattle_count = random.randint(500, 5000)
            sheep_count = random.randint(2000, 20000)
            horse_count = random.randint(200, 1000)
            camel_count = random.randint(50, 300) if stats['camel'] > 5 else random.randint(0, 20)
            poultry_count = random.randint(5000, 50000)

        # Regional weighting: scale by region's livestock density
        total_national_cattle = sum(r['cattle'] for r in REGION_STATS.values())
        cattle_scale = stats['cattle'] / (total_national_cattle / len(REGION_STATS))
        cattle_count = max(1, int(cattle_count * min(cattle_scale, 2.0)))

        total_national_sheep = sum(r['sheep'] for r in REGION_STATS.values())
        sheep_scale = stats['sheep'] / (total_national_sheep / len(REGION_STATS))
        sheep_count = max(0, int(sheep_count * min(sheep_scale, 2.0)))

        # Choose which animals this farm has (not all types)
        # Most farms specialize
        specialization = random.choices(
            ['cattle', 'sheep', 'mixed', 'horse'],
            weights=[35, 30, 25, 10]
        )[0]

        if specialization == 'cattle':
            sheep_count = sheep_count // 4
            horse_count = horse_count // 2
        elif specialization == 'sheep':
            cattle_count = cattle_count // 3
            horse_count = horse_count // 2
        elif specialization == 'horse':
            cattle_count = cattle_count // 3
            sheep_count = sheep_count // 3
        # mixed keeps all

        animals = []

        # Generate cattle
        for j in range(min(cattle_count, 200)):  # Cap JSON size
            animals.append(self._make_animal('cattle', risk, iin_bin))

        # Generate sheep (summarize if too many)
        for j in range(min(sheep_count, 150)):
            animals.append(self._make_animal('sheep', risk, iin_bin))

        # Generate horses
        for j in range(min(horse_count, 80)):
            animals.append(self._make_animal('horse', risk, iin_bin))

        # Generate camels
        for j in range(min(camel_count, 30)):
            animals.append(self._make_animal('camel', risk, iin_bin))

        # Total real count stored separately for large farms
        total_real_count = cattle_count + sheep_count + horse_count + camel_count + poultry_count

        # Pedigree certificates
        for a in animals:
            has_pedigree = random.random() > (0.3 if risk in ('clean', 'minor_issues') else 0.6)
            a['pedigree_certificate'] = has_pedigree

        rejected = sum(1 for a in animals if not a.get('age_valid', True) or a.get('previously_subsidized', False))

        # Mortality data (Приказ №3-3/1061)
        mortality_records = []
        animal_types_in_herd = set(a['type'] for a in animals)
        for atype in animal_types_in_herd:
            type_count = sum(1 for a in animals if a['type'] == atype)
            if risk == 'clean':
                mort_pct = round(random.uniform(0.0, 1.5), 2)
            elif risk == 'minor_issues':
                mort_pct = round(random.uniform(0.5, 2.5), 2)
            elif risk == 'risky':
                mort_pct = round(random.uniform(1.0, 4.5), 2)
            else:
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
            sum(r['fallen_count'] for r in mortality_records) / max(len(animals), 1) * 100, 2
        )

        return {
            'verified': True,
            'animals': animals,
            'total_count_real': total_real_count,
            'cattle_count': cattle_count,
            'sheep_count': sheep_count,
            'horse_count': horse_count,
            'camel_count': camel_count,
            'poultry_count': poultry_count,
            'total_verified': len(animals) - rejected,
            'total_rejected': rejected,
            'rejection_reasons': [],
            'mortality_data': {
                'records': mortality_records,
                'total_mortality_pct': total_mort_pct,
                'reporting_year': 2025,
            },
        }

    def _make_animal(self, animal_type, risk, iin_bin):
        """Generate a single animal record."""
        breed = random.choice(BREEDS.get(animal_type, ['Местная']))
        age = random.randint(4, 36)
        age_valid = 6 <= age <= 24
        sex = random.choice(['female', 'male'])

        # RFID
        has_rfid = random.random() > 0.15
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
            else:
                rfid_active = random.random() > 0.7
                rfid_scan_count = random.randint(0, 3)
                rfid_last_scan = (date.today() - timedelta(days=random.randint(30, 90))).isoformat()
        else:
            rfid_active = False
            rfid_scan_count = 0
            rfid_last_scan = None

        prev_sub = risk == 'fraudulent' and random.random() > 0.5

        # Productivity
        if animal_type == 'cattle':
            meat_kg = round(random.uniform(180, 400), 1) if sex == 'male' else round(random.uniform(150, 280), 1)
            milk_liters = round(random.uniform(3000, 8000), 0) if sex == 'female' else 0
        elif animal_type == 'sheep':
            meat_kg = round(random.uniform(15, 50), 1)
            milk_liters = round(random.uniform(50, 200), 0) if sex == 'female' else 0
        elif animal_type == 'horse':
            meat_kg = round(random.uniform(150, 320), 1)
            milk_liters = round(random.uniform(1000, 3000), 0) if sex == 'female' else 0
        elif animal_type == 'camel':
            meat_kg = round(random.uniform(200, 450), 1)
            milk_liters = round(random.uniform(1500, 4000), 0) if sex == 'female' else 0
        else:
            meat_kg = 0
            milk_liters = 0

        seller = {
            'name': random.choice(SELLER_NAMES),
            'iin_bin': f'{random.randint(100000000000, 999999999999)}',
            'purchase_date': (date.today() - timedelta(days=random.randint(30, 730))).isoformat(),
            'purchase_price': random.randint(150000, 1200000),
        }

        categories = {
            'cattle': ['heifer', 'bull', 'cow', 'calf', 'young'],
            'sheep': ['ewe', 'ram', 'lamb', 'yearling'],
            'horse': ['mare', 'stallion', 'foal', 'gelding'],
            'camel': ['female', 'male', 'calf'],
        }

        return {
            'tag_number': f'KZ{random.randint(10000000, 99999999)}',
            'type': animal_type,
            'breed': breed,
            'category': random.choice(categories.get(animal_type, ['adult'])),
            'sex': sex,
            'birth_date': (date.today() - timedelta(days=age * 30)).isoformat(),
            'age_months': age,
            'age_valid': age_valid if risk != 'fraudulent' else random.random() > 0.4,
            'owner_iin_bin': iin_bin,
            'owner_match': True,
            'previously_subsidized': prev_sub,
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
        }

    def _gen_is_esf(self, risk, iin_bin, farm_size):
        """ЭСФ — электронные счета-фактуры."""
        if farm_size == 'small':
            inv_count = random.randint(1, 3)
            amount_range = (300_000, 5_000_000)
        elif farm_size == 'medium':
            inv_count = random.randint(2, 5)
            amount_range = (2_000_000, 20_000_000)
        else:
            inv_count = random.randint(3, 8)
            amount_range = (10_000_000, 100_000_000)

        invoices = []
        for _ in range(inv_count):
            amount = random.randint(*amount_range)
            invoices.append({
                'esf_number': f'ESF-2025-{random.randint(1000000, 9999999)}',
                'date': f'2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
                'seller_bin': generate_bin(),
                'seller_name': random.choice(SELLER_NAMES),
                'buyer_iin_bin': iin_bin,
                'total_amount': amount,
                'items': [{
                    'description': random.choice([
                        'Племенные тёлки', 'Племенные овцы', 'Молоко коровье',
                        'Шерсть полутонкая', 'Племенные лошади', 'Корма комбинированные',
                    ]),
                    'quantity': random.randint(5, 500),
                    'unit': random.choice(['голова', 'кг', 'тонна']),
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

    def _gen_egkn(self, risk, region, district, farm_size, stats):
        """ЕГКН — земельный кадастр."""
        if risk == 'fraudulent' and random.random() > 0.6:
            return {'has_agricultural_land': False, 'plots': [], 'total_agricultural_area': 0}

        # Land size by farm size
        if farm_size == 'small':
            total_area = random.uniform(30, 500)
            plot_count = random.randint(1, 2)
        elif farm_size == 'medium':
            total_area = random.uniform(500, 5000)
            plot_count = random.randint(1, 4)
        else:
            total_area = random.uniform(5000, 50000)
            plot_count = random.randint(2, 6)

        center = stats['center']
        plots = []
        remaining = total_area
        for i in range(plot_count):
            if i == plot_count - 1:
                area = remaining
            else:
                area = round(random.uniform(remaining * 0.2, remaining * 0.6), 1)
                remaining -= area
            area = max(5, round(area, 1))
            geometry = _generate_plot_polygon(center[0], center[1], area, idx=i)
            plots.append({
                'cadastral_number': f'{random.randint(1,99):02d}-{random.randint(100,999)}-{random.randint(100,999)}-{random.randint(100,999)}',
                'area_hectares': area,
                'purpose': 'сельскохозяйственное назначение',
                'sub_purpose': random.choice(['пастбище', 'пашня', 'сенокос', 'пастбище', 'пастбище']),
                'region': region,
                'district': district,
                'ownership_type': random.choice(['собственность', 'аренда', 'аренда']),
                'registration_date': f'{random.randint(2010, 2023)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
                'geometry': geometry,
            })

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

    def _gen_treasury(self, risk, farm_size):
        """Казначейство — история выплат."""
        if risk in ('risky', 'fraudulent'):
            return {'payments': []}

        if farm_size == 'small':
            payment_count = random.randint(0, 2)
            amount_range = (100_000, 3_000_000)
        elif farm_size == 'medium':
            payment_count = random.randint(1, 4)
            amount_range = (1_000_000, 15_000_000)
        else:
            payment_count = random.randint(2, 6)
            amount_range = (5_000_000, 50_000_000)

        payments = []
        for _ in range(payment_count):
            payments.append({
                'payment_id': f'PAY-2025-{random.randint(10000, 99999)}',
                'amount': random.randint(*amount_range),
                'status': 'completed',
                'paid_date': f'2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
                'treasury_reference': f'TR-2025-{random.randint(10000, 99999)}',
            })
        return {'payments': payments}

    # ==============================================================
    # RFID, APPLICATIONS, BUDGETS, SCORING
    # ==============================================================

    def _create_rfid_records(self, entities):
        """Create RFIDMonitoring records for entities with RFID-tagged animals."""
        self.stdout.write('Creating RFID records...')
        rfid_locations = ['Ворота загона', 'Поилка №1', 'Поилка №2', 'Кормушка', 'Доильный зал', 'Пастбище']
        rfid_readers = ['Панельный UHF', 'Станция на поилке', 'Ручной ридер', 'Станция на кормушке']
        count = 0
        for entity in entities:
            for animal in (entity.is_iszh_data or {}).get('animals', [])[:50]:  # Cap RFID per entity
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
                    count += 1
        self.stdout.write(f'  Created {count} RFID records')

    def _create_applications(self, entities):
        """Create applications with budget control per region."""
        self.stdout.write('Creating applications (budget-controlled)...')

        subsidy_types = list(SubsidyType.objects.filter(is_active=True))
        if not subsidy_types:
            self.stdout.write(self.style.ERROR('No subsidy types! Run seed_data first.'))
            return

        # Track spent per region
        region_spent = {r: 0 for r in REGION_STATS}
        statuses = ['submitted'] * 35 + ['checking'] * 15 + ['approved'] * 20 + \
                   ['paid'] * 15 + ['rejected'] * 10 + ['waiting_list'] * 5

        total_created = 0
        random.shuffle(entities)

        for entity in entities:
            region = entity.region
            if region not in REGION_STATS:
                continue

            budget_cap = REGION_STATS[region]['budget_cap']
            if region_spent[region] >= budget_cap * 0.95:
                continue  # Budget almost full

            # 1-3 applications per entity
            app_count = random.choices([1, 2, 3], weights=[60, 30, 10])[0]

            for _ in range(app_count):
                if region_spent[region] >= budget_cap * 0.95:
                    break

                stype = random.choice(subsidy_types)
                animals_data = entity.is_iszh_data.get('animals', [])

                # Realistic quantity based on farm data
                real_count = entity.is_iszh_data.get('total_count_real', len(animals_data))
                if stype.unit in ('голова', 'осеменённая голова'):
                    quantity = min(random.randint(5, max(10, real_count // 2)), 500)
                elif stype.unit in ('кг мяса', 'кг молока', 'кг говядины', 'кг конины', 'кг шерсти', 'кг пуха', 'кг рыбы', 'кг молока', 'кг мёда'):
                    quantity = random.randint(500, 50000)
                elif stype.unit in ('тонна', 'тонна'):
                    quantity = random.randint(10, 2000)
                elif stype.unit in ('га',):
                    total_land = (entity.egkn_data or {}).get('total_agricultural_area', 100)
                    quantity = min(random.randint(10, max(20, int(total_land))), 5000)
                elif stype.unit == 'единица':
                    quantity = random.randint(1, 5)
                else:
                    quantity = random.randint(5, 100)

                total_amount = int(quantity * float(stype.rate))

                # Cap single application at reasonable amount
                max_single = min(budget_cap * 0.05, 500_000_000)  # max 5% of region budget or 500M
                if total_amount > max_single:
                    quantity = max(1, int(max_single / float(stype.rate)))
                    total_amount = int(quantity * float(stype.rate))

                if total_amount < 10000:
                    continue

                # Check budget
                if region_spent[region] + total_amount > budget_cap:
                    continue

                # Create applicant
                applicant, _ = Applicant.objects.get_or_create(
                    iin_bin=entity.iin_bin,
                    defaults={
                        'name': entity.name,
                        'entity_type': entity.entity_type,
                        'region': entity.region,
                        'district': entity.district,
                        'phone': f'+7 (7{random.randint(0,99):02d}) {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}',
                        'email': f'{entity.iin_bin}@mail.kz',
                        'bank_account': f'KZ{random.randint(10**17, 10**18 - 1)}',
                        'bank_name': random.choice(['АО "Халык Банк"', 'АО "Каспи Банк"', 'АО "Народный Банк"']),
                        'registration_date': entity.registration_date,
                        'is_blocked': entity.giss_data.get('blocked', False),
                    },
                )

                esf_data = entity.is_esf_data.get('invoices', [{}])
                esf = esf_data[0] if esf_data else {}
                submitted = timezone.now() - timedelta(days=random.randint(1, 300))
                number = f'{random.randint(10, 99)}{random.randint(100, 999)}{random.randint(100, 999)}{random.randint(100000, 999999)}'

                try:
                    Application.objects.create(
                        number=number,
                        applicant=applicant,
                        subsidy_type=stype,
                        status=random.choice(statuses),
                        quantity=quantity,
                        unit_price=float(stype.rate) * random.uniform(1.0, 1.5),
                        rate=stype.rate,
                        total_amount=total_amount,
                        submitted_at=submitted,
                        region=entity.region,
                        district=entity.district,
                        akimat=f'ГУ "Управление сельского хозяйства {entity.region}"',
                        animals_data=animals_data[:quantity] if stype.unit == 'голова' else [],
                        esf_number=esf.get('esf_number', ''),
                        esf_amount=esf.get('total_amount', 0),
                        counterparty_bin=esf.get('seller_bin', ''),
                        counterparty_name=esf.get('seller_name', ''),
                    )
                    region_spent[region] += total_amount
                    total_created += 1
                except Exception:
                    continue  # Duplicate number, etc.

                if total_created % 500 == 0:
                    self.stdout.write(f'  Created {total_created} applications...')

        self.stdout.write(self.style.SUCCESS(f'Created {total_created} applications'))

        # Report
        self.stdout.write('\nBudget utilization:')
        for region in sorted(REGION_STATS.keys()):
            cap = REGION_STATS[region]['budget_cap']
            spent = region_spent[region]
            pct = spent / cap * 100 if cap > 0 else 0
            self.stdout.write(f'  {region:45s} {spent/1e9:6.1f} / {cap/1e9:6.1f} млрд ({pct:.0f}%)')

    def _update_budgets(self):
        """Update Budget model to match regional caps."""
        self.stdout.write('Updating budgets...')
        directions = list(SubsidyDirection.objects.all())
        if not directions:
            return

        for region, stats in REGION_STATS.items():
            total_budget = stats['budget_cap']
            # Distribute across directions (weighted by direction type)
            livestock_dirs = [d for d in directions if d.code in (
                'cattle_meat', 'cattle_dairy', 'cattle_general', 'sheep',
                'horse', 'camel', 'poultry', 'pig', 'beekeeping', 'aquaculture')]
            crop_dirs = [d for d in directions if d not in livestock_dirs]

            # 55% livestock, 45% crops
            livestock_budget = int(total_budget * 0.55)
            crop_budget = total_budget - livestock_budget

            for d in livestock_dirs:
                share = livestock_budget / len(livestock_dirs)
                # Add some variance
                amount = int(share * random.uniform(0.5, 1.5))
                spent = int(amount * random.uniform(0.4, 0.85))
                Budget.objects.update_or_create(
                    year=2025, region=region, direction=d,
                    defaults={'planned_amount': amount, 'spent_amount': spent},
                )

            for d in crop_dirs:
                share = crop_budget / max(len(crop_dirs), 1)
                amount = int(share * random.uniform(0.5, 1.5))
                spent = int(amount * random.uniform(0.3, 0.8))
                Budget.objects.update_or_create(
                    year=2025, region=region, direction=d,
                    defaults={'planned_amount': amount, 'spent_amount': spent},
                )

        self.stdout.write(f'  Updated budgets for {len(REGION_STATS)} regions')

    def _run_scoring(self):
        """Run scoring on all unscored applications."""
        self.stdout.write('Running scoring...')
        try:
            from apps.scoring.scoring_engine import ScoringEngine
            engine = ScoringEngine()
            scored = 0
            for app in Application.objects.filter(score__isnull=True):
                try:
                    engine.run_scoring(app)
                    scored += 1
                except Exception:
                    pass
                if scored % 200 == 0 and scored > 0:
                    self.stdout.write(f'  Scored {scored}...')
            self.stdout.write(self.style.SUCCESS(f'Scored {scored} applications'))
        except ImportError:
            self.stdout.write(self.style.WARNING('Scoring engine not found'))
