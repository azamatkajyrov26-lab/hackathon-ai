"""
Generate historical application data from real Excel dataset.

Creates:
1. Applicant records for unique farms
2. EmulatedEntity records with realistic data from 7 systems
3. Historical Application records (2020-2024) for each applicant
4. Current 2025 applications from the real dataset
5. Syncs subsidy_history in EmulatedEntity with Application records

Usage:
    python manage.py generate_history --file docs/Выгрузка...xlsx
    python manage.py generate_history --clear --file docs/Выгрузка...xlsx
"""
import random
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from apps.emulator.models import EmulatedEntity
from apps.scoring.models import (
    Applicant, Application, Budget, HardFilterResult,
    Score, ScoreFactor, SubsidyDirection, SubsidyType,
)

fake = Faker('ru_RU')

# === Mapping from dataset directions to our DB direction codes ===
DIRECTION_MAP = {
    'Субсидирование в скотоводстве': 'cattle_meat',
    'Субсидирование затрат по искусственному осеменению': 'cattle_general',
    'Субсидирование в овцеводстве': 'sheep',
    'Субсидирование в козоводстве': 'sheep',
    'Субсидирование в коневодстве': 'horse',
    'Субсидирование в птицеводстве': 'poultry',
    'Субсидирование в свиноводстве': 'pig',
    'Субсидирование в верблюдоводстве': 'camel',
    'Субсидирование в пчеловодстве': 'beekeeping',
}

# === Mapping subsidy names to direction codes for more precision ===
NAME_TO_DIRECTION = {
    'молочн': 'cattle_dairy',
    'молоко (коровье)': 'cattle_dairy',
    'молока (коровье)': 'cattle_dairy',
    'молока (кобылье)': 'horse',
    'молока (верблюжье)': 'camel',
    'быков-производителей': 'cattle_meat',
    'маточного поголовья крупного': 'cattle_meat',
    'племенного молодняка крупного': 'cattle_meat',
    'крупного рогатого скота': 'cattle_meat',
    'овец': 'sheep',
    'мелкого рогатого': 'sheep',
    'шерсти': 'sheep',
    'козы': 'sheep',
    'коз': 'sheep',
    'жеребца': 'horse',
    'лошадей': 'horse',
    'конины': 'horse',
    'птицы': 'poultry',
    'курицы': 'poultry',
    'яичного': 'poultry',
    'свин': 'pig',
    'верблюд': 'camel',
    'шубат': 'camel',
    'меда': 'beekeeping',
    'пчел': 'beekeeping',
    'осеменен': 'cattle_general',
    'семя': 'cattle_general',
    'эмбрион': 'cattle_general',
    'корма': 'cattle_meat',
}

# Status mapping from real dataset to our DB statuses
STATUS_MAP = {
    'Исполнена': 'paid',
    'Одобрена': 'approved',
    'Отклонена': 'rejected',
    'Отозвано': 'rejected',
    'Получена': 'submitted',
    'Сформировано поручение': 'approved',
}

BREEDS_CATTLE = ['Ангусская', 'Герефордская', 'Казахская белоголовая', 'Шароле', 'Лимузинская', 'Голштинская', 'Симментальская']
BREEDS_SHEEP = ['Эдильбаевская', 'Казахская тонкорунная', 'Каракульская', 'Меринос', 'Гиссарская']
BREEDS_HORSE = ['Казахская', 'Кустанайская', 'Мугалжарская', 'Донская']

FARM_PREFIXES = ['ТОО', 'КХ', 'ТОО']
FARM_NAMES = [
    'Агрофирма', 'Байтерек', 'Дала', 'Жулдыз', 'Нур', 'Степь', 'Асыл', 'Тулпар',
    'Береке', 'Достык', 'Шанырак', 'Жайлау', 'Кокше', 'Арман', 'Мерей', 'Алтын',
    'Саулет', 'Кенже', 'Акбота', 'Самал', 'Отрар', 'Сарыарка', 'Табиғат',
    'Ақ бидай', 'Жер ана', 'Қоңыр', 'Алтай', 'Тараз', 'Байконур', 'Арыстан',
]

