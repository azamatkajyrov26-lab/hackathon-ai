"""
Management command to create test users and EmulatedEntity records
for each YES/NO scenario branch in the AS-IS subsidy application flow.

Usage:
    python manage.py create_test_scenarios
"""

import datetime

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.emulator.models import EmulatedEntity
from apps.scoring.models import Applicant, UserProfile


# ---------------------------------------------------------------------------
# Reusable defaults for the 7 system JSON blobs
# ---------------------------------------------------------------------------

def _base_giss(*, registered=True, blocked=False, block_reason='',
               obligations_met=True, consecutive_decline_years=0,
               gross_prev=45_000_000, gross_before=40_000_000):
    growth = round((gross_prev - gross_before) / gross_before * 100, 1) if gross_before else 0
    return {
        'registered': registered,
        'gross_production_previous_year': gross_prev,
        'gross_production_year_before': gross_before,
        'growth_rate': growth,
        'obligations_met': obligations_met,
        'total_subsidies_received': 3_500_000,
        'consecutive_decline_years': consecutive_decline_years,
        'blocked': blocked,
        'block_reason': block_reason,
    }


def _base_ias_rszh(*, registered=True):
    return {
        'registered': registered,
        'registration_date': '2020-03-10',
        'entity_type': 'individual',
        'name': 'Тестовое хозяйство',
        'region': 'Акмолинская область',
        'district': 'Целиноградский район',
        'subsidy_history': [
            {'year': 2024, 'direction': 'Животноводство', 'amount': 1_200_000, 'status': 'paid'},
        ],
        'total_subsidies_history': 1_200_000,
        'pending_returns': 0,
    }


def _base_easu(*, is_spk=False, spk_name='', spk_members=None):
    return {
        'has_account_number': True,
        'account_numbers': ['KZ12345678901234567890'],
        'is_spk': is_spk,
        'spk_name': spk_name,
        'spk_members': spk_members or [],
    }


