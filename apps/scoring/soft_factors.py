import logging

from apps.scoring.models import Application

logger = logging.getLogger(__name__)

# Региональные приоритеты по направлениям (0.0 — 1.0)
# Ключ: (region_keyword, direction_code) -> priority
REGION_PRIORITIES = {
    # Мясное скотоводство — приоритет степные и полустепные регионы
    ('Акмолинская', 'cattle_meat'): 0.8,
    ('Костанайская', 'cattle_meat'): 0.9,
    ('Павлодарская', 'cattle_meat'): 0.7,
    ('Восточно-Казахстанская', 'cattle_meat'): 0.8,
    ('Карагандинская', 'cattle_meat'): 0.7,
    ('Западно-Казахстанская', 'cattle_meat'): 0.6,
    ('Северо-Казахстанская', 'cattle_meat'): 0.8,
    ('Туркестанская', 'cattle_meat'): 0.5,
    ('Алматинская', 'cattle_meat'): 0.6,
    ('Жамбылская', 'cattle_meat'): 0.5,
    ('Кызылординская', 'cattle_meat'): 0.4,
    ('Атырауская', 'cattle_meat'): 0.4,
    ('Мангистауская', 'cattle_meat'): 0.3,
    ('Актюбинская', 'cattle_meat'): 0.6,
    ('Абай', 'cattle_meat'): 0.7,
    ('Жетісу', 'cattle_meat'): 0.6,
    ('Ұлытау', 'cattle_meat'): 0.5,
    # Молочное скотоводство
    ('Акмолинская', 'cattle_dairy'): 0.9,
    ('Костанайская', 'cattle_dairy'): 0.8,
    ('Северо-Казахстанская', 'cattle_dairy'): 0.9,
    ('Алматинская', 'cattle_dairy'): 0.7,
    ('Восточно-Казахстанская', 'cattle_dairy'): 0.7,
    ('Павлодарская', 'cattle_dairy'): 0.6,
    # Овцеводство
    ('Туркестанская', 'sheep'): 0.9,
    ('Алматинская', 'sheep'): 0.8,
    ('Жамбылская', 'sheep'): 0.8,
    ('Восточно-Казахстанская', 'sheep'): 0.7,
    ('Кызылординская', 'sheep'): 0.6,
    # Коневодство
    ('Костанайская', 'horse'): 0.9,
    ('Акмолинская', 'horse'): 0.7,
    ('Павлодарская', 'horse'): 0.6,
    ('Атырауская', 'horse'): 0.7,
    ('Мангистауская', 'horse'): 0.6,
    # Птицеводство
    ('Алматинская', 'poultry'): 0.9,
    ('Акмолинская', 'poultry'): 0.8,
    ('Костанайская', 'poultry'): 0.7,
    # Свиноводство
    ('Костанайская', 'pig'): 0.8,
    ('Северо-Казахстанская', 'pig'): 0.7,
    ('Акмолинская', 'pig'): 0.7,
}

# Значение по умолчанию для регионов, не указанных в справочнике
DEFAULT_REGION_PRIORITY = 0.5


def get_region_priority(region: str, direction_code: str) -> float:
    """Возвращает приоритет региона для данного направления (0.0-1.0)."""
    for (region_key, dir_code), priority in REGION_PRIORITIES.items():
        if region_key in region and dir_code == direction_code:
            return priority
    return DEFAULT_REGION_PRIORITY


