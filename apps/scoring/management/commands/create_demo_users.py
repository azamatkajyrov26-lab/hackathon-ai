"""
Создаёт демо-пользователей для проверки основных сценариев системы.

Usage:
    python manage.py create_demo_users
"""
import datetime
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.emulator.models import EmulatedEntity, RFIDMonitoring
from apps.scoring.models import Applicant, UserProfile


REG_DATE = datetime.date(2020, 1, 15)
REGION = 'Акмолинская область'
DISTRICT = 'Целиноградский район'


DEMO_USERS = [
    # ============================================================
    # 1. ИП Софья Абрамова — новенькая, ничего нет
    #    ГИСС не зарег, ИАС РСЖ не зарег, нет земли, нет животных
    #    Ожидание: ОТКАЗ по hard filters
    # ============================================================
    {
        'username': 'sofiya',
        'password': 'demo123',
        'first_name': 'Софья',
        'last_name': 'Абрамова',
        'iin_bin': '950315400123',
        'entity_type': 'individual',
        'entity_name': 'ИП Абрамова С.',
        'risk_profile': 'risky',
        'region': REGION,
        'district': DISTRICT,
        'phone': '+7 (701) 111-22-33',
        'organization': 'ИП Абрамова С.',
        'giss_data': {
            'registered': False,
            'gross_production_previous_year': 0,
            'gross_production_year_before': 0,
            'growth_rate': 0,
            'obligations_met': True,
            'total_subsidies_received': 0,
            'consecutive_decline_years': 0,
            'blocked': False,
            'block_reason': '',
        },
        'ias_rszh_data': {
            'registered': False,
            'registration_date': '',
            'entity_type': 'individual',
            'name': 'ИП Абрамова С.',
            'region': REGION,
            'district': DISTRICT,
            'subsidy_history': [],
            'total_subsidies_history': 0,
            'pending_returns': 0,
        },
        'easu_data': {
            'has_account_number': False,
            'account_numbers': [],
            'is_spk': False,
            'spk_name': '',
            'spk_members': [],
        },
        'is_iszh_data': {
            'verified': False,
            'animals': [],
            'total_verified': 0,
            'total_rejected': 0,
        },
        'is_esf_data': {
            'invoices': [],
            'total_amount': 0,
            'invoice_count': 0,
        },
        'egkn_data': {
            'has_agricultural_land': False,
            'plots': [],
            'total_agricultural_area': 0,
        },
        'treasury_data': {'payments': []},
    },

    # ============================================================
    # 2. ИП Богдан Ковалёв — опытный, состоит в СПК, несколько заявок
    #    Зарегистрирован везде, член СПК "Береке Астана"
    #    Есть история субсидий (3 заявки), обязательства выполнены
    #    Ожидание: ОДОБРЕНИЕ, высокий скор
    # ============================================================
    {
        'username': 'bogdan',
        'password': 'demo123',
        'first_name': 'Богдан',
        'last_name': 'Ковалёв',
        'iin_bin': '880720300456',
        'entity_type': 'cooperative',
        'entity_name': 'СПК "Береке Астана"',
        'risk_profile': 'clean',
        'region': REGION,
        'district': DISTRICT,
        'phone': '+7 (702) 333-44-55',
        'organization': 'СПК "Береке Астана"',
        'giss_data': {
            'registered': True,
            'gross_production_previous_year': 85_000_000,
            'gross_production_year_before': 72_000_000,
            'growth_rate': 18.1,
            'obligations_met': True,
            'total_subsidies_received': 12_500_000,
            'consecutive_decline_years': 0,
            'blocked': False,
            'block_reason': '',
        },
        'ias_rszh_data': {
            'registered': True,
            'registration_date': '2018-06-10',
            'entity_type': 'cooperative',
            'name': 'СПК "Береке Астана"',
            'region': REGION,
            'district': DISTRICT,
            'subsidy_history': [
                {'year': 2024, 'type': 'Приобретение маточного поголовья КРС', 'amount': 4_500_000, 'heads': 30, 'status': 'executed', 'obligations_met': True},
                {'year': 2023, 'type': 'Удешевление производства молока', 'amount': 3_200_000, 'heads': 0, 'status': 'executed', 'obligations_met': True},
                {'year': 2022, 'type': 'Приобретение племенных овец', 'amount': 2_800_000, 'heads': 50, 'status': 'executed', 'obligations_met': True},
            ],
            'total_subsidies_history': 10_500_000,
            'pending_returns': 0,
        },
        'easu_data': {
            'has_account_number': True,
            'account_numbers': ['KZ86125KZT2052344789', 'KZ43125KZT2098712345'],
            'is_spk': True,
            'spk_name': 'СПК "Береке Астана"',
            'spk_members': [
                {'name': 'Ковалёв Б.И.', 'iin': '880720300456'},
                {'name': 'Серикбаев А.К.', 'iin': '910504200789'},
                {'name': 'Тулегенова Г.М.', 'iin': '870119500321'},
                {'name': 'Жанибеков Е.Р.', 'iin': '930812100654'},
            ],
        },
        'is_iszh_data': {
            'verified': True,
            'animals': [
                {'tag_number': 'KZ90001001', 'type': 'cattle', 'breed': 'Ангусская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-01-10', 'age_months': 14, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-15', 'registration_date': '2025-02-01', 'rfid_tag': 'RFID-9000101', 'rfid_active': True, 'rfid_last_scan': '2026-03-31T08:15:00', 'rfid_scan_count_30d': 52},
                {'tag_number': 'KZ90001002', 'type': 'cattle', 'breed': 'Ангусская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-03-05', 'age_months': 12, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-15', 'registration_date': '2025-04-01', 'rfid_tag': 'RFID-9000102', 'rfid_active': True, 'rfid_last_scan': '2026-03-31T09:20:00', 'rfid_scan_count_30d': 48},
                {'tag_number': 'KZ90001003', 'type': 'cattle', 'breed': 'Герефордская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-05-20', 'age_months': 10, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-20', 'registration_date': '2025-06-01', 'rfid_tag': 'RFID-9000103', 'rfid_active': True, 'rfid_last_scan': '2026-03-31T07:45:00', 'rfid_scan_count_30d': 55},
                {'tag_number': 'KZ90001004', 'type': 'cattle', 'breed': 'Казахская белоголовая', 'category': 'bull', 'sex': 'male', 'birth_date': '2025-02-15', 'age_months': 13, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-10', 'registration_date': '2025-03-01', 'rfid_tag': 'RFID-9000104', 'rfid_active': True, 'rfid_last_scan': '2026-03-31T10:00:00', 'rfid_scan_count_30d': 41},
                {'tag_number': 'KZ90001005', 'type': 'cattle', 'breed': 'Ангусская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2024-08-10', 'age_months': 19, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': True, 'vet_status': 'healthy', 'last_vet_check': '2026-01-20', 'registration_date': '2024-09-01', 'rfid_tag': 'RFID-9000105', 'rfid_active': True, 'rfid_last_scan': '2026-03-30T14:30:00', 'rfid_scan_count_30d': 38},
                {'tag_number': 'KZ90001006', 'type': 'sheep', 'breed': 'Эдильбаевская', 'category': 'ewe', 'sex': 'female', 'birth_date': '2025-04-01', 'age_months': 11, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-25', 'registration_date': '2025-05-01', 'rfid_tag': 'RFID-9000106', 'rfid_active': True, 'rfid_last_scan': '2026-03-31T06:00:00', 'rfid_scan_count_30d': 44},
                {'tag_number': 'KZ90001007', 'type': 'sheep', 'breed': 'Эдильбаевская', 'category': 'ewe', 'sex': 'female', 'birth_date': '2025-06-15', 'age_months': 9, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-01', 'registration_date': '2025-07-01', 'rfid_tag': None, 'rfid_active': False, 'rfid_last_scan': None, 'rfid_scan_count_30d': 0},
                {'tag_number': 'KZ90001008', 'type': 'sheep', 'breed': 'Меринос', 'category': 'ram', 'sex': 'male', 'birth_date': '2025-01-20', 'age_months': 14, 'age_valid': True, 'owner_iin_bin': '880720300456', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-28', 'registration_date': '2025-02-15', 'rfid_tag': 'RFID-9000108', 'rfid_active': False, 'rfid_last_scan': '2026-03-15T11:20:00', 'rfid_scan_count_30d': 8},
            ],
            'total_verified': 7,
            'total_rejected': 1,
        },
        'is_esf_data': {
            'invoices': [
                {'esf_number': 'ESF-2026-0078901', 'date': '2026-01-15', 'seller_bin': '120340567890', 'seller_name': 'ТОО "АгроГенетика Казахстан"', 'buyer_iin_bin': '880720300456', 'total_amount': 6_000_000, 'items': [{'description': 'Племенные тёлки ангусской породы', 'quantity': 4, 'unit': 'голова', 'unit_price': 1_500_000, 'amount': 6_000_000}], 'status': 'confirmed', 'payment_confirmed': True},
                {'esf_number': 'ESF-2026-0078902', 'date': '2026-02-20', 'seller_bin': '120340567890', 'seller_name': 'ТОО "АгроГенетика Казахстан"', 'buyer_iin_bin': '880720300456', 'total_amount': 2_500_000, 'items': [{'description': 'Племенные овцы эдильбаевской породы', 'quantity': 50, 'unit': 'голова', 'unit_price': 50_000, 'amount': 2_500_000}], 'status': 'confirmed', 'payment_confirmed': True},
            ],
            'total_amount': 8_500_000,
            'invoice_count': 2,
        },
        'egkn_data': {
            'has_agricultural_land': True,
            'plots': [
                {'cadastral_number': '01-301-145-789', 'area_hectares': 250.0, 'purpose': 'сельскохозяйственное назначение', 'sub_purpose': 'пастбище', 'region': REGION, 'district': DISTRICT, 'ownership_type': 'собственность', 'registration_date': '2018-04-15'},
                {'cadastral_number': '01-301-145-790', 'area_hectares': 120.5, 'purpose': 'сельскохозяйственное назначение', 'sub_purpose': 'пашня', 'region': REGION, 'district': DISTRICT, 'ownership_type': 'аренда', 'registration_date': '2019-08-20'},
            ],
            'total_agricultural_area': 370.5,
        },
        'treasury_data': {
            'payments': [
                {'payment_id': 'PAY-2024-45678', 'amount': 4_500_000, 'status': 'completed', 'paid_date': '2024-06-15', 'treasury_reference': 'TR-2024-45678'},
                {'payment_id': 'PAY-2023-34567', 'amount': 3_200_000, 'status': 'completed', 'paid_date': '2023-09-20', 'treasury_reference': 'TR-2023-34567'},
            ],
        },
    },

    # ============================================================
    # 3. ИП Нурсултан Жумабаев — готов к подаче заявки
    #    Всё зарегистрировано, чистая история, есть животные и земля
    #    Отечественный скот, стандартный пакет документов
    #    Ожидание: ОДОБРЕНИЕ, средний-высокий скор
    # ============================================================
    {
        'username': 'nursultan',
        'password': 'demo123',
        'first_name': 'Нурсултан',
        'last_name': 'Жумабаев',
        'iin_bin': '901105200789',
        'entity_type': 'individual',
        'entity_name': 'КХ "Жумабаев Н."',
        'risk_profile': 'clean',
        'region': 'Костанайская область',
        'district': 'Костанайский район',
        'phone': '+7 (705) 777-88-99',
        'organization': 'КХ "Жумабаев Н."',
        'giss_data': {
            'registered': True,
            'gross_production_previous_year': 32_000_000,
            'gross_production_year_before': 28_000_000,
            'growth_rate': 14.3,
            'obligations_met': True,
            'total_subsidies_received': 2_100_000,
            'consecutive_decline_years': 0,
            'blocked': False,
            'block_reason': '',
        },
        'ias_rszh_data': {
            'registered': True,
            'registration_date': '2020-02-15',
            'entity_type': 'individual',
            'name': 'КХ "Жумабаев Н."',
            'region': 'Костанайская область',
            'district': 'Костанайский район',
            'subsidy_history': [
                {'year': 2024, 'type': 'Селекционная работа с маточным поголовьем КРС', 'amount': 2_100_000, 'heads': 15, 'status': 'executed', 'obligations_met': True},
            ],
            'total_subsidies_history': 2_100_000,
            'pending_returns': 0,
        },
        'easu_data': {
            'has_account_number': True,
            'account_numbers': ['KZ76125KZT2031298765'],
            'is_spk': False,
            'spk_name': '',
            'spk_members': [],
        },
        'is_iszh_data': {
            'verified': True,
            'animals': [
                {'tag_number': 'KZ80002001', 'type': 'cattle', 'breed': 'Казахская белоголовая', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-04-10', 'age_months': 11, 'age_valid': True, 'owner_iin_bin': '901105200789', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-05', 'registration_date': '2025-05-01', 'rfid_tag': 'RFID-8000201', 'rfid_active': True, 'rfid_last_scan': '2026-03-31T07:30:00', 'rfid_scan_count_30d': 35},
                {'tag_number': 'KZ80002002', 'type': 'cattle', 'breed': 'Казахская белоголовая', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-06-20', 'age_months': 9, 'age_valid': True, 'owner_iin_bin': '901105200789', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-05', 'registration_date': '2025-07-15', 'rfid_tag': 'RFID-8000202', 'rfid_active': True, 'rfid_last_scan': '2026-03-30T16:45:00', 'rfid_scan_count_30d': 29},
                {'tag_number': 'KZ80002003', 'type': 'cattle', 'breed': 'Герефордская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-02-01', 'age_months': 13, 'age_valid': True, 'owner_iin_bin': '901105200789', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-01', 'registration_date': '2025-03-01', 'rfid_tag': None, 'rfid_active': False, 'rfid_last_scan': None, 'rfid_scan_count_30d': 0},
            ],
            'total_verified': 3,
            'total_rejected': 0,
        },
        'is_esf_data': {
            'invoices': [
                {'esf_number': 'ESF-2026-0091234', 'date': '2026-02-10', 'seller_bin': '150640789012', 'seller_name': 'ТОО "Костанай-Агро"', 'buyer_iin_bin': '901105200789', 'total_amount': 4_200_000, 'items': [{'description': 'Тёлки казахской белоголовой породы', 'quantity': 3, 'unit': 'голова', 'unit_price': 1_400_000, 'amount': 4_200_000}], 'status': 'confirmed', 'payment_confirmed': True},
            ],
            'total_amount': 4_200_000,
            'invoice_count': 1,
        },
        'egkn_data': {
            'has_agricultural_land': True,
            'plots': [
                {'cadastral_number': '04-210-087-345', 'area_hectares': 180.0, 'purpose': 'сельскохозяйственное назначение', 'sub_purpose': 'пастбище', 'region': 'Костанайская область', 'district': 'Костанайский район', 'ownership_type': 'собственность', 'registration_date': '2020-05-10'},
            ],
            'total_agricultural_area': 180.0,
        },
        'treasury_data': {
            'payments': [
                {'payment_id': 'PAY-2024-56789', 'amount': 2_100_000, 'status': 'completed', 'paid_date': '2024-07-20', 'treasury_reference': 'TR-2024-56789'},
            ],
        },
    },

    # ============================================================
    # 4. ТОО "Дала Агро" (Марат Серикбаев) — заблокирован в ГИСС
    #    Был зарег, но заблокирован за невыполнение обязательств
    #    Ожидание: ОТКАЗ (blocked)
    # ============================================================
    {
        'username': 'marat',
        'password': 'demo123',
        'first_name': 'Марат',
        'last_name': 'Серикбаев',
        'iin_bin': '850930100234',
        'entity_type': 'legal',
        'entity_name': 'ТОО "Дала Агро"',
        'risk_profile': 'fraudulent',
        'region': 'Туркестанская область',
        'district': 'Сайрамский район',
        'phone': '+7 (708) 555-66-77',
        'organization': 'ТОО "Дала Агро"',
        'giss_data': {
            'registered': True,
            'gross_production_previous_year': 18_000_000,
            'gross_production_year_before': 25_000_000,
            'growth_rate': -28.0,
            'obligations_met': False,
            'total_subsidies_received': 8_000_000,
            'consecutive_decline_years': 2,
            'blocked': True,
            'block_reason': 'Невыполнение встречных обязательств 2 года подряд (снижение валовой продукции на 28%)',
        },
        'ias_rszh_data': {
            'registered': True,
            'registration_date': '2017-09-01',
            'entity_type': 'legal',
            'name': 'ТОО "Дала Агро"',
            'region': 'Туркестанская область',
            'district': 'Сайрамский район',
            'subsidy_history': [
                {'year': 2024, 'type': 'Приобретение маточного поголовья КРС', 'amount': 5_000_000, 'heads': 20, 'status': 'pending', 'obligations_met': False},
                {'year': 2023, 'type': 'Удешевление стоимости говядины', 'amount': 3_000_000, 'heads': 0, 'status': 'pending', 'obligations_met': False},
            ],
            'total_subsidies_history': 8_000_000,
            'pending_returns': 3,
        },
        'easu_data': {
            'has_account_number': True,
            'account_numbers': ['KZ54125KZT2076543210'],
            'is_spk': False,
            'spk_name': '',
            'spk_members': [],
        },
        'is_iszh_data': {
            'verified': True,
            'animals': [
                {'tag_number': 'KZ70003001', 'type': 'cattle', 'breed': 'Симментальская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-07-10', 'age_months': 8, 'age_valid': True, 'owner_iin_bin': '850930100234', 'owner_match': True, 'previously_subsidized': True, 'vet_status': 'healthy', 'last_vet_check': '2026-01-10', 'registration_date': '2025-08-01', 'rfid_tag': 'RFID-7000301', 'rfid_active': False, 'rfid_last_scan': '2026-02-10T12:00:00', 'rfid_scan_count_30d': 2},
                {'tag_number': 'KZ70003002', 'type': 'cattle', 'breed': 'Симментальская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-09-01', 'age_months': 6, 'age_valid': False, 'owner_iin_bin': '850930100234', 'owner_match': True, 'previously_subsidized': True, 'vet_status': 'quarantine', 'last_vet_check': '2026-02-01', 'registration_date': '2025-10-01', 'rfid_tag': None, 'rfid_active': False, 'rfid_last_scan': None, 'rfid_scan_count_30d': 0},
            ],
            'total_verified': 0,
            'total_rejected': 2,
        },
        'is_esf_data': {
            'invoices': [
                {'esf_number': 'ESF-2025-0045678', 'date': '2025-11-05', 'seller_bin': '180250345678', 'seller_name': 'ТОО "Южная ферма"', 'buyer_iin_bin': '850930100234', 'total_amount': 3_000_000, 'items': [{'description': 'КРС симментальской породы', 'quantity': 2, 'unit': 'голова', 'unit_price': 1_500_000, 'amount': 3_000_000}], 'status': 'draft', 'payment_confirmed': False},
            ],
            'total_amount': 3_000_000,
            'invoice_count': 1,
        },
        'egkn_data': {
            'has_agricultural_land': True,
            'plots': [
                {'cadastral_number': '13-501-200-111', 'area_hectares': 50.0, 'purpose': 'сельскохозяйственное назначение', 'sub_purpose': 'пастбище', 'region': 'Туркестанская область', 'district': 'Сайрамский район', 'ownership_type': 'аренда', 'registration_date': '2017-11-01'},
            ],
            'total_agricultural_area': 50.0,
        },
        'treasury_data': {'payments': []},
    },

    # ============================================================
    # 5. ИП Айгуль Тастемирова — импортный скот из-за рубежа
    #    Всё зарег, покупает импортных герефордов
    #    Ожидание: ОДОБРЕНИЕ, нужны доп. документы (таможня, карантин)
    # ============================================================
    {
        'username': 'aigul',
        'password': 'demo123',
        'first_name': 'Айгуль',
        'last_name': 'Тастемирова',
        'iin_bin': '920812500567',
        'entity_type': 'individual',
        'entity_name': 'ИП Тастемирова А.',
        'risk_profile': 'clean',
        'region': 'Алматинская область',
        'district': 'Талгарский район',
        'phone': '+7 (707) 999-00-11',
        'organization': 'ИП Тастемирова А.',
        'giss_data': {
            'registered': True,
            'gross_production_previous_year': 55_000_000,
            'gross_production_year_before': 48_000_000,
            'growth_rate': 14.6,
            'obligations_met': True,
            'total_subsidies_received': 5_000_000,
            'consecutive_decline_years': 0,
            'blocked': False,
            'block_reason': '',
        },
        'ias_rszh_data': {
            'registered': True,
            'registration_date': '2019-04-20',
            'entity_type': 'individual',
            'name': 'ИП Тастемирова А.',
            'region': 'Алматинская область',
            'district': 'Талгарский район',
            'subsidy_history': [
                {'year': 2024, 'type': 'Приобретение маточного поголовья КРС — импорт', 'amount': 5_000_000, 'heads': 10, 'status': 'executed', 'obligations_met': True},
            ],
            'total_subsidies_history': 5_000_000,
            'pending_returns': 0,
        },
        'easu_data': {
            'has_account_number': True,
            'account_numbers': ['KZ98125KZT2041567890'],
            'is_spk': False,
            'spk_name': '',
            'spk_members': [],
        },
        'is_iszh_data': {
            'verified': True,
            'animals': [
                {'tag_number': 'KZ60004001', 'type': 'cattle', 'breed': 'Герефордская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-05-01', 'age_months': 10, 'age_valid': True, 'owner_iin_bin': '920812500567', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-10', 'registration_date': '2025-06-15', 'rfid_tag': 'RFID-6000401', 'rfid_active': True, 'rfid_last_scan': '2026-04-01T06:30:00', 'rfid_scan_count_30d': 58},
                {'tag_number': 'KZ60004002', 'type': 'cattle', 'breed': 'Герефордская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-04-15', 'age_months': 11, 'age_valid': True, 'owner_iin_bin': '920812500567', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-10', 'registration_date': '2025-06-15', 'rfid_tag': 'RFID-6000402', 'rfid_active': True, 'rfid_last_scan': '2026-04-01T06:32:00', 'rfid_scan_count_30d': 55},
                {'tag_number': 'KZ60004003', 'type': 'cattle', 'breed': 'Шароле', 'category': 'bull', 'sex': 'male', 'birth_date': '2024-12-01', 'age_months': 15, 'age_valid': True, 'owner_iin_bin': '920812500567', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-10', 'registration_date': '2025-02-01', 'rfid_tag': 'RFID-6000403', 'rfid_active': True, 'rfid_last_scan': '2026-04-01T06:35:00', 'rfid_scan_count_30d': 50},
            ],
            'total_verified': 3,
            'total_rejected': 0,
        },
        'is_esf_data': {
            'invoices': [
                {'esf_number': 'ESF-2026-0102345', 'date': '2026-01-25', 'seller_bin': '990101000001', 'seller_name': 'Hereford Genetics GmbH (Германия)', 'buyer_iin_bin': '920812500567', 'total_amount': 12_000_000, 'items': [{'description': 'Племенные тёлки герефордской породы (импорт Германия)', 'quantity': 3, 'unit': 'голова', 'unit_price': 4_000_000, 'amount': 12_000_000}], 'status': 'confirmed', 'payment_confirmed': True},
            ],
            'total_amount': 12_000_000,
            'invoice_count': 1,
        },
        'egkn_data': {
            'has_agricultural_land': True,
            'plots': [
                {'cadastral_number': '03-115-078-456', 'area_hectares': 320.0, 'purpose': 'сельскохозяйственное назначение', 'sub_purpose': 'пастбище', 'region': 'Алматинская область', 'district': 'Талгарский район', 'ownership_type': 'собственность', 'registration_date': '2019-06-01'},
            ],
            'total_agricultural_area': 320.0,
        },
        'treasury_data': {
            'payments': [
                {'payment_id': 'PAY-2024-67890', 'amount': 5_000_000, 'status': 'completed', 'paid_date': '2024-08-10', 'treasury_reference': 'TR-2024-67890'},
            ],
        },
    },

    # ============================================================
    # 6. ИП Дархан Оспанов — частично готов, есть проблемы
    #    Зарег, но обязательства не выполнены, некоторые животные
    #    уже субсидированы, ЭСФ не подтверждена
    #    Ожидание: РАССМОТРЕНИЕ (средний скор) или ОТКАЗ по обязательствам
    # ============================================================
    {
        'username': 'darkhan',
        'password': 'demo123',
        'first_name': 'Дархан',
        'last_name': 'Оспанов',
        'iin_bin': '870325100890',
        'entity_type': 'individual',
        'entity_name': 'КХ "Оспанов"',
        'risk_profile': 'minor_issues',
        'region': 'Павлодарская область',
        'district': 'Павлодарский район',
        'phone': '+7 (771) 222-33-44',
        'organization': 'КХ "Оспанов"',
        'giss_data': {
            'registered': True,
            'gross_production_previous_year': 22_000_000,
            'gross_production_year_before': 24_000_000,
            'growth_rate': -8.3,
            'obligations_met': False,
            'total_subsidies_received': 4_000_000,
            'consecutive_decline_years': 1,
            'blocked': False,
            'block_reason': '',
        },
        'ias_rszh_data': {
            'registered': True,
            'registration_date': '2021-01-10',
            'entity_type': 'individual',
            'name': 'КХ "Оспанов"',
            'region': 'Павлодарская область',
            'district': 'Павлодарский район',
            'subsidy_history': [
                {'year': 2024, 'type': 'Приобретение маточного поголовья КРС', 'amount': 2_500_000, 'heads': 10, 'status': 'pending', 'obligations_met': False},
                {'year': 2023, 'type': 'Приобретение племенных овец', 'amount': 1_500_000, 'heads': 30, 'status': 'executed', 'obligations_met': True},
            ],
            'total_subsidies_history': 4_000_000,
            'pending_returns': 1,
        },
        'easu_data': {
            'has_account_number': True,
            'account_numbers': ['KZ32125KZT2055678901'],
            'is_spk': False,
            'spk_name': '',
            'spk_members': [],
        },
        'is_iszh_data': {
            'verified': True,
            'animals': [
                {'tag_number': 'KZ50005001', 'type': 'cattle', 'breed': 'Ангусская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2025-08-01', 'age_months': 7, 'age_valid': True, 'owner_iin_bin': '870325100890', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-02-20', 'registration_date': '2025-09-01', 'rfid_tag': 'RFID-5000501', 'rfid_active': True, 'rfid_last_scan': '2026-03-29T10:00:00', 'rfid_scan_count_30d': 18},
                {'tag_number': 'KZ50005002', 'type': 'cattle', 'breed': 'Ангусская', 'category': 'heifer', 'sex': 'female', 'birth_date': '2024-06-01', 'age_months': 21, 'age_valid': False, 'owner_iin_bin': '870325100890', 'owner_match': True, 'previously_subsidized': True, 'vet_status': 'healthy', 'last_vet_check': '2026-01-15', 'registration_date': '2024-07-01', 'rfid_tag': 'RFID-5000502', 'rfid_active': False, 'rfid_last_scan': '2026-02-01T08:00:00', 'rfid_scan_count_30d': 0},
                {'tag_number': 'KZ50005003', 'type': 'sheep', 'breed': 'Казахская тонкорунная', 'category': 'ewe', 'sex': 'female', 'birth_date': '2025-09-10', 'age_months': 6, 'age_valid': True, 'owner_iin_bin': '870325100890', 'owner_match': True, 'previously_subsidized': False, 'vet_status': 'healthy', 'last_vet_check': '2026-03-01', 'registration_date': '2025-10-01', 'rfid_tag': None, 'rfid_active': False, 'rfid_last_scan': None, 'rfid_scan_count_30d': 0},
            ],
            'total_verified': 2,
            'total_rejected': 1,
        },
        'is_esf_data': {
            'invoices': [
                {'esf_number': 'ESF-2026-0056789', 'date': '2026-02-01', 'seller_bin': '140850234567', 'seller_name': 'КХ "Степной край"', 'buyer_iin_bin': '870325100890', 'total_amount': 2_800_000, 'items': [{'description': 'КРС ангусской породы', 'quantity': 2, 'unit': 'голова', 'unit_price': 1_400_000, 'amount': 2_800_000}], 'status': 'confirmed', 'payment_confirmed': False},
            ],
            'total_amount': 2_800_000,
            'invoice_count': 1,
        },
        'egkn_data': {
            'has_agricultural_land': True,
            'plots': [
                {'cadastral_number': '11-401-055-222', 'area_hectares': 85.0, 'purpose': 'сельскохозяйственное назначение', 'sub_purpose': 'сенокос', 'region': 'Павлодарская область', 'district': 'Павлодарский район', 'ownership_type': 'аренда', 'registration_date': '2021-03-20'},
            ],
            'total_agricultural_area': 85.0,
        },
        'treasury_data': {
            'payments': [
                {'payment_id': 'PAY-2023-23456', 'amount': 1_500_000, 'status': 'completed', 'paid_date': '2023-10-05', 'treasury_reference': 'TR-2023-23456'},
            ],
        },
    },
]


class Command(BaseCommand):
    help = 'Создаёт демо-пользователей для проверки основных сценариев'

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for u in DEMO_USERS:
            # User
            user, user_created = User.objects.get_or_create(
                username=u['username'],
                defaults={
                    'first_name': u['first_name'],
                    'last_name': u['last_name'],
                },
            )
            if user_created:
                user.set_password(u['password'])
                user.save()

            # Profile
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'role': 'applicant',
                    'iin_bin': u['iin_bin'],
                    'region': u['region'],
                    'district': u['district'],
                    'organization': u.get('organization', ''),
                    'phone': u.get('phone', ''),
                },
            )

            # Applicant
            Applicant.objects.update_or_create(
                iin_bin=u['iin_bin'],
                defaults={
                    'name': u['entity_name'],
                    'entity_type': u['entity_type'],
                    'region': u['region'],
                    'district': u['district'],
                    'phone': u.get('phone', ''),
                    'registration_date': REG_DATE,
                },
            )

            # EmulatedEntity
            entity_obj, entity_created = EmulatedEntity.objects.update_or_create(
                iin_bin=u['iin_bin'],
                defaults={
                    'name': u['entity_name'],
                    'entity_type': u['entity_type'],
                    'region': u['region'],
                    'district': u['district'],
                    'registration_date': REG_DATE,
                    'risk_profile': u['risk_profile'],
                    'giss_data': u['giss_data'],
                    'ias_rszh_data': u['ias_rszh_data'],
                    'easu_data': u['easu_data'],
                    'is_iszh_data': u['is_iszh_data'],
                    'is_esf_data': u['is_esf_data'],
                    'egkn_data': u['egkn_data'],
                    'treasury_data': u['treasury_data'],
                },
            )

            # Create RFIDMonitoring records for animals with RFID
            rfid_locations = ['Ворота загона', 'Поилка №1', 'Кормушка', 'Пастбище']
            rfid_readers = ['Панельный UHF', 'Станция на поилке', 'Станция на кормушке']
            for animal in u.get('is_iszh_data', {}).get('animals', []):
                if animal.get('rfid_tag'):
                    last_scan_str = animal.get('rfid_last_scan')
                    if last_scan_str:
                        last_scan_dt = datetime.datetime.fromisoformat(last_scan_str)
                        if last_scan_dt.tzinfo is None:
                            last_scan_dt = timezone.make_aware(last_scan_dt)
                    else:
                        last_scan_dt = timezone.now() - datetime.timedelta(days=60)
                    if animal.get('rfid_active'):
                        rfid_status = 'active'
                    elif animal.get('rfid_scan_count_30d', 0) > 0:
                        rfid_status = 'inactive'
                    else:
                        rfid_status = 'missing'
                    RFIDMonitoring.objects.update_or_create(
                        entity=entity_obj,
                        animal_tag=animal['tag_number'],
                        defaults={
                            'rfid_tag': animal['rfid_tag'],
                            'last_scan_date': last_scan_dt,
                            'scan_location': random.choice(rfid_locations),
                            'status': rfid_status,
                            'scan_count_30d': animal.get('rfid_scan_count_30d', 0),
                            'animal_type': animal.get('type', ''),
                            'reader_type': random.choice(rfid_readers),
                        },
                    )

            status = 'NEW' if entity_created else 'UPD'
            if entity_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(f'  [{status}] {u["username"]} / {u["iin_bin"]} — {u["entity_name"]}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Готово: {created} создано, {updated} обновлено.'
        ))
        self.stdout.write('')
        self.stdout.write('Демо-аккаунты (логин / пароль demo123):')
        self.stdout.write('  sofiya    — ИП Абрамова С. (новенькая, ничего нет → ОТКАЗ)')
        self.stdout.write('  bogdan    — СПК "Береке Астана" (опытный, СПК, 8 животных → ОДОБРЕНИЕ)')
        self.stdout.write('  nursultan — КХ "Жумабаев Н." (готов к подаче, 3 головы → ОДОБРЕНИЕ)')
        self.stdout.write('  marat     — ТОО "Дала Агро" (заблокирован в ГИСС → ОТКАЗ)')
        self.stdout.write('  aigul     — ИП Тастемирова А. (импортный скот → ОДОБРЕНИЕ + доп.документы)')
        self.stdout.write('  darkhan   — КХ "Оспанов" (проблемы с обязательствами → РАССМОТРЕНИЕ)')