def _base_is_iszh(*, animals=None):
    if animals is None:
        animals = [
            {
                'tag': 'KZ-ACM-00001',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2025-05-15',
                'age_months': 10,
                'age_valid': True,
                'weight_kg': 320,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
            {
                'tag': 'KZ-ACM-00002',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2025-03-20',
                'age_months': 12,
                'age_valid': True,
                'weight_kg': 350,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
        ]
    total_verified = sum(1 for a in animals if a.get('verified'))
    total_rejected = len(animals) - total_verified
    return {
        'verified': True,
        'animals': animals,
        'total_verified': total_verified,
        'total_rejected': total_rejected,
    }


def _base_is_esf(*, invoices=None):
    if invoices is None:
        invoices = [
            {
                'number': 'ESF-2026-001234',
                'date': '2026-01-20',
                'seller_bin': '123456789012',
                'seller_name': 'ТОО "АгроСнаб"',
                'buyer_iin': '',
                'amount': 4_800_000,
                'status': 'confirmed',
                'items': [
                    {'name': 'КРС Ангус тёлка', 'quantity': 2, 'unit_price': 2_400_000}
                ],
                'origin': 'domestic',
            },
        ]
    total = sum(inv.get('amount', 0) for inv in invoices)
    return {
        'invoices': invoices,
        'total_amount': total,
        'invoice_count': len(invoices),
    }


def _base_egkn(*, has_land=True):
    plots = []
    if has_land:
        plots = [
            {
                'cadastral_number': '01-123-456-789',
                'area_hectares': 120.5,
                'purpose': 'Сельскохозяйственное',
                'ownership_type': 'Аренда',
                'valid_until': '2030-12-31',
            },
        ]
    return {
        'has_agricultural_land': has_land,
        'plots': plots,
        'total_agricultural_area': sum(p['area_hectares'] for p in plots),
    }


def _base_treasury():
    return {
        'payments': [
            {
                'date': '2025-06-15',
                'amount': 1_200_000,
                'purpose': 'Субсидия за приобретение КРС',
                'status': 'completed',
                'reference': 'TR-2025-00456',
            },
        ],
    }


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

REGION = 'Акмолинская область'
DISTRICT = 'Целиноградский район'
REG_DATE = datetime.date(2020, 1, 15)

SCENARIOS = [
    # 1. GISS Registration
    {
        'username': 'test_giss_yes',
        'iin_bin': '111111111111',
        'name': 'Тест ГИСС — зарегистрирован',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(registered=True),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_giss_no',
        'iin_bin': '111111111112',
        'name': 'Тест ГИСС — не зарегистрирован',
        'entity_type': 'individual',
        'risk_profile': 'risky',
        'giss_data': _base_giss(registered=False),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 2. IAS RSZh Registration
    {
        'username': 'test_ias_yes',
        'iin_bin': '222222222221',
        'name': 'Тест ИАС РСЖ — зарегистрирован',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(registered=True),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_ias_no',
        'iin_bin': '222222222222',
        'name': 'Тест ИАС РСЖ — не зарегистрирован',
        'entity_type': 'individual',
        'risk_profile': 'risky',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(registered=False),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 3. SPK / Non-SPK
    {
        'username': 'test_spk_yes',
        'iin_bin': '333333333331',
        'name': 'СПК "Тест Береке"',
        'entity_type': 'cooperative',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(
            is_spk=True,
            spk_name='СПК "Тест Береке"',
            spk_members=[{'name': 'Иванов', 'iin': '444444444444'}],
        ),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_spk_no',
        'iin_bin': '333333333332',
        'name': 'Тест не-СПК индивидуал',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(is_spk=False),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 4. Has Agricultural Land (ЕГКН)
    {
        'username': 'test_land_yes',
        'iin_bin': '444444444441',
        'name': 'Тест земля — есть с/х участок',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(has_land=True),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_land_no',
        'iin_bin': '444444444442',
        'name': 'Тест земля — нет с/х участка',
        'entity_type': 'individual',
        'risk_profile': 'risky',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(has_land=False),
        'treasury_data': _base_treasury(),
    },

    # 5. Has ESF (ИС ЭСФ)
    {
        'username': 'test_esf_yes',
        'iin_bin': '555555555551',
        'name': 'Тест ЭСФ — есть подтверждённые',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_esf_no',
        'iin_bin': '555555555552',
        'name': 'Тест ЭСФ — нет счетов-фактур',
        'entity_type': 'individual',
        'risk_profile': 'risky',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(invoices=[]),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 6. Blocked (ГИСС)
    {
        'username': 'test_block_yes',
        'iin_bin': '666666666661',
        'name': 'Тест блокировка — не заблокирован',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(blocked=False),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_block_no',
        'iin_bin': '666666666662',
        'name': 'Тест блокировка — заблокирован',
        'entity_type': 'individual',
        'risk_profile': 'fraudulent',
        'giss_data': _base_giss(blocked=True, block_reason='Невыполнение обязательств'),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 7. Import vs Domestic
    {
        'username': 'test_import',
        'iin_bin': '777777777771',
        'name': 'Тест импорт — зарубежный скот',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(animals=[
            {
                'tag': 'KZ-IMP-00001',
                'species': 'КРС',
                'breed': 'Герефорд',
                'gender': 'female',
                'birth_date': '2025-04-10',
                'age_months': 11,
                'age_valid': True,
                'weight_kg': 340,
                'origin': 'import',
                'country_of_origin': 'Австралия',
                'previously_subsidized': False,
                'verified': True,
            },
        ]),
        'is_esf_data': _base_is_esf(invoices=[
            {
                'number': 'ESF-2026-IMP-001',
                'date': '2026-01-10',
                'seller_bin': '999888777666',
                'seller_name': 'Australian Genetics Pty Ltd',
                'buyer_iin': '777777777771',
                'amount': 8_500_000,
                'status': 'confirmed',
                'items': [
                    {'name': 'КРС Герефорд тёлка (импорт)', 'quantity': 1, 'unit_price': 8_500_000}
                ],
                'origin': 'import',
            },
        ]),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_domestic',
        'iin_bin': '777777777772',
        'name': 'Тест отечественный — местный скот',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(animals=[
            {
                'tag': 'KZ-DOM-00001',
                'species': 'КРС',
                'breed': 'Казахская белоголовая',
                'gender': 'female',
                'birth_date': '2025-06-01',
                'age_months': 9,
                'age_valid': True,
                'weight_kg': 300,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
        ]),
        'is_esf_data': _base_is_esf(invoices=[
            {
                'number': 'ESF-2026-DOM-001',
                'date': '2026-02-05',
                'seller_bin': '123456789012',
                'seller_name': 'КХ "Жайлау"',
                'buyer_iin': '777777777772',
                'amount': 2_800_000,
                'status': 'confirmed',
                'items': [
                    {'name': 'КРС Казахская белоголовая тёлка', 'quantity': 1, 'unit_price': 2_800_000}
                ],
                'origin': 'domestic',
            },
        ]),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 8. Obligations Met
    {
        'username': 'test_obl_yes',
        'iin_bin': '888888888881',
        'name': 'Тест обязательства — выполнены',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(obligations_met=True, consecutive_decline_years=0),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_obl_no',
        'iin_bin': '888888888882',
        'name': 'Тест обязательства — не выполнены',
        'entity_type': 'individual',
        'risk_profile': 'risky',
        'giss_data': _base_giss(obligations_met=False, consecutive_decline_years=2),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 9. Animals age valid (ИС ИСЖ)
    {
        'username': 'test_age_yes',
        'iin_bin': '999999999991',
        'name': 'Тест возраст — допустимый',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(animals=[
            {
                'tag': 'KZ-AGE-00001',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2025-07-01',
                'age_months': 8,
                'age_valid': True,
                'weight_kg': 280,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
            {
                'tag': 'KZ-AGE-00002',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2024-09-15',
                'age_months': 18,
                'age_valid': True,
                'weight_kg': 420,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
        ]),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_age_no',
        'iin_bin': '999999999992',
        'name': 'Тест возраст — слишком молодые',
        'entity_type': 'individual',
        'risk_profile': 'risky',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(animals=[
            {
                'tag': 'KZ-AGE-00003',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2026-01-01',
                'age_months': 3,
                'age_valid': False,
                'weight_kg': 120,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
        ]),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },

    # 10. Previously subsidized animals
    {
        'username': 'test_subsid_yes',
        'iin_bin': '101010101011',
        'name': 'Тест субсидирование — ранее не получали',
        'entity_type': 'individual',
        'risk_profile': 'clean',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(animals=[
            {
                'tag': 'KZ-SUB-00001',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2025-05-01',
                'age_months': 10,
                'age_valid': True,
                'weight_kg': 310,
                'origin': 'domestic',
                'previously_subsidized': False,
                'verified': True,
            },
        ]),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
    {
        'username': 'test_subsid_no',
        'iin_bin': '101010101012',
        'name': 'Тест субсидирование — уже получали',
        'entity_type': 'individual',
        'risk_profile': 'fraudulent',
        'giss_data': _base_giss(),
        'ias_rszh_data': _base_ias_rszh(),
        'easu_data': _base_easu(),
        'is_iszh_data': _base_is_iszh(animals=[
            {
                'tag': 'KZ-SUB-00002',
                'species': 'КРС',
                'breed': 'Ангус',
                'gender': 'female',
                'birth_date': '2025-05-01',
                'age_months': 10,
                'age_valid': True,
                'weight_kg': 310,
                'origin': 'domestic',
                'previously_subsidized': True,
                'subsidy_date': '2025-08-20',
                'subsidy_amount': 1_200_000,
                'verified': True,
            },
        ]),
        'is_esf_data': _base_is_esf(),
        'egkn_data': _base_egkn(),
        'treasury_data': _base_treasury(),
    },
]


class Command(BaseCommand):
    help = (
        'Создаёт тестовых пользователей, EmulatedEntity и Applicant '
        'для каждого YES/NO сценария AS-IS потока субсидирования.'
    )

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for sc in SCENARIOS:
            iin_bin = sc['iin_bin']
            username = sc['username']
            entity_name = sc['name']
            entity_type = sc['entity_type']

            # --- User ---
            user, user_created = User.objects.update_or_create(
                username=username,
                defaults={
                    'first_name': entity_name[:30],
                    'last_name': 'Тестовый',
                    'email': f'{username}@test.local',
                    'is_active': True,
                },
            )
            user.set_password('test123')
            user.save()

            # --- UserProfile ---
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'role': 'applicant',
                    'iin_bin': iin_bin,
                    'region': REGION,
                    'district': DISTRICT,
                    'organization': entity_name,
                    'phone': '+77001234567',
                },
            )

            # --- EmulatedEntity ---
            _, entity_created = EmulatedEntity.objects.update_or_create(
                iin_bin=iin_bin,
                defaults={
                    'name': entity_name,
                    'entity_type': entity_type,
                    'region': REGION,
                    'district': DISTRICT,
                    'registration_date': REG_DATE,
                    'risk_profile': sc['risk_profile'],
                    'giss_data': sc['giss_data'],
                    'ias_rszh_data': sc['ias_rszh_data'],
                    'easu_data': sc['easu_data'],
                    'is_iszh_data': sc['is_iszh_data'],
                    'is_esf_data': sc['is_esf_data'],
                    'egkn_data': sc['egkn_data'],
                    'treasury_data': sc['treasury_data'],
                },
            )

            # --- Applicant ---
            is_blocked = sc['giss_data'].get('blocked', False)
            block_reason = sc['giss_data'].get('block_reason', '')
            Applicant.objects.update_or_create(
                iin_bin=iin_bin,
                defaults={
                    'name': entity_name,
                    'entity_type': entity_type,
                    'region': REGION,
                    'district': DISTRICT,
                    'address': f'{REGION}, {DISTRICT}',
                    'phone': '+77001234567',
                    'email': f'{username}@test.local',
                    'bank_account': 'KZ12345678901234567890',
                    'bank_name': 'АО "Казкоммерцбанк"',
                    'registration_date': REG_DATE,
                    'is_blocked': is_blocked,
                    'block_reason': block_reason,
                },
            )

            if entity_created:
                created_count += 1
            else:
                updated_count += 1

            self.stdout.write(
                f'  {"[NEW]" if entity_created else "[UPD]"} '
                f'{username} / {iin_bin} — {entity_name}'
            )

        self.stdout.write(self.style.SUCCESS(
            f'\nГотово: {created_count} создано, {updated_count} обновлено '
            f'(всего {len(SCENARIOS)} сценариев).'
        ))