DISTRICTS_BY_REGION = {
    'Акмолинская область': ['Целиноградский район', 'Бурабайский район', 'Аршалинский район', 'Ерейментауский район', 'Шортандинский район'],
    'Алматинская область': ['Алматинский район', 'Енбекшиказахский район', 'Талгарский район', 'Карасайский район', 'Илийский район'],
    'Костанайская область': ['Костанайский район', 'Житикаринский район', 'Рудненский район', 'Наурзумский район', 'Мендыкаринский район'],
    'Туркестанская область': ['Сайрамский район', 'Ордабасынский район', 'Отрарский район', 'Толебийский район'],
    'Карагандинская область': ['Бухар-Жырауский район', 'Нуринский район', 'Осакаровский район', 'Шетский район'],
    'область Абай': ['Жарминский район', 'Аягозский район', 'Семейский район', 'Бескарагайский район'],
    'Павлодарская область': ['Павлодарский район', 'Экибастузский район', 'Баянаульский район', 'Иртышский район'],
    'Северо-Казахстанская область': ['Петропавловский район', 'Аккайынский район', 'Кызылжарский район', 'Тайыншинский район'],
    'Восточно-Казахстанская область': ['Усть-Каменогорский район', 'Шемонаихинский район', 'Зыряновский район', 'Глубоковский район'],
    'Актюбинская область': ['Мугалжарский район', 'Хромтауский район', 'Алгинский район', 'Мартукский район'],
    'Западно-Казахстанская область': ['Бурлинский район', 'Теректинский район', 'Казталовский район'],
    'Жамбылская область': ['Жамбылский район', 'Кордайский район', 'Байзакский район', 'Мойынкумский район'],
    'Атырауская область': ['Жылыойский район', 'Макатский район', 'Индерский район'],
    'Кызылординская область': ['Кызылординский район', 'Аральский район', 'Казалинский район'],
    'Мангистауская область': ['Мунайлинский район', 'Каракиянский район', 'Бейнеуский район'],
    'область Жетісу': ['Аксуский район', 'Панфиловский район', 'Коксуский район'],
    'область Ұлытау': ['Жанааркинский район', 'Улытауский район'],
    'г.Шымкент': ['Шымкент'],
}


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


def resolve_direction(direction_name, subsidy_name):
    """Determine direction code from dataset direction + subsidy name."""
    subsidy_lower = subsidy_name.lower() if subsidy_name else ''

    # Check specific subsidy name first
    for keyword, code in NAME_TO_DIRECTION.items():
        if keyword in subsidy_lower:
            return code

    # Fallback to direction name
    return DIRECTION_MAP.get(direction_name, 'cattle_meat')