class SoftFactorCalculator:
    """
    Рассчитывает 8 мягких факторов скоринга на основе данных
    из EmulatedEntity JSON-полей.

    Каждый фактор возвращает:
        value, max_value, weight, weighted_value, explanation, data_source
    """

    def __init__(self, application: Application, entity_data: dict):
        """
        Args:
            application: объект Application
            entity_data: словарь с данными из EmulatedEntity:
                {
                    'giss_data': {...},
                    'ias_rszh_data': {...},
                    'easu_data': {...},
                    'is_iszh_data': {...},
                    'is_esf_data': {...},
                    'egkn_data': {...},
                    'treasury_data': {...},
                    'entity_type': '...',
                }
        """
        self.application = application
        self.giss_data = entity_data.get('giss_data', {}) or {}
        self.ias_rszh_data = entity_data.get('ias_rszh_data', {}) or {}
        self.easu_data = entity_data.get('easu_data', {}) or {}
        self.is_iszh_data = entity_data.get('is_iszh_data', {}) or {}
        self.is_esf_data = entity_data.get('is_esf_data', {}) or {}
        self.egkn_data = entity_data.get('egkn_data', {}) or {}
        self.treasury_data = entity_data.get('treasury_data', {}) or {}
        self.entity_type = entity_data.get('entity_type', 'individual')
        self.db_history = entity_data.get('db_history', {}) or {}

    def calculate_all(self) -> list[dict]:
        """Рассчитывает все 8 факторов. Возвращает список словарей."""
        return [
            self._calc_subsidy_history(),
            self._calc_production_growth(),
            self._calc_farm_size(),
            self._calc_efficiency(),
            self._calc_rate_compliance(),
            self._calc_region_priority(),
            self._calc_entity_type(),
            self._calc_applicant_history(),
        ]

    def _calc_subsidy_history(self) -> dict:
        """Factor 1: История субсидий (max 20, weight 0.20)."""
        subsidy_history = self.ias_rszh_data.get('subsidy_history', [])
        total_subsidies = len(subsidy_history)

        successful = sum(
            1
            for h in subsidy_history
            if h.get('status') == 'executed' and h.get('obligations_met', False)
        )
        success_rate = successful / total_subsidies if total_subsidies > 0 else 0

        # Prefer DB history data when available (more accurate than JSON)
        db_hist = self.db_history
        if db_hist.get('total_past_apps', 0) > 0:
            db_total = db_hist['total_past_apps']
            db_success_rate = db_hist.get('success_rate', 0)
            # Use DB data if it has more records or JSON is empty
            if db_total >= total_subsidies:
                total_subsidies = db_total
                successful = db_hist['success_count']
                success_rate = db_success_rate

        if total_subsidies == 0:
            score = 10.0  # нейтральный — первичный заявитель
        elif success_rate >= 0.9:
            score = 18 + min(total_subsidies, 2)  # 18-20
        elif success_rate >= 0.7:
            score = 14 + (success_rate - 0.7) * 20  # 14-18
        elif success_rate >= 0.5:
            score = 8 + (success_rate - 0.5) * 30  # 8-14
        else:
            score = success_rate * 16  # 0-8

        score = min(20.0, max(0.0, score))

        returns_count = sum(
            1 for h in self.ias_rszh_data.get('subsidy_history', [])
            if not h.get('obligations_met', True)
        )
        data_source = 'ias_rszh'
        if db_hist.get('total_past_apps', 0) > 0 and db_hist['total_past_apps'] >= len(self.ias_rszh_data.get('subsidy_history', [])):
            data_source = 'ias_rszh + db'

        if total_subsidies == 0:
            explanation = 'Первичный заявитель — нет истории субсидий'
        else:
            explanation = (
                f'{total_subsidies} субсидий, {successful} успешных '
                f'({success_rate:.0%}), {returns_count} невыполненных обязательств'
            )

        weight = 0.20
        return {
            'factor_code': 'subsidy_history',
            'factor_name': 'История субсидий',
            'value': round(score, 2),
            'max_value': 20.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': data_source,
            'raw_data': {
                'total_subsidies': total_subsidies,
                'successful': successful,
                'success_rate': round(success_rate, 4),
                'db_history_used': db_hist.get('total_past_apps', 0) > 0,
            },
        }

    def _calc_production_growth(self) -> dict:
        """Factor 2: Рост валовой продукции (max 20, weight 0.20)."""
        growth_rate = self.giss_data.get('growth_rate', 0)
        prev_year = self.giss_data.get('gross_production_previous_year', 0)
        year_before = self.giss_data.get('gross_production_year_before', 0)

        if growth_rate >= 10:
            score = 20.0
        elif growth_rate >= 5:
            score = 14 + (growth_rate - 5) * 1.2  # 14-20
        elif growth_rate >= 0:
            score = 8 + growth_rate * 1.2  # 8-14
        elif growth_rate >= -5:
            score = 4 + (growth_rate + 5) * 0.8  # 4-8
        else:
            score = max(0, 4 + growth_rate * 0.4)  # 0-4

        score = min(20.0, max(0.0, score))

        def fmt_amount(val):
            if val >= 1_000_000:
                return f'{val / 1_000_000:.1f}M тг'
            elif val >= 1_000:
                return f'{val / 1_000:.0f}K тг'
            return f'{val:.0f} тг'

        if growth_rate >= 0:
            dynamics = 'положительная динамика'
        elif growth_rate >= -5:
            dynamics = 'незначительное снижение'
        else:
            dynamics = 'существенное снижение'

        explanation = (
            f'Валовая продукция: {fmt_amount(prev_year)} (пред. год) vs '
            f'{fmt_amount(year_before)} (год ранее), '
            f'рост {growth_rate:+.1f}% — {dynamics}'
        )

        weight = 0.20
        return {
            'factor_code': 'production_growth',
            'factor_name': 'Рост валовой продукции',
            'value': round(score, 2),
            'max_value': 20.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': 'giss',
            'raw_data': {
                'growth_rate': growth_rate,
                'gross_production_previous_year': prev_year,
                'gross_production_year_before': year_before,
            },
        }

    def _calc_farm_size(self) -> dict:
        """Factor 3: Размер хозяйства (max 15, weight 0.15)."""
        land_area = self.egkn_data.get('total_agricultural_area', 0)
        herd_size = self.is_iszh_data.get('total_verified', 0)

        # Земля: 0-8 баллов
        if land_area >= 500:
            land_score = 8.0
        elif land_area >= 100:
            land_score = 4 + (land_area - 100) / 100  # 4-8
        elif land_area >= 10:
            land_score = land_area / 25  # 0.4-4
        else:
            land_score = 0.0

        # Поголовье: 0-7 баллов
        if herd_size >= 200:
            herd_score = 7.0
        elif herd_size >= 50:
            herd_score = 3.5 + (herd_size - 50) / 42.8  # 3.5-7
        elif herd_size >= 10:
            herd_score = herd_size / 14.3  # 0.7-3.5
        else:
            herd_score = 0.0

        score = min(15.0, max(0.0, land_score + herd_score))

        # Определяем размер
        if score >= 12:
            size_label = 'крупное хозяйство'
        elif score >= 7:
            size_label = 'среднее хозяйство'
        elif score >= 3:
            size_label = 'малое хозяйство'
        else:
            size_label = 'микрохозяйство'

        explanation = (
            f'{land_area:.1f} га с/х земли, {herd_size} голов — {size_label}'
        )

        weight = 0.15
        return {
            'factor_code': 'farm_size',
            'factor_name': 'Размер хозяйства',
            'value': round(score, 2),
            'max_value': 15.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': 'egkn',
            'raw_data': {
                'land_area': land_area,
                'herd_size': herd_size,
                'land_score': round(land_score, 2),
                'herd_score': round(herd_score, 2),
            },
        }

    def _calc_efficiency(self) -> dict:
        """Factor 4: Эффективность — сохранность поголовья (max 15, weight 0.15)."""
        subsidy_history = self.ias_rszh_data.get('subsidy_history', [])
        total_heads_subsidized = sum(h.get('heads', 0) for h in subsidy_history)
        returns = self.ias_rszh_data.get('pending_returns', 0)

        if total_heads_subsidized == 0:
            score = 10.0  # нейтральный — нет истории
            retention_rate = None
        else:
            retention_rate = 1 - (returns / total_heads_subsidized)
            retention_rate = max(0.0, min(1.0, retention_rate))
            if retention_rate >= 0.98:
                score = 15.0
            elif retention_rate >= 0.90:
                score = 11 + (retention_rate - 0.90) * 50  # 11-15
            elif retention_rate >= 0.80:
                score = 7 + (retention_rate - 0.80) * 40  # 7-11
            else:
                score = retention_rate * 8.75  # 0-7

        score = min(15.0, max(0.0, score))

        if retention_rate is None:
            explanation = 'Нет истории субсидирования поголовья — нейтральная оценка'
        else:
            explanation = (
                f'Сохранность {retention_rate:.0%} — {returns} возвратов '
                f'из {total_heads_subsidized} просубсидированных голов'
            )

        weight = 0.15
        return {
            'factor_code': 'efficiency',
            'factor_name': 'Эффективность (сохранность)',
            'value': round(score, 2),
            'max_value': 15.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': 'ias_rszh',
            'raw_data': {
                'total_heads_subsidized': total_heads_subsidized,
                'pending_returns': returns,
                'retention_rate': round(retention_rate, 4) if retention_rate is not None else None,
            },
        }

    def _calc_rate_compliance(self) -> dict:
        """Factor 5: Соответствие нормативу (max 10, weight 0.10)."""
        esf_total = self.is_esf_data.get('total_amount', 0)
        requested = float(self.application.total_amount)
        expected = float(self.application.quantity) * float(self.application.rate)
        unit_price = float(self.application.unit_price) if self.application.unit_price else 0
        actual_cost = float(self.application.quantity) * unit_price

        # Проверка: запрашиваемая сумма соответствует нормативу (допуск 1%)
        rate_match = abs(requested - expected) <= expected * 0.01 if expected > 0 else False

        # Проверка: ЭСФ покрывает фактическую стоимость
        esf_covers = esf_total >= actual_cost if actual_cost > 0 else esf_total > 0

        if rate_match and esf_covers:
            score = 10.0
        elif rate_match and not esf_covers:
            score = 6.0
        elif not rate_match and esf_covers:
            score = 4.0
        else:
            score = 2.0

        parts = []
        parts.append(
            f'Запрошено {requested:,.0f} тг '
            f'({self.application.quantity} ед. x {float(self.application.rate):,.0f} тг)'
        )
        if rate_match:
            parts.append('точно по нормативу')
        else:
            parts.append(f'расхождение с нормативом ({expected:,.0f} тг)')
        if esf_covers:
            parts.append(f'ЭСФ на {esf_total:,.0f} тг покрывает стоимость')
        else:
            parts.append(f'ЭСФ на {esf_total:,.0f} тг не покрывает стоимость ({actual_cost:,.0f} тг)')

        explanation = '. '.join(parts)

        weight = 0.10
        return {
            'factor_code': 'rate_compliance',
            'factor_name': 'Соответствие нормативу',
            'value': round(score, 2),
            'max_value': 10.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': 'is_esf',
            'raw_data': {
                'esf_total': esf_total,
                'requested': requested,
                'expected': expected,
                'rate_match': rate_match,
                'esf_covers': esf_covers,
            },
        }

    def _calc_region_priority(self) -> dict:
        """Factor 6: Региональный приоритет (max 10, weight 0.10)."""
        region = self.application.region
        direction_code = self.application.subsidy_type.direction.code

        priority = get_region_priority(region, direction_code)
        score = priority * 10

        score = min(10.0, max(0.0, score))

        level = 'приоритетный' if priority >= 0.7 else ('средний' if priority >= 0.4 else 'низкий')
        direction_name = self.application.subsidy_type.direction.name

        explanation = (
            f'{region} — {level} регион для направления '
            f'«{direction_name}» ({score:.0f}/10)'
        )

        weight = 0.10
        return {
            'factor_code': 'region_priority',
            'factor_name': 'Региональный приоритет',
            'value': round(score, 2),
            'max_value': 10.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': 'reference',
            'raw_data': {
                'region': region,
                'direction_code': direction_code,
                'priority': priority,
            },
        }

    def _calc_entity_type(self) -> dict:
        """Factor 7: Тип заявителя (max 5, weight 0.05)."""
        entity_type = self.application.applicant.entity_type

        if entity_type == 'cooperative':
            score = 5.0
            label = 'С/х кооператив (СПК) — максимальный приоритет (кооперация)'
        elif entity_type == 'legal':
            score = 4.0
            label = 'Юридическое лицо — стабильная организационная форма'
        else:  # individual
            score = 3.0
            label = 'Физическое лицо — базовый приоритет'

        weight = 0.05
        return {
            'factor_code': 'entity_type',
            'factor_name': 'Тип заявителя',
            'value': round(score, 2),
            'max_value': 5.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': label,
            'data_source': 'easu',
            'raw_data': {
                'entity_type': entity_type,
            },
        }

    def _calc_applicant_history(self) -> dict:
        """Factor 8: Первичность заявителя (max 5, weight 0.05)."""
        subsidy_history = self.ias_rszh_data.get('subsidy_history', [])
        total_subsidies = len(subsidy_history)

        direction_code = self.application.subsidy_type.direction.code
        has_same_direction = any(
            h.get('type', '') == direction_code for h in subsidy_history
        )

        # Prefer DB history when available (more accurate)
        db_hist = self.db_history
        db_total = db_hist.get('total_past_apps', 0)
        if db_total > 0 and db_total >= total_subsidies:
            total_subsidies = db_total

        data_source = 'ias_rszh'
        if db_total > 0 and db_total >= len(self.ias_rszh_data.get('subsidy_history', [])):
            data_source = 'ias_rszh + db'

        if total_subsidies == 0:
            score = 4.0
            explanation = 'Первичный заявитель — приоритет поддержки новых участников'
        elif not has_same_direction and db_total == 0:
            # Only claim diversification if JSON data says so and no DB override
            score = 5.0
            explanation = (
                f'Диверсификация — {total_subsidies} субсидий по другим направлениям, '
                f'новое направление для заявителя'
            )
        elif total_subsidies <= 3:
            score = 3.0
            explanation = f'Умеренный повторный заявитель ({total_subsidies} заявок)'
        else:
            score = 2.0
            explanation = f'Частый заявитель ({total_subsidies} заявок)'

        # Enrich explanation with DB avg score if available
        if db_hist.get('avg_past_score'):
            explanation += f', средний балл по прошлым заявкам: {db_hist["avg_past_score"]:.1f}'

        weight = 0.05
        return {
            'factor_code': 'applicant_history',
            'factor_name': 'Первичность заявителя',
            'value': round(score, 2),
            'max_value': 5.0,
            'weight': weight,
            'weighted_value': round(score * weight, 2),
            'explanation': explanation,
            'data_source': data_source,
            'raw_data': {
                'total_subsidies': total_subsidies,
                'has_same_direction': has_same_direction,
                'db_total_apps': db_total,
                'db_avg_score': db_hist.get('avg_past_score'),
            },
        }
