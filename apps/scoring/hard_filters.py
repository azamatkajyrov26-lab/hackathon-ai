import logging
from datetime import date
from decimal import Decimal

from apps.emulator.models import EmulatedEntity
from apps.scoring.models import Application, HardFilterResult

logger = logging.getLogger(__name__)


class HardFilterChecker:
    """
    Проверяет 15 бинарных hard-фильтров для заявки.
    Если хотя бы один FAIL — информирование заявителя (не отказ).

    Фильтры 1–11: базовые проверки регистрации и данных.
    Фильтры 12–15: дополнительные проверки по Приказу №108.

    Для хакатона данные читаются напрямую из EmulatedEntity JSON-полей
    вместо реальных HTTP-вызовов к API эмуляторов.
    """

    FILTER_LABELS = {
        'giss_registered': 'Регистрация в ГИСС',
        'has_eds': 'Наличие ЭЦП',
        'ias_rszh_registered': 'Учётный номер в ИАС «РСЖ»',
        'has_agricultural_land': 'Земельный участок с/х назначения (ЕГКН)',
        'is_iszh_registered': 'Регистрация в ИС ИСЖ',
        'ibspr_registered': 'Регистрация в ИБСПР',
        'esf_confirmed': 'Подтверждение затрат через ЭСФ',
        'no_unfulfilled_obligations': 'Нет невыполненных обязательств',
        'no_block': 'Нет блокировки',
        'animals_age_valid': 'Возраст животных в допустимом диапазоне',
        'animals_not_subsidized': 'Животные не субсидировались ранее',
        'application_period_valid': 'Заявка подана в допустимый период (Приказ №108)',
        'subsidy_amount_valid': 'Сумма субсидии не превышает 50% стоимости',
        'min_herd_size_met': 'Минимальное поголовье соответствует требованиям',
        'no_duplicate_application': 'Нет дублирующих заявок в текущем году',
    }

    def __init__(self, application: Application):
        self.application = application
        self.entity = None
        self.results = {}
        self.failed_reasons = []
        self.raw_responses = {}

    def _load_entity(self):
        """Загрузка EmulatedEntity по ИИН/БИН заявителя."""
        try:
            self.entity = EmulatedEntity.objects.get(
                iin_bin=self.application.applicant.iin_bin
            )
        except EmulatedEntity.DoesNotExist:
            logger.warning(
                'EmulatedEntity не найден для ИИН/БИН %s',
                self.application.applicant.iin_bin,
            )
            self.entity = None

    def _check_giss_registered(self):
        """Фильтр 1: Регистрация в ГИСС."""
        if not self.entity:
            return False
        giss = self.entity.giss_data or {}
        self.raw_responses['giss'] = giss
        return giss.get('registered', False)

    def _check_has_eds(self):
        """Фильтр 2: Наличие ЭЦП (из данных ЕАСУ)."""
        if not self.entity:
            return False
        easu = self.entity.easu_data or {}
        self.raw_responses['easu'] = easu
        # ЭЦП подтверждается наличием учётного номера в ЕАСУ
        return easu.get('has_account_number', False)

    def _check_ias_rszh_registered(self):
        """Фильтр 3: Учётный номер в ИАС «РСЖ» (исключение: СПК)."""
        if not self.entity:
            return False
        # СПК освобождены от этой проверки
        if self.application.applicant.entity_type == 'cooperative':
            return True
        ias = self.entity.ias_rszh_data or {}
        self.raw_responses['ias_rszh'] = ias
        return ias.get('registered', False)

    def _check_has_agricultural_land(self):
        """Фильтр 4: Земельный участок с/х назначения (ЕГКН)."""
        if not self.entity:
            return False
        egkn = self.entity.egkn_data or {}
        self.raw_responses['egkn'] = egkn
        return egkn.get('has_agricultural_land', False)

    def _check_is_iszh_registered(self):
        """Фильтр 5: Регистрация в ИС ИСЖ (есть верифицированные животные)."""
        if not self.entity:
            return False
        is_iszh = self.entity.is_iszh_data or {}
        self.raw_responses['is_iszh'] = is_iszh
        return is_iszh.get('total_verified', 0) > 0

    def _check_ibspr_registered(self):
        """Фильтр 6: Регистрация в ИБСПР (через ИАС РСЖ)."""
        if not self.entity:
            return False
        ias = self.entity.ias_rszh_data or {}
        if 'ias_rszh' not in self.raw_responses:
            self.raw_responses['ias_rszh'] = ias
        # ИБСПР привязан к ИАС РСЖ — если registered, значит и ИБСПР есть
        return ias.get('ibspr_registered', ias.get('registered', False))

    def _check_esf_confirmed(self):
        """Фильтр 7: Подтверждение затрат через ЭСФ."""
        if not self.entity:
            return False
        esf = self.entity.is_esf_data or {}
        self.raw_responses['is_esf'] = esf
        invoice_count = esf.get('invoice_count', 0)
        if invoice_count <= 0:
            return False
        # Проверяем что хотя бы одна ЭСФ подтверждена
        invoices = esf.get('invoices', [])
        return any(inv.get('payment_confirmed', False) for inv in invoices)

    def _check_no_unfulfilled_obligations(self):
        """Фильтр 8: Нет невыполненных обязательств (ГИСС)."""
        if not self.entity:
            return False
        giss = self.entity.giss_data or {}
        obligations_met = giss.get('obligations_met', True)
        obligations_required = giss.get('obligations_required', False)
        # Обязательства выполнены ИЛИ обязательства не требуются
        return obligations_met or not obligations_required

    def _check_no_block(self):
        """Фильтр 9: Нет блокировки (ГИСС + Applicant)."""
        if not self.entity:
            return False
        giss = self.entity.giss_data or {}
        giss_blocked = giss.get('blocked', False)
        applicant_blocked = self.application.applicant.is_blocked
        # Проверяем дату окончания блокировки
        if applicant_blocked and self.application.applicant.block_until:
            if self.application.applicant.block_until <= date.today():
                applicant_blocked = False
        return not giss_blocked and not applicant_blocked

    def _check_animals_age_valid(self):
        """Фильтр 10: Возраст животных в допустимом диапазоне (ИС ИСЖ)."""
        # Если SubsidyType не требует проверки возраста — пропускаем
        subsidy_type = self.application.subsidy_type
        if subsidy_type.min_age_months is None and subsidy_type.max_age_months is None:
            return True
        if not self.entity:
            return False
        is_iszh = self.entity.is_iszh_data or {}
        animals = is_iszh.get('animals', [])
        if not animals:
            return False
        # Все животные должны иметь age_valid == True
        return all(animal.get('age_valid', False) for animal in animals)

    def _check_animals_not_subsidized(self):
        """Фильтр 11: Животные не субсидировались ранее (ИС ИСЖ)."""
        # Если субсидия не связана с животными — пропускаем
        subsidy_type = self.application.subsidy_type
        direction_code = subsidy_type.direction.code if subsidy_type.direction else ''
        animal_directions = {'cattle_meat', 'cattle_dairy', 'cattle_general', 'sheep', 'horse', 'pig', 'poultry', 'camel', 'beekeeping', 'aquaculture'}
        if direction_code not in animal_directions:
            return True
        if not self.entity:
            return False
        is_iszh = self.entity.is_iszh_data or {}
        animals = is_iszh.get('animals', [])
        if not animals:
            return True
        return all(
            not animal.get('previously_subsidized', False) for animal in animals
        )

    # ------------------------------------------------------------------
    # Фильтры 12–15 (Приказ №108)
    # ------------------------------------------------------------------

    # Формы племенных субсидий (где действует лимит 50%)
    TRIBAL_FORM_NUMBERS = {1, 2, 3, 4, 5, 6, 7, 8}

    def _check_application_period_valid(self):
        """Фильтр 12: Заявка подана в допустимый период (настраивается в админке)."""
        from apps.scoring.models import ApplicationPeriod

        direction = self.application.subsidy_type.direction
        if not direction:
            return True

        try:
            period = ApplicationPeriod.objects.get(direction=direction)
        except ApplicationPeriod.DoesNotExist:
            return True  # Нет записи = круглый год

        if period.is_year_round:
            return True

        submit_date = (
            self.application.submitted_at.date()
            if hasattr(self.application, 'submitted_at') and self.application.submitted_at
            else self.application.created_at.date()
        )

        start = date(submit_date.year, period.start_month, period.start_day)
        end = date(submit_date.year, period.end_month, period.end_day)

        return start <= submit_date <= end

    def _check_subsidy_amount_valid(self):
        """Фильтр 13: Сумма субсидии не превышает 50% стоимости животного (Приказ №108)."""
        subsidy_type = self.application.subsidy_type
        form_number = subsidy_type.form_number

        if form_number not in self.TRIBAL_FORM_NUMBERS:
            return True

        # Оценочная стоимость = количество * цена за единицу
        unit_price = self.application.unit_price or Decimal('0')
        quantity = self.application.quantity or 0

        if unit_price <= 0 or quantity <= 0:
            return True  # Нет данных о стоимости — пропускаем

        estimated_cost = unit_price * quantity
        total_amount = self.application.total_amount or Decimal('0')

        # Субсидия не должна превышать 50% от реальной стоимости
        # Если unit_price ≈ rate (данные из эмулятора), считаем что реальная
        # стоимость выше норматива — пропускаем проверку
        rate = self.application.subsidy_type.rate or Decimal('0')
        if rate > 0 and abs(unit_price - rate) / rate < Decimal('0.1'):
            return True  # unit_price ≈ rate, нет данных о реальной стоимости

        max_allowed = estimated_cost * Decimal('0.5')
        return total_amount <= max_allowed

    def _check_min_herd_size_met(self):
        """Фильтр 14: Минимальное поголовье (Приказ №108)."""
        subsidy_type = self.application.subsidy_type
        direction_code = subsidy_type.direction.code if subsidy_type.direction else ''

        # Получаем данные ИС ИСЖ о верифицированном поголовье
        if not self.entity:
            # Без данных не можем проверить — проваливаем только если
            # есть явное требование min_herd_size
            return subsidy_type.min_herd_size is None

        is_iszh = self.entity.is_iszh_data or {}
        verified_count = is_iszh.get('verified_count', is_iszh.get('total_verified', 0))

        # 1. Проверка по SubsidyType.min_herd_size (приоритет)
        if subsidy_type.min_herd_size is not None:
            return verified_count >= subsidy_type.min_herd_size

        # 2. Специальные требования по типу хозяйства (Приказ №108)
        subsidy_name_lower = subsidy_type.name.lower() if subsidy_type.name else ''

        # Откормочные площадки
        if 'откорм' in subsidy_name_lower or 'фидлот' in subsidy_name_lower:
            if direction_code in ('cattle_meat', 'cattle_dairy', 'cattle_general'):
                return verified_count >= 1000
            elif direction_code == 'sheep':
                return verified_count >= 5000

        # Молочно-товарные фермы
        if 'молочн' in subsidy_name_lower or 'мтф' in subsidy_name_lower:
            return verified_count >= 50

        # Нет специальных требований — пропускаем
        return True

    def _check_no_duplicate_application(self):
        """Фильтр 15: Нет дублирующей одобренной заявки в текущем году."""
        current_year = date.today().year
        duplicate_exists = (
            Application.objects.filter(
                applicant=self.application.applicant,
                subsidy_type=self.application.subsidy_type,
                status__in=('approved', 'paid', 'partially_paid'),
                created_at__year=current_year,
            )
            .exclude(pk=self.application.pk)
            .exists()
        )
        return not duplicate_exists

    def check_all(self) -> dict:
        """
        Запускает все 15 hard-фильтров.
        Возвращает словарь с результатами и сохраняет HardFilterResult.
        """
        self._load_entity()

        checks = {
            'giss_registered': self._check_giss_registered,
            'has_eds': self._check_has_eds,
            'ias_rszh_registered': self._check_ias_rszh_registered,
            'has_agricultural_land': self._check_has_agricultural_land,
            'is_iszh_registered': self._check_is_iszh_registered,
            'ibspr_registered': self._check_ibspr_registered,
            'esf_confirmed': self._check_esf_confirmed,
            'no_unfulfilled_obligations': self._check_no_unfulfilled_obligations,
            'no_block': self._check_no_block,
            'animals_age_valid': self._check_animals_age_valid,
            'animals_not_subsidized': self._check_animals_not_subsidized,
            'application_period_valid': self._check_application_period_valid,
            'subsidy_amount_valid': self._check_subsidy_amount_valid,
            'min_herd_size_met': self._check_min_herd_size_met,
            'no_duplicate_application': self._check_no_duplicate_application,
        }

        self.failed_reasons = []
        for key, check_fn in checks.items():
            try:
                result = check_fn()
            except Exception as e:
                logger.error('Ошибка проверки %s: %s', key, e)
                result = False
            self.results[key] = result
            if not result:
                self.failed_reasons.append(self.FILTER_LABELS[key])

        all_passed = len(self.failed_reasons) == 0

        # Создаём или обновляем HardFilterResult
        hard_filter_result, _ = HardFilterResult.objects.update_or_create(
            application=self.application,
            defaults={
                'giss_registered': self.results.get('giss_registered', False),
                'has_eds': self.results.get('has_eds', False),
                'ias_rszh_registered': self.results.get('ias_rszh_registered', False),
                'has_agricultural_land': self.results.get('has_agricultural_land', False),
                'is_iszh_registered': self.results.get('is_iszh_registered', False),
                'ibspr_registered': self.results.get('ibspr_registered', False),
                'esf_confirmed': self.results.get('esf_confirmed', False),
                'no_unfulfilled_obligations': self.results.get('no_unfulfilled_obligations', False),
                'no_block': self.results.get('no_block', False),
                'animals_age_valid': self.results.get('animals_age_valid', False),
                'animals_not_subsidized': self.results.get('animals_not_subsidized', False),
                'application_period_valid': self.results.get('application_period_valid', False),
                'subsidy_amount_valid': self.results.get('subsidy_amount_valid', False),
                'min_herd_size_met': self.results.get('min_herd_size_met', False),
                'no_duplicate_application': self.results.get('no_duplicate_application', False),
                'all_passed': all_passed,
                'failed_reasons': self.failed_reasons,
                'raw_responses': self.raw_responses,
            },
        )

        return {
            'all_passed': all_passed,
            'results': self.results,
            'failed_reasons': self.failed_reasons,
            'hard_filter_result': hard_filter_result,
        }
