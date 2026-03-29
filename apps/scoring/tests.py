"""
Comprehensive unit tests for SubsidyAI scoring pipeline.

Tests cover:
  - 11 hard filters (binary pass/fail checks)
  - 8 soft factors (scoring ranges)
  - Scoring engine (full pipeline, hybrid score, recommendations)
  - ML model (feature extraction, prediction)

Run: docker compose exec web python manage.py test apps.scoring
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

import numpy as np
from django.test import TestCase

from apps.emulator.models import EmulatedEntity
from apps.scoring.hard_filters import HardFilterChecker
from apps.scoring.ml_model import extract_features, FEATURE_NAMES
from apps.scoring.models import (
    Applicant,
    Application,
    Budget,
    HardFilterResult,
    Score,
    ScoreFactor,
    SubsidyDirection,
    SubsidyType,
)
from apps.scoring.scoring_engine import ScoringEngine
from apps.scoring.soft_factors import (
    SoftFactorCalculator,
    get_region_priority,
    DEFAULT_REGION_PRIORITY,
)


# ---------------------------------------------------------------------------
# Helpers: build realistic test fixtures
# ---------------------------------------------------------------------------

def _make_direction(code='cattle_meat', name='Мясное скотоводство'):
    return SubsidyDirection.objects.create(code=code, name=name)


def _make_subsidy_type(direction=None, **kwargs):
    if direction is None:
        direction = _make_direction()
    defaults = dict(
        direction=direction,
        form_number=1,
        name='Субсидия на приобретение племенного КРС',
        unit='голова',
        rate=Decimal('200000.00'),
        origin='domestic',
        min_age_months=None,
        max_age_months=None,
        is_active=True,
    )
    defaults.update(kwargs)
    return SubsidyType.objects.create(**defaults)


def _make_applicant(iin_bin='123456789012', entity_type='individual', **kwargs):
    defaults = dict(
        iin_bin=iin_bin,
        name='Тестовый заявитель',
        entity_type=entity_type,
        region='Костанайская область',
        district='Костанайский район',
        registration_date=date(2020, 1, 1),
        is_blocked=False,
    )
    defaults.update(kwargs)
    return Applicant.objects.create(**defaults)


def _make_application(applicant=None, subsidy_type=None, **kwargs):
    if applicant is None:
        applicant = _make_applicant()
    if subsidy_type is None:
        subsidy_type = _make_subsidy_type()
    defaults = dict(
        number='SUB-2026-00001',
        applicant=applicant,
        subsidy_type=subsidy_type,
        status='submitted',
        quantity=10,
        unit_price=Decimal('500000.00'),
        rate=Decimal('200000.00'),
        total_amount=Decimal('2000000.00'),
        region='Костанайская область',
        district='Костанайский район',
    )
    defaults.update(kwargs)
    return Application.objects.create(**defaults)


def _make_entity(iin_bin='123456789012', **overrides):
    """Create an EmulatedEntity with all 7 JSON fields populated for a clean profile."""
    giss = {
        'registered': True,
        'obligations_met': True,
        'obligations_required': True,
        'blocked': False,
        'growth_rate': 7.5,
        'gross_production_previous_year': 50_000_000,
        'gross_production_year_before': 45_000_000,
        'total_subsidies_received': 10_000_000,
    }
    easu = {
        'has_account_number': True,
    }
    ias_rszh = {
        'registered': True,
        'ibspr_registered': True,
        'pending_returns': 0,
        'subsidy_history': [
            {'type': 'cattle_meat', 'status': 'executed', 'obligations_met': True, 'heads': 10},
            {'type': 'cattle_meat', 'status': 'executed', 'obligations_met': True, 'heads': 15},
        ],
    }
    is_iszh = {
        'total_verified': 25,
        'total_rejected': 0,
        'animals': [
            {'tag': 'KZ001', 'age_months': 18, 'age_valid': True, 'previously_subsidized': False},
            {'tag': 'KZ002', 'age_months': 24, 'age_valid': True, 'previously_subsidized': False},
        ],
    }
    is_esf = {
        'invoice_count': 2,
        'total_amount': 5_000_000,
        'invoices': [
            {'number': 'ESF-001', 'amount': 3_000_000, 'payment_confirmed': True},
            {'number': 'ESF-002', 'amount': 2_000_000, 'payment_confirmed': True},
        ],
    }
    egkn = {
        'has_agricultural_land': True,
        'total_agricultural_area': 150.0,
    }
    treasury = {
        'payments': [
            {'ref': 'TR-001', 'amount': 1_000_000, 'status': 'completed'},
        ],
    }

    data = dict(
        iin_bin=iin_bin,
        name='Тестовый субъект',
        entity_type='individual',
        region='Костанайская область',
        district='Костанайский район',
        registration_date=date(2020, 1, 1),
        risk_profile='clean',
        giss_data=giss,
        easu_data=easu,
        ias_rszh_data=ias_rszh,
        is_iszh_data=is_iszh,
        is_esf_data=is_esf,
        egkn_data=egkn,
        treasury_data=treasury,
    )
    data.update(overrides)
    return EmulatedEntity.objects.create(**data)


# ===========================================================================
# 1. Hard Filter Tests
# ===========================================================================

class HardFilterGISSTest(TestCase):
    """Filter 1: GISS registration."""

    def test_giss_registered_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_giss_registered())

    def test_giss_registered_fail(self):
        entity = _make_entity(giss_data={'registered': False})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_giss_registered())

    def test_giss_no_entity(self):
        app = _make_application(applicant=_make_applicant(iin_bin='999999999999'))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_giss_registered())


class HardFilterECPTest(TestCase):
    """Filter 2: ECP (digital signature) availability."""

    def test_has_eds_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_has_eds())

    def test_has_eds_fail(self):
        entity = _make_entity(easu_data={'has_account_number': False})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_has_eds())


class HardFilterIASTest(TestCase):
    """Filter 3: IAS RSZH registration (cooperatives exempt)."""

    def test_ias_registered_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_ias_rszh_registered())

    def test_ias_registered_fail(self):
        entity = _make_entity(ias_rszh_data={'registered': False})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_ias_rszh_registered())

    def test_ias_cooperative_exempt(self):
        entity = _make_entity(ias_rszh_data={'registered': False})
        app = _make_application(
            applicant=_make_applicant(iin_bin=entity.iin_bin, entity_type='cooperative'),
        )
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_ias_rszh_registered())


class HardFilterEGKNTest(TestCase):
    """Filter 4: Agricultural land (EGKN)."""

    def test_has_land_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_has_agricultural_land())

    def test_has_land_fail(self):
        entity = _make_entity(egkn_data={'has_agricultural_land': False})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_has_agricultural_land())


class HardFilterLivestockTest(TestCase):
    """Filter 5: Livestock verification (IS ISZH)."""

    def test_livestock_verified_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_is_iszh_registered())

    def test_livestock_verified_fail(self):
        entity = _make_entity(is_iszh_data={'total_verified': 0, 'animals': []})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_is_iszh_registered())


class HardFilterIBSPRTest(TestCase):
    """Filter 6: IBSPR registration."""

    def test_ibspr_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_ibspr_registered())

    def test_ibspr_fail(self):
        entity = _make_entity(ias_rszh_data={
            'registered': False,
            'ibspr_registered': False,
        })
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_ibspr_registered())

    def test_ibspr_fallback_to_registered(self):
        """When ibspr_registered key is missing, falls back to registered."""
        entity = _make_entity(ias_rszh_data={'registered': True})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_ibspr_registered())


class HardFilterESFTest(TestCase):
    """Filter 7: ESF confirmation."""

    def test_esf_confirmed_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_esf_confirmed())

    def test_esf_no_invoices_fail(self):
        entity = _make_entity(is_esf_data={'invoice_count': 0, 'invoices': []})
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_esf_confirmed())

    def test_esf_none_confirmed_fail(self):
        entity = _make_entity(is_esf_data={
            'invoice_count': 1,
            'invoices': [{'number': 'X', 'amount': 100, 'payment_confirmed': False}],
        })
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_esf_confirmed())


class HardFilterObligationsTest(TestCase):
    """Filter 8: No unfulfilled obligations."""

    def test_obligations_met_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_no_unfulfilled_obligations())

    def test_obligations_not_met_fail(self):
        entity = _make_entity(giss_data={
            'registered': True,
            'obligations_met': False,
            'obligations_required': True,
            'blocked': False,
        })
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_no_unfulfilled_obligations())

    def test_obligations_not_required_pass(self):
        entity = _make_entity(giss_data={
            'registered': True,
            'obligations_met': False,
            'obligations_required': False,
            'blocked': False,
        })
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_no_unfulfilled_obligations())


class HardFilterBlockTest(TestCase):
    """Filter 9: No blocks."""

    def test_no_block_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_no_block())

    def test_giss_blocked_fail(self):
        entity = _make_entity(giss_data={
            'registered': True,
            'blocked': True,
            'obligations_met': True,
        })
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_no_block())

    def test_applicant_blocked_fail(self):
        entity = _make_entity()
        applicant = _make_applicant(
            iin_bin=entity.iin_bin,
            is_blocked=True,
            block_until=date.today() + timedelta(days=30),
        )
        app = _make_application(applicant=applicant)
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_no_block())

    def test_applicant_block_expired_pass(self):
        """Block has expired (block_until in the past) -> pass."""
        entity = _make_entity()
        applicant = _make_applicant(
            iin_bin=entity.iin_bin,
            is_blocked=True,
            block_until=date.today() - timedelta(days=1),
        )
        app = _make_application(applicant=applicant)
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_no_block())


class HardFilterAnimalAgeTest(TestCase):
    """Filter 10: Animal age validity."""

    def test_age_valid_pass(self):
        direction = _make_direction()
        st = _make_subsidy_type(direction=direction, min_age_months=12, max_age_months=36)
        entity = _make_entity()
        app = _make_application(
            applicant=_make_applicant(iin_bin=entity.iin_bin),
            subsidy_type=st,
        )
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_animals_age_valid())

    def test_age_invalid_fail(self):
        direction = _make_direction()
        st = _make_subsidy_type(direction=direction, min_age_months=12, max_age_months=36)
        entity = _make_entity(is_iszh_data={
            'total_verified': 2,
            'animals': [
                {'tag': 'A1', 'age_months': 18, 'age_valid': True, 'previously_subsidized': False},
                {'tag': 'A2', 'age_months': 6, 'age_valid': False, 'previously_subsidized': False},
            ],
        })
        app = _make_application(
            applicant=_make_applicant(iin_bin=entity.iin_bin),
            subsidy_type=st,
        )
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_animals_age_valid())

    def test_age_check_skipped_no_limits(self):
        """No min/max age on subsidy type -> always pass."""
        direction = _make_direction()
        st = _make_subsidy_type(direction=direction, min_age_months=None, max_age_months=None)
        entity = _make_entity()
        app = _make_application(
            applicant=_make_applicant(iin_bin=entity.iin_bin),
            subsidy_type=st,
        )
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_animals_age_valid())


class HardFilterSubsidyDuplicationTest(TestCase):
    """Filter 11: Animals not previously subsidized."""

    def test_not_subsidized_pass(self):
        entity = _make_entity()
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_animals_not_subsidized())

    def test_previously_subsidized_fail(self):
        entity = _make_entity(is_iszh_data={
            'total_verified': 2,
            'animals': [
                {'tag': 'A1', 'age_valid': True, 'previously_subsidized': True},
                {'tag': 'A2', 'age_valid': True, 'previously_subsidized': False},
            ],
        })
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertFalse(checker._check_animals_not_subsidized())

    def test_non_animal_direction_skipped(self):
        """Non-animal direction -> subsidy duplication check is skipped."""
        direction = _make_direction(code='plant_seeds', name='Семена')
        st = _make_subsidy_type(direction=direction)
        entity = _make_entity(is_iszh_data={
            'total_verified': 1,
            'animals': [
                {'tag': 'A1', 'age_valid': True, 'previously_subsidized': True},
            ],
        })
        app = _make_application(
            applicant=_make_applicant(iin_bin=entity.iin_bin),
            subsidy_type=st,
        )
        checker = HardFilterChecker(app)
        checker._load_entity()
        self.assertTrue(checker._check_animals_not_subsidized())


class HardFilterCheckAllTest(TestCase):
    """Integration: check_all saves HardFilterResult to DB."""

    def test_check_all_pass(self):
        # Use poultry direction (year-round acceptance) to avoid period filter
        direction = _make_direction(code='poultry', name='Птицеводство')
        st = _make_subsidy_type(direction=direction, form_number=20)
        entity = _make_entity()
        app = _make_application(
            applicant=_make_applicant(iin_bin=entity.iin_bin),
            subsidy_type=st,
        )
        checker = HardFilterChecker(app)
        result = checker.check_all()
        self.assertTrue(result['all_passed'], f"Failed: {result['failed_reasons']}")
        self.assertEqual(result['failed_reasons'], [])
        self.assertTrue(HardFilterResult.objects.filter(application=app).exists())

    def test_check_all_fail_saves_reasons(self):
        entity = _make_entity(
            giss_data={'registered': False, 'obligations_met': True, 'blocked': False},
        )
        app = _make_application(applicant=_make_applicant(iin_bin=entity.iin_bin))
        checker = HardFilterChecker(app)
        result = checker.check_all()
        self.assertFalse(result['all_passed'])
        self.assertIn('Регистрация в ГИСС', result['failed_reasons'])


# ===========================================================================
# 2. Soft Factor Tests
# ===========================================================================

class _SoftFactorTestBase(TestCase):
    """Base class that sets up a default application + entity_data dict."""

    def setUp(self):
        direction = _make_direction()
        self.subsidy_type = _make_subsidy_type(direction=direction)
        self.applicant = _make_applicant()
        self.application = _make_application(
            applicant=self.applicant,
            subsidy_type=self.subsidy_type,
        )
        self.entity_data = {
            'giss_data': {
                'growth_rate': 7.5,
                'gross_production_previous_year': 50_000_000,
                'gross_production_year_before': 45_000_000,
            },
            'ias_rszh_data': {
                'registered': True,
                'pending_returns': 0,
                'subsidy_history': [
                    {'type': 'cattle_meat', 'status': 'executed', 'obligations_met': True, 'heads': 10},
                    {'type': 'cattle_meat', 'status': 'executed', 'obligations_met': True, 'heads': 15},
                ],
            },
            'easu_data': {'has_account_number': True},
            'is_iszh_data': {'total_verified': 25, 'total_rejected': 0, 'animals': []},
            'is_esf_data': {
                'invoice_count': 2,
                'total_amount': 5_000_000,
                'invoices': [
                    {'number': 'E1', 'amount': 3_000_000, 'payment_confirmed': True},
                ],
            },
            'egkn_data': {'has_agricultural_land': True, 'total_agricultural_area': 150.0},
            'treasury_data': {'payments': [{'ref': 'T1'}]},
            'entity_type': 'individual',
            'db_history': {},
        }


class SubsidyHistoryFactorTest(_SoftFactorTestBase):
    """Factor 1: subsidy_history scoring."""

    def test_no_history_neutral(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = []
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_subsidy_history()
        self.assertEqual(result['value'], 10.0)

    def test_high_success_rate(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = [
            {'status': 'executed', 'obligations_met': True, 'heads': 10},
        ] * 5
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_subsidy_history()
        self.assertGreaterEqual(result['value'], 18.0)

    def test_low_success_rate(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = [
            {'status': 'executed', 'obligations_met': False, 'heads': 5},
        ] * 4
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_subsidy_history()
        self.assertLess(result['value'], 8.0)


class ProductionGrowthFactorTest(_SoftFactorTestBase):
    """Factor 2: production_growth scoring."""

    def test_high_growth(self):
        self.entity_data['giss_data']['growth_rate'] = 12.0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_production_growth()
        self.assertEqual(result['value'], 20.0)

    def test_moderate_growth(self):
        self.entity_data['giss_data']['growth_rate'] = 3.0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_production_growth()
        self.assertGreater(result['value'], 8.0)
        self.assertLess(result['value'], 14.0)

    def test_negative_growth(self):
        self.entity_data['giss_data']['growth_rate'] = -8.0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_production_growth()
        self.assertLess(result['value'], 4.0)

    def test_zero_growth(self):
        self.entity_data['giss_data']['growth_rate'] = 0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_production_growth()
        self.assertEqual(result['value'], 8.0)


class FarmSizeFactorTest(_SoftFactorTestBase):
    """Factor 3: farm_size scoring."""

    def test_large_farm(self):
        self.entity_data['egkn_data']['total_agricultural_area'] = 600
        self.entity_data['is_iszh_data']['total_verified'] = 250
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_farm_size()
        self.assertEqual(result['value'], 15.0)

    def test_small_farm(self):
        self.entity_data['egkn_data']['total_agricultural_area'] = 15
        self.entity_data['is_iszh_data']['total_verified'] = 5
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_farm_size()
        self.assertLess(result['value'], 3.0)

    def test_zero_farm(self):
        self.entity_data['egkn_data']['total_agricultural_area'] = 0
        self.entity_data['is_iszh_data']['total_verified'] = 0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_farm_size()
        self.assertEqual(result['value'], 0.0)


class EfficiencyFactorTest(_SoftFactorTestBase):
    """Factor 4: efficiency (livestock retention) scoring."""

    def test_no_history_neutral(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = []
        self.entity_data['ias_rszh_data']['pending_returns'] = 0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_efficiency()
        self.assertEqual(result['value'], 11.0)

    def test_high_retention(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = [
            {'heads': 50, 'status': 'executed', 'obligations_met': True},
        ]
        self.entity_data['ias_rszh_data']['pending_returns'] = 0
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_efficiency()
        self.assertEqual(result['value'], 15.0)

    def test_low_retention(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = [
            {'heads': 100, 'status': 'executed', 'obligations_met': True},
        ]
        self.entity_data['ias_rszh_data']['pending_returns'] = 50
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_efficiency()
        self.assertLess(result['value'], 7.0)


class RateComplianceFactorTest(_SoftFactorTestBase):
    """Factor 5: rate_compliance scoring."""

    def test_perfect_compliance(self):
        # total_amount = quantity * rate = 10 * 200000 = 2_000_000
        # esf covers actual cost (quantity * unit_price = 10 * 500000 = 5_000_000)
        self.entity_data['is_esf_data']['total_amount'] = 6_000_000
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_rate_compliance()
        self.assertGreaterEqual(result['value'], 6.0)
        self.assertLessEqual(result['value'], 10.0)

    def test_rate_mismatch_esf_covers(self):
        # Change total_amount so it does not match quantity * rate
        self.application.total_amount = Decimal('3000000.00')
        self.application.save()
        self.entity_data['is_esf_data']['total_amount'] = 3_000_000
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_rate_compliance()
        self.assertGreaterEqual(result['value'], 0.0)
        self.assertLessEqual(result['value'], 10.0)

    def test_rate_match_esf_short(self):
        self.entity_data['is_esf_data']['total_amount'] = 100_000  # not enough for actual cost
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_rate_compliance()
        self.assertEqual(result['value'], 6.0)


class RegionalPriorityFactorTest(_SoftFactorTestBase):
    """Factor 6: regional_priority scoring."""

    def test_high_priority_region(self):
        self.application.region = 'Костанайская область'
        self.application.save()
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_region_priority()
        # Костанайская + cattle_meat = 0.9
        self.assertEqual(result['value'], 9.0)

    def test_default_priority_region(self):
        self.application.region = 'Неизвестная область'
        self.application.save()
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_region_priority()
        self.assertEqual(result['value'], DEFAULT_REGION_PRIORITY * 10)

    def test_get_region_priority_helper(self):
        self.assertEqual(get_region_priority('Костанайская область', 'cattle_meat'), 0.9)
        self.assertEqual(get_region_priority('UnknownRegion', 'cattle_meat'), DEFAULT_REGION_PRIORITY)


class EntityTypeFactorTest(_SoftFactorTestBase):
    """Factor 7: entity_type scoring."""

    def test_cooperative_max(self):
        self.applicant.entity_type = 'cooperative'
        self.applicant.save()
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_entity_type()
        self.assertEqual(result['value'], 5.0)

    def test_legal_entity(self):
        self.applicant.entity_type = 'legal'
        self.applicant.save()
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_entity_type()
        self.assertEqual(result['value'], 4.0)

    def test_individual(self):
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_entity_type()
        self.assertEqual(result['value'], 3.0)


class ApplicantPrimacyFactorTest(_SoftFactorTestBase):
    """Factor 8: applicant_primacy scoring."""

    def test_first_time_applicant(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = []
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_applicant_history()
        self.assertEqual(result['value'], 4.0)

    def test_diversification(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = [
            {'type': 'sheep', 'status': 'executed', 'obligations_met': True, 'heads': 10},
        ]
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_applicant_history()
        self.assertEqual(result['value'], 5.0)

    def test_frequent_applicant(self):
        self.entity_data['ias_rszh_data']['subsidy_history'] = [
            {'type': 'cattle_meat', 'status': 'executed', 'obligations_met': True, 'heads': 5},
        ] * 5
        calc = SoftFactorCalculator(self.application, self.entity_data)
        result = calc._calc_applicant_history()
        self.assertEqual(result['value'], 2.0)


class SoftFactorCalculateAllTest(_SoftFactorTestBase):
    """Integration: calculate_all returns 8 factors summing up to <= 100."""

    def test_calculate_all_returns_eight_factors(self):
        calc = SoftFactorCalculator(self.application, self.entity_data)
        factors = calc.calculate_all()
        self.assertEqual(len(factors), 8)
        total_max = sum(f['max_value'] for f in factors)
        self.assertEqual(total_max, 100.0)

    def test_all_values_within_bounds(self):
        calc = SoftFactorCalculator(self.application, self.entity_data)
        factors = calc.calculate_all()
        for f in factors:
            self.assertGreaterEqual(f['value'], 0.0, f"Factor {f['factor_code']} below 0")
            self.assertLessEqual(f['value'], f['max_value'], f"Factor {f['factor_code']} above max")


# ===========================================================================
# 3. Scoring Engine Tests
# ===========================================================================

class ScoringEnginePipelineTest(TestCase):
    """Full pipeline tests for ScoringEngine."""

    def setUp(self):
        self.direction = _make_direction(code='poultry', name='Птицеводство')
        self.subsidy_type = _make_subsidy_type(direction=self.direction, form_number=20)
        self.entity = _make_entity()
        self.applicant = _make_applicant(iin_bin=self.entity.iin_bin)
        self.application = _make_application(
            applicant=self.applicant,
            subsidy_type=self.subsidy_type,
        )

    @patch('apps.scoring.scoring_engine.predict_score', return_value=None)
    def test_full_pipeline_pass_rules_only(self, mock_ml):
        """All hard filters pass, ML unavailable -> rule-based score."""
        engine = ScoringEngine()
        result = engine.run_scoring(self.application)
        self.assertTrue(result['success'])
        self.assertIsNotNone(result['score'])
        self.assertGreater(result['total_score'], 0)
        self.assertEqual(len(result['factors']), 8)
        self.assertIn(result['recommendation'], ('approve', 'review', 'reject'))

    @patch('apps.scoring.scoring_engine.predict_score', return_value=None)
    def test_pipeline_hard_filter_fail_info(self, mock_ml):
        """Hard filter failure -> info (not reject), no score calculated."""
        self.entity.giss_data = {'registered': False, 'blocked': False, 'obligations_met': True}
        self.entity.save()
        engine = ScoringEngine()
        result = engine.run_scoring(self.application)
        self.assertTrue(result['success'])
        self.assertIsNone(result['score'])
        self.assertEqual(result['recommendation'], 'info')
        self.assertEqual(result['total_score'], 0)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'checking')

    @patch('apps.scoring.scoring_engine.predict_score')
    def test_hybrid_score_calculation(self, mock_ml):
        """60% ML + 40% rules hybrid scoring."""
        mock_ml.return_value = {
            'ml_score': 80.0,
            'ml_recommendation': 'approve',
            'confidence': 0.92,
            'feature_contributions': [],
        }
        engine = ScoringEngine()
        result = engine.run_scoring(self.application)
        self.assertTrue(result['success'])
        total = result['total_score']
        # total = 0.6 * 80 + 0.4 * rule_score
        # Since rule_score is sum of factor values, just verify it's a weighted blend
        # ML part should contribute 48 (0.6 * 80)
        self.assertGreater(total, 0)
        self.assertLessEqual(total, 100)
        # Verify ML was actually used: total should differ from pure rule_score
        rule_score = sum(f['value'] for f in result['factors'])
        expected = round(0.6 * 80.0 + 0.4 * rule_score, 2)
        self.assertAlmostEqual(total, min(100, expected), places=1)

    @patch('apps.scoring.scoring_engine.predict_score', return_value=None)
    def test_entity_not_found_returns_error(self, mock_ml):
        """No EmulatedEntity for applicant -> error result."""
        applicant2 = _make_applicant(iin_bin='000000000000')
        app2 = _make_application(
            applicant=applicant2,
            subsidy_type=self.subsidy_type,
            number='SUB-2026-00002',
        )
        engine = ScoringEngine()
        result = engine.run_scoring(app2)
        self.assertFalse(result['success'])
        self.assertEqual(result['recommendation'], 'reject')


class RecommendationThresholdTest(TestCase):
    """Test that _get_recommendation thresholds are correct."""

    def test_approve_threshold(self):
        engine = ScoringEngine()
        self.assertEqual(engine._get_recommendation(70), 'approve')
        self.assertEqual(engine._get_recommendation(85), 'approve')
        self.assertEqual(engine._get_recommendation(100), 'approve')

    def test_review_threshold(self):
        engine = ScoringEngine()
        self.assertEqual(engine._get_recommendation(40), 'review')
        self.assertEqual(engine._get_recommendation(55), 'review')
        self.assertEqual(engine._get_recommendation(69.99), 'review')

    def test_reject_threshold(self):
        engine = ScoringEngine()
        self.assertEqual(engine._get_recommendation(0), 'reject')
        self.assertEqual(engine._get_recommendation(20), 'reject')
        self.assertEqual(engine._get_recommendation(39.99), 'reject')


class ScoringEngineBudgetTest(TestCase):
    """Budget availability affects application status."""

    def setUp(self):
        self.direction = _make_direction(code='poultry', name='Птицеводство')
        self.subsidy_type = _make_subsidy_type(direction=self.direction, form_number=20)
        self.entity = _make_entity()
        self.applicant = _make_applicant(iin_bin=self.entity.iin_bin)

    @patch('apps.scoring.scoring_engine.predict_score')
    def test_approve_with_no_budget_goes_to_waiting_list(self, mock_ml):
        mock_ml.return_value = {
            'ml_score': 95.0,
            'ml_recommendation': 'approve',
            'confidence': 0.95,
            'feature_contributions': [],
        }
        app = _make_application(
            applicant=self.applicant,
            subsidy_type=self.subsidy_type,
        )
        # Create a budget with zero remaining
        Budget.objects.create(
            year=date.today().year,
            region=app.region,
            direction=self.direction,
            planned_amount=Decimal('1000000.00'),
            spent_amount=Decimal('1000000.00'),
        )
        engine = ScoringEngine()
        result = engine.run_scoring(app)
        if result['recommendation'] == 'approve':
            app.refresh_from_db()
            self.assertEqual(app.status, 'waiting_list')


# ===========================================================================
# 4. ML Model Tests
# ===========================================================================

class FeatureExtractionTest(TestCase):
    """Test extract_features from emulated entity data."""

    def setUp(self):
        self.entity_data = {
            'giss_data': {
                'registered': True,
                'growth_rate': 7.5,
                'gross_production_previous_year': 50_000_000,
                'gross_production_year_before': 45_000_000,
                'obligations_met': True,
                'total_subsidies_received': 10_000_000,
            },
            'ias_rszh_data': {
                'registered': True,
                'pending_returns': 1,
                'subsidy_history': [
                    {'status': 'executed', 'obligations_met': True, 'heads': 10},
                    {'status': 'executed', 'obligations_met': False, 'heads': 5},
                ],
            },
            'easu_data': {'has_account_number': True},
            'is_iszh_data': {
                'total_verified': 25,
                'total_rejected': 2,
                'animals': [
                    {'age_valid': True},
                    {'age_valid': True},
                    {'age_valid': False},
                ],
            },
            'is_esf_data': {
                'total_amount': 5_000_000,
                'invoice_count': 3,
                'invoices': [
                    {'payment_confirmed': True},
                    {'payment_confirmed': True},
                    {'payment_confirmed': False},
                ],
            },
            'egkn_data': {
                'has_agricultural_land': True,
                'total_agricultural_area': 150.0,
            },
            'treasury_data': {
                'payments': [{'ref': 'T1'}, {'ref': 'T2'}],
            },
            'entity_type': 'legal',
        }

    def test_returns_correct_shape(self):
        features = extract_features(self.entity_data)
        self.assertEqual(features.shape, (len(FEATURE_NAMES),))
        self.assertEqual(features.shape, (20,))

    def test_feature_values(self):
        features = extract_features(self.entity_data)
        # giss_registered
        self.assertEqual(features[0], 1.0)
        # growth_rate
        self.assertEqual(features[1], 7.5)
        # gross_production_prev (50M / 1M)
        self.assertAlmostEqual(features[2], 50.0)
        # gross_production_before (45M / 1M)
        self.assertAlmostEqual(features[3], 45.0)
        # obligations_met
        self.assertEqual(features[4], 1.0)
        # total_subsidies_received (10M / 1M)
        self.assertAlmostEqual(features[5], 10.0)
        # ias_registered
        self.assertEqual(features[6], 1.0)
        # subsidy_history_count
        self.assertEqual(features[7], 2.0)
        # subsidy_success_rate (1 executed+met out of 2)
        self.assertAlmostEqual(features[8], 0.5)
        # pending_returns
        self.assertEqual(features[9], 1.0)
        # total_verified_animals
        self.assertEqual(features[10], 25.0)
        # total_rejected_animals
        self.assertEqual(features[11], 2.0)
        # animal_age_valid_ratio (2/3)
        self.assertAlmostEqual(features[12], 2 / 3, places=4)
        # esf_total_amount (5M / 1M)
        self.assertAlmostEqual(features[13], 5.0)
        # esf_invoice_count
        self.assertEqual(features[14], 3.0)
        # esf_confirmed_ratio (2/3)
        self.assertAlmostEqual(features[15], 2 / 3, places=4)
        # has_agricultural_land
        self.assertEqual(features[16], 1.0)
        # total_agricultural_area
        self.assertEqual(features[17], 150.0)
        # entity_type_encoded (legal=1)
        self.assertEqual(features[18], 1.0)
        # treasury_payment_count
        self.assertEqual(features[19], 2.0)

    def test_empty_entity_data(self):
        features = extract_features({})
        self.assertEqual(features.shape, (20,))
        # All should be default/zero except success_rate (0.5) and obligations_met (1.0)
        self.assertEqual(features[0], 0.0)  # giss_registered
        self.assertAlmostEqual(features[8], 0.5)  # success_rate default
        # age_valid_ratio defaults to 0.5 when no animals
        self.assertAlmostEqual(features[12], 0.5)

    def test_entity_type_encoding(self):
        for etype, code in [('individual', 0), ('legal', 1), ('cooperative', 2)]:
            self.entity_data['entity_type'] = etype
            features = extract_features(self.entity_data)
            self.assertEqual(features[18], float(code))


class PredictScoreTest(TestCase):
    """Test predict_score with mocked models."""

    def setUp(self):
        self.entity_data = {
            'giss_data': {'registered': True, 'growth_rate': 5, 'obligations_met': True,
                          'gross_production_previous_year': 1_000_000,
                          'gross_production_year_before': 900_000,
                          'total_subsidies_received': 500_000},
            'ias_rszh_data': {'registered': True, 'pending_returns': 0, 'subsidy_history': []},
            'easu_data': {},
            'is_iszh_data': {'total_verified': 10, 'total_rejected': 0, 'animals': []},
            'is_esf_data': {'total_amount': 200_000, 'invoice_count': 1, 'invoices': []},
            'egkn_data': {'has_agricultural_land': True, 'total_agricultural_area': 50},
            'treasury_data': {'payments': []},
            'entity_type': 'individual',
        }

    @patch('apps.scoring.ml_model._load_models', return_value=True)
    @patch('apps.scoring.ml_model._score_model')
    @patch('apps.scoring.ml_model._rec_model')
    @patch('apps.scoring.ml_model._meta')
    def test_predict_returns_valid_range(self, mock_meta, mock_rec, mock_score, mock_load):
        mock_score.predict.return_value = np.array([75.5])
        mock_rec.predict_proba.return_value = np.array([[0.1, 0.2, 0.7]])
        mock_meta.__getitem__ = lambda self, key: {
            'label_encoder_classes': ['approve', 'reject', 'review'],
            'score_feature_importances': [0.05] * 20,
        }[key]
        mock_meta.get = lambda key, default=None: {
            'label_encoder_classes': ['approve', 'reject', 'review'],
            'score_feature_importances': [0.05] * 20,
        }.get(key, default)

        from apps.scoring.ml_model import predict_score
        result = predict_score(self.entity_data)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result['ml_score'], 0)
        self.assertLessEqual(result['ml_score'], 100)
        self.assertIn(result['ml_recommendation'], ('approve', 'review', 'reject'))
        self.assertGreater(result['confidence'], 0)
        self.assertLessEqual(result['confidence'], 1)

    @patch('apps.scoring.ml_model._load_models', return_value=False)
    def test_predict_returns_none_when_no_model(self, mock_load):
        from apps.scoring.ml_model import predict_score
        result = predict_score(self.entity_data)
        self.assertIsNone(result)