class Command(BaseCommand):
    help = 'Generate historical data from real Excel dataset with application history'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file', type=str,
            default='docs/Выгрузка по выданным субсидиям 2025 год (обезлич).xlsx',
            help='Path to Excel dataset',
        )
        parser.add_argument('--clear', action='store_true', help='Clear all existing data')
        parser.add_argument('--max-applicants', type=int, default=500, help='Max unique applicants to create')
        parser.add_argument('--history-years', type=int, default=4, help='Years of history (2020-2024)')

    def handle(self, *args, **options):
        filepath = options['file']
        max_applicants = options['max_applicants']
        history_years = options['history_years']

        if options['clear']:
            self._clear_data()

        # Step 1: Read Excel dataset
        self.stdout.write('Reading Excel dataset...')
        rows = self._read_excel(filepath)
        self.stdout.write(f'  Read {len(rows)} rows from dataset')

        # Step 2: Group by unique application numbers (proxy for unique applicants)
        # Since dataset is anonymized, we group by (region, district, direction) combinations
        # and treat each unique combo as one applicant
        grouped = self._group_applicants(rows, max_applicants)
        self.stdout.write(f'  Grouped into {len(grouped)} unique applicants')

        # Step 3: Ensure SubsidyDirection + SubsidyType exist
        self._ensure_directions()

        # Step 4: Create data with history
        self.stdout.write('Generating applicants, entities and history...')
        stats = self._create_all_data(grouped, history_years)

        self.stdout.write(self.style.SUCCESS(
            f'\nDone! Created:\n'
            f'  {stats["applicants"]} applicants\n'
            f'  {stats["entities"]} emulated entities\n'
            f'  {stats["historical_apps"]} historical applications (2020-2024)\n'
            f'  {stats["current_apps"]} current applications (2025)\n'
            f'  Total: {stats["historical_apps"] + stats["current_apps"]} applications'
        ))

    def _clear_data(self):
        self.stdout.write('Clearing existing data...')
        Score.objects.all().delete()
        HardFilterResult.objects.all().delete()
        Application.objects.all().delete()
        Applicant.objects.all().delete()
        EmulatedEntity.objects.all().delete()
        self.stdout.write('  Cleared all scoring + emulator data')

    def _read_excel(self, filepath):
        wb = openpyxl.load_workbook(filepath, read_only=True)
        ws = wb.active
        rows = []
        for i, row in enumerate(ws.iter_rows(min_row=6, values_only=True)):
            if not row[6]:  # Skip rows without номер заявки
                continue
            rows.append({
                'date': row[1],
                'region': row[4],
                'akimat': row[5],
                'number': str(row[6]).strip() if row[6] else '',
                'direction': row[7],
                'subsidy_name': row[8],
                'status': row[9],
                'rate': row[10],
                'amount': row[11],
                'district': row[12],
            })
        wb.close()
        return rows

    def _group_applicants(self, rows, max_applicants):
        """
        Group dataset rows into "applicants".
        Since data is anonymized, we create synthetic applicants per
        unique (region, district) pair and assign rows to them.
        One applicant can have multiple applications in 2025.
        """
        # Group by (region, district)
        by_location = {}
        for row in rows:
            key = (row['region'] or '', row['district'] or '')
            if key not in by_location:
                by_location[key] = []
            by_location[key].append(row)

        # Create applicant groups: split large location groups
        applicants = []
        for (region, district), location_rows in by_location.items():
            if not region:
                continue
            # Each applicant gets ~5-50 applications from this location
            chunk_size = random.randint(5, 50)
            random.shuffle(location_rows)
            for start in range(0, len(location_rows), chunk_size):
                chunk = location_rows[start:start + chunk_size]
                applicants.append({
                    'region': region,
                    'district': district,
                    'rows': chunk,
                })
                if len(applicants) >= max_applicants:
                    break
            if len(applicants) >= max_applicants:
                break

        return applicants[:max_applicants]

    def _ensure_directions(self):
        """Make sure all directions exist."""
        for code in set(DIRECTION_MAP.values()):
            SubsidyDirection.objects.get_or_create(code=code)

    def _create_all_data(self, grouped, history_years):
        stats = {'applicants': 0, 'entities': 0, 'historical_apps': 0, 'current_apps': 0}
        existing_iins = set(Applicant.objects.values_list('iin_bin', flat=True))
        existing_numbers = set(Application.objects.values_list('number', flat=True))

        for idx, group in enumerate(grouped):
            region = group['region']
            district = group['district']
            current_rows = group['rows']

            # Determine risk profile based on statuses
            statuses = [r['status'] for r in current_rows if r['status']]
            rejected_ratio = sum(1 for s in statuses if s in ('Отклонена', 'Отозвано')) / max(len(statuses), 1)
            if rejected_ratio > 0.5:
                risk = 'risky'
            elif rejected_ratio > 0.2:
                risk = 'minor_issues'
            elif rejected_ratio > 0:
                risk = random.choice(['clean', 'minor_issues'])
            else:
                risk = 'clean'

            # Override: small % fraudulent
            if random.random() < 0.03:
                risk = 'fraudulent'

            # Generate entity type
            entity_roll = random.random()
            if entity_roll < 0.55:
                entity_type = 'legal'
                iin_bin = generate_bin()
                name = f'{random.choice(FARM_PREFIXES)} "{random.choice(FARM_NAMES)} {fake.city_name()}"'
            elif entity_roll < 0.88:
                entity_type = 'individual'
                iin_bin = generate_iin()
                name = f'ИП {fake.last_name()} {fake.first_name()[0]}.'
            else:
                entity_type = 'cooperative'
                iin_bin = generate_bin()
                name = f'СПК "{random.choice(FARM_NAMES)}"'

            # Ensure unique IIN
            while iin_bin in existing_iins:
                iin_bin = generate_bin() if entity_type != 'individual' else generate_iin()
            existing_iins.add(iin_bin)

            reg_date = date(random.randint(2015, 2022), random.randint(1, 12), random.randint(1, 28))

            # Primary direction from rows
            directions = [resolve_direction(r['direction'], r['subsidy_name']) for r in current_rows]
            primary_direction = max(set(directions), key=directions.count)

            with transaction.atomic():
                # --- Create Applicant ---
                applicant = Applicant.objects.create(
                    iin_bin=iin_bin,
                    name=name,
                    entity_type=entity_type,
                    region=region,
                    district=district or '',
                    address=f'{region}, {district}',
                    phone=f'+7{random.randint(700, 778)}{random.randint(1000000, 9999999)}',
                    email=f'{iin_bin}@agro.kz',
                    bank_account=f'KZ{random.randint(10, 99)}{"".join([str(random.randint(0,9)) for _ in range(18)])}',
                    bank_name=random.choice(['Халык Банк', 'Kaspi Bank', 'БЦК', 'Отбасы Банк', 'Jusan Bank']),
                    registration_date=reg_date,
                    is_blocked=risk == 'fraudulent' and random.random() > 0.6,
                )
                stats['applicants'] += 1

                # --- Generate historical subsidies (for ias_rszh_data) ---
                subsidy_history = self._generate_subsidy_history(
                    risk, primary_direction, history_years, current_rows,
                )

                # --- Create EmulatedEntity ---
                entity = EmulatedEntity.objects.create(
                    iin_bin=iin_bin,
                    name=name,
                    entity_type=entity_type,
                    region=region,
                    district=district or '',
                    registration_date=reg_date,
                    risk_profile=risk,
                    giss_data=self._gen_giss(risk, subsidy_history, current_rows),
                    ias_rszh_data=self._gen_ias_rszh(risk, reg_date, region, district, name, entity_type, subsidy_history),
                    easu_data=self._gen_easu(entity_type, name),
                    is_iszh_data=self._gen_is_iszh(risk, iin_bin, primary_direction),
                    is_esf_data=self._gen_is_esf(risk, iin_bin, current_rows),
                    egkn_data=self._gen_egkn(risk, region, district),
                    treasury_data=self._gen_treasury(risk, subsidy_history),
                )
                stats['entities'] += 1

                # --- Create historical Application records (2020-2024) ---
                for hist in subsidy_history:
                    app_number = f'H{hist["year"]}{random.randint(100000, 999999):06d}'
                    while app_number in existing_numbers:
                        app_number = f'H{hist["year"]}{random.randint(100000, 999999):06d}'
                    existing_numbers.add(app_number)

                    hist_dir_code = hist.get('direction_code', primary_direction)
                    stype = self._find_subsidy_type(hist_dir_code, hist.get('type', ''))

                    hist_status = 'paid' if hist['obligations_met'] else random.choice(['rejected', 'paid'])
                    submitted = datetime(hist['year'], random.randint(2, 10), random.randint(1, 28),
                                         random.randint(8, 17), random.randint(0, 59),
                                         tzinfo=timezone.get_current_timezone())

                    Application.objects.create(
                        number=app_number,
                        applicant=applicant,
                        subsidy_type=stype,
                        status=hist_status,
                        quantity=hist.get('heads', random.randint(5, 50)),
                        rate=Decimal(str(stype.rate)),
                        total_amount=Decimal(str(hist['amount'])),
                        submitted_at=submitted,
                        region=region,
                        district=district or '',
                        akimat=current_rows[0].get('akimat', ''),
                        ecp_signed=True,
                        ecp_signed_at=submitted,
                    )
                    stats['historical_apps'] += 1

                # --- Create current (2025) Application records from real data ---
                for row in current_rows:
                    app_number = str(row['number']).strip()
                    if not app_number or app_number in existing_numbers:
                        app_number = f'A2025{random.randint(1000000, 9999999)}'
                        while app_number in existing_numbers:
                            app_number = f'A2025{random.randint(1000000, 9999999)}'
                    existing_numbers.add(app_number)

                    dir_code = resolve_direction(row['direction'], row['subsidy_name'])
                    stype = self._find_subsidy_type(dir_code, row.get('subsidy_name', ''))

                    amount = row['amount'] or 0
                    rate_val = row['rate'] or float(stype.rate)
                    quantity = max(1, int(amount / rate_val)) if rate_val and rate_val > 0 else random.randint(1, 20)

                    status = STATUS_MAP.get(row['status'], 'submitted')

                    # Parse date
                    submitted = None
                    if row['date']:
                        if isinstance(row['date'], datetime):
                            submitted = row['date']
                            if submitted.tzinfo is None:
                                submitted = timezone.make_aware(submitted)
                        elif isinstance(row['date'], str):
                            try:
                                submitted = datetime.strptime(row['date'][:19], '%d.%m.%Y %H:%M:%S')
                                submitted = timezone.make_aware(submitted)
                            except (ValueError, TypeError):
                                pass
                    if not submitted:
                        submitted = timezone.make_aware(
                            datetime(2025, random.randint(1, 3), random.randint(1, 28), 10, 0)
                        )

                    Application.objects.create(
                        number=app_number,
                        applicant=applicant,
                        subsidy_type=stype,
                        status=status,
                        quantity=quantity,
                        rate=Decimal(str(rate_val)),
                        total_amount=Decimal(str(amount)) if amount else Decimal('0'),
                        submitted_at=submitted,
                        region=region,
                        district=district or '',
                        akimat=row.get('akimat', '') or '',
                        ecp_signed=True,
                        ecp_signed_at=submitted,
                    )
                    stats['current_apps'] += 1

            if (idx + 1) % 50 == 0:
                self.stdout.write(f'  Progress: {idx + 1}/{len(grouped)} applicants...')

        return stats

    def _generate_subsidy_history(self, risk, primary_direction, history_years, current_rows):
        """Generate realistic subsidy history for 2020-2024."""
        history = []

        # Determine how many years of history
        if risk == 'clean':
            years_active = random.randint(2, history_years)
        elif risk == 'minor_issues':
            years_active = random.randint(1, history_years)
        elif risk == 'risky':
            years_active = random.randint(1, 3)
        else:  # fraudulent
            years_active = random.randint(2, history_years)  # fraudsters often have long history

        # Average amount from current rows
        amounts = [r['amount'] for r in current_rows if r['amount'] and r['amount'] > 0]
        avg_amount = sum(amounts) / len(amounts) if amounts else 1_000_000

        start_year = 2025 - years_active
        for year in range(start_year, 2025):
            # Some years might be skipped
            if random.random() < 0.2:
                continue

            # Amount with year-to-year variation
            year_amount = int(avg_amount * random.uniform(0.5, 1.5))
            heads = max(1, int(year_amount / random.randint(15000, 300000)))

            if risk == 'clean':
                met = True
            elif risk == 'minor_issues':
                met = random.random() > 0.15
            elif risk == 'risky':
                met = random.random() > 0.4
            else:  # fraudulent
                met = random.random() > 0.6

            # Direction might vary slightly
            if random.random() < 0.8:
                dir_code = primary_direction
            else:
                dir_code = random.choice(list(set(DIRECTION_MAP.values())))

            history.append({
                'year': year,
                'type': dir_code,
                'direction_code': dir_code,
                'amount': year_amount,
                'heads': heads,
                'status': 'executed' if met else random.choice(['pending', 'returned']),
                'obligations_met': met,
            })

        return history

    def _find_subsidy_type(self, direction_code, subsidy_name=''):
        """Find matching SubsidyType or return first one for direction."""
        try:
            direction = SubsidyDirection.objects.get(code=direction_code)
        except SubsidyDirection.DoesNotExist:
            direction = SubsidyDirection.objects.first()

        types = SubsidyType.objects.filter(direction=direction)
        if not types.exists():
            # Fallback: any type
            return SubsidyType.objects.first()

        # Try to match by subsidy name keywords
        if subsidy_name:
            name_lower = subsidy_name.lower()
            for t in types:
                if any(word in name_lower for word in t.name.lower().split()[:3]):
                    return t

        return types.first()

    # === Data generators for EmulatedEntity ===

    def _gen_giss(self, risk, history, current_rows):
        amounts = [r['amount'] for r in current_rows if r['amount'] and r['amount'] > 0]
        total_current = sum(amounts) if amounts else 0
        total_historical = sum(h['amount'] for h in history)

        if risk == 'clean':
            growth = round(random.uniform(3, 25), 2)
        elif risk == 'minor_issues':
            growth = round(random.uniform(-3, 12), 2)
        elif risk == 'risky':
            growth = round(random.uniform(-15, 5), 2)
        else:
            growth = round(random.uniform(-30, -5), 2)

        prev = random.randint(10_000_000, 300_000_000)
        before = int(prev / (1 + growth / 100))

        obligations_met_history = all(h['obligations_met'] for h in history) if history else True
        total_subs = total_historical + total_current

        return {
            'registered': risk != 'fraudulent' or random.random() > 0.3,
            'gross_production_previous_year': prev,
            'gross_production_year_before': before,
            'growth_rate': growth,
            'obligations_met': obligations_met_history if risk != 'fraudulent' else False,
            'total_subsidies_received': total_subs,
            'obligations_required': total_subs >= 100_000_000,
            'blocked': risk == 'fraudulent' and random.random() > 0.5,
            'block_reason': 'Невыполнение встречных обязательств' if risk == 'fraudulent' else None,
        }

    def _gen_ias_rszh(self, risk, reg_date, region, district, name, entity_type, history):
        formatted_history = []
        for h in history:
            formatted_history.append({
                'year': h['year'],
                'type': h['type'],
                'amount': h['amount'],
                'heads': h['heads'],
                'status': 'executed' if h['obligations_met'] else 'pending',
                'obligations_met': h['obligations_met'],
            })

        pending_returns = sum(1 for h in history if not h['obligations_met'])

        return {
            'registered': risk != 'fraudulent' or random.random() > 0.2,
            'ibspr_registered': risk != 'fraudulent' or random.random() > 0.3,
            'registration_date': reg_date.isoformat(),
            'entity_type': entity_type,
            'name': name,
            'region': region,
            'district': district or '',
            'subsidy_history': formatted_history,
            'total_subsidies_history': sum(h['amount'] for h in history),
            'pending_returns': pending_returns,
        }

    def _gen_easu(self, entity_type, name):
        return {
            'has_account_number': True,
            'account_numbers': [f'KZ-AGR-{random.randint(100000, 999999)}'],
            'is_spk': entity_type == 'cooperative',
            'spk_members': [],
            'spk_name': name if entity_type == 'cooperative' else None,
        }

    def _gen_is_iszh(self, risk, iin_bin, direction):
        # Number of animals based on direction
        if direction in ('poultry',):
            count = random.randint(50, 5000)
        elif direction in ('sheep',):
            count = random.randint(20, 500)
        elif direction in ('beekeeping',):
            count = random.randint(10, 200)
        else:
            count = random.randint(5, 100)

        animals = []
        for j in range(min(count, 50)):  # Cap at 50 for JSON size
            if direction in ('cattle_meat', 'cattle_dairy', 'cattle_general'):
                animal_type = 'cattle'
                breed = random.choice(BREEDS_CATTLE)
                categories = ['heifer', 'bull', 'cow']
            elif direction == 'sheep':
                animal_type = 'sheep'
                breed = random.choice(BREEDS_SHEEP)
                categories = ['ewe', 'ram', 'lamb']
            elif direction == 'horse':
                animal_type = 'horse'
                breed = random.choice(BREEDS_HORSE)
                categories = ['mare', 'stallion', 'foal']
            else:
                animal_type = random.choice(['cattle', 'sheep'])
                breed = random.choice(BREEDS_CATTLE + BREEDS_SHEEP)
                categories = ['heifer', 'bull', 'ewe', 'ram']

            age = random.randint(4, 36)
            age_valid = 6 <= age <= 26  # General range from rules

            animals.append({
                'tag_number': f'KZ{random.randint(10000000, 99999999)}',
                'type': animal_type,
                'breed': breed,
                'category': random.choice(categories),
                'sex': random.choice(['female', 'male']),
                'birth_date': (date.today() - timedelta(days=age * 30)).isoformat(),
                'age_months': age,
                'age_valid': age_valid if risk != 'fraudulent' else random.random() > 0.4,
                'owner_iin_bin': iin_bin,
                'owner_match': True,
                'previously_subsidized': risk == 'fraudulent' and random.random() > 0.5,
                'vet_status': 'healthy' if risk != 'risky' else random.choice(['healthy', 'quarantine']),
                'last_vet_check': (date.today() - timedelta(days=random.randint(1, 90))).isoformat(),
                'registration_date': (date.today() - timedelta(days=random.randint(30, 730))).isoformat(),
            })

        rejected = sum(1 for a in animals if not a['age_valid'] or a['previously_subsidized'])
        return {
            'verified': True,
            'animals': animals,
            'total_verified': len(animals) - rejected,
            'total_rejected': rejected,
            'total_count': count,  # Actual total (animals list may be capped)
            'rejection_reasons': [],
        }

    def _gen_is_esf(self, risk, iin_bin, current_rows):
        amounts = [r['amount'] for r in current_rows if r['amount'] and r['amount'] > 0]
        total_amount = sum(amounts) if amounts else random.randint(500_000, 5_000_000)

        inv_count = min(len(amounts), 5) if amounts else random.randint(1, 3)
        invoices = []
        for i in range(max(1, inv_count)):
            amount = amounts[i] if i < len(amounts) else random.randint(500_000, 5_000_000)
            invoices.append({
                'esf_number': f'ESF-2025-{random.randint(1000000, 9999999)}',
                'date': f'2025-{random.randint(1, 3):02d}-{random.randint(1, 28):02d}',
                'seller_bin': generate_bin(),
                'seller_name': f'ТОО "{random.choice(FARM_NAMES)}"',
                'buyer_iin_bin': iin_bin,
                'total_amount': int(amount * random.uniform(1.5, 3.0)),  # ESF > subsidy amount
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

        plot_count = random.randint(1, 4)
        plots = []
        for _ in range(plot_count):
            area = round(random.uniform(10, 1000), 1)
            plots.append({
                'cadastral_number': f'{random.randint(1, 99):02d}-{random.randint(100, 999)}-{random.randint(100, 999)}-{random.randint(100, 999)}',
                'area_hectares': area,
                'purpose': 'сельскохозяйственное назначение',
                'sub_purpose': random.choice(['пастбище', 'пашня', 'сенокос', 'выпас']),
                'region': region,
                'district': district or '',
                'ownership_type': random.choice(['собственность', 'аренда', 'долгосрочная аренда']),
                'registration_date': f'{random.randint(2010, 2023)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}',
            })

        return {
            'has_agricultural_land': True,
            'plots': plots,
            'total_agricultural_area': round(sum(p['area_hectares'] for p in plots), 1),
        }

    def _gen_treasury(self, risk, history):
        if risk in ('risky', 'fraudulent') and random.random() > 0.5:
            return {'payments': []}

        # Generate treasury payments from successful history
        payments = []
        for h in history:
            if h['obligations_met'] and h['status'] == 'executed':
                payments.append({
                    'payment_id': f'PAY-{h["year"]}-{random.randint(10000, 99999)}',
                    'amount': h['amount'],
                    'status': 'completed',
                    'paid_date': f'{h["year"]}-{random.randint(3, 12):02d}-{random.randint(1, 28):02d}',
                    'treasury_reference': f'TR-{h["year"]}-{random.randint(10000, 99999)}',
                })

        return {'payments': payments}
