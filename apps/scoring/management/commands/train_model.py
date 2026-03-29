"""
Команда для обучения ML модели скоринга.

Собирает данные из EmulatedEntity, рассчитывает «эталонные» баллы
с помощью правил (soft factors), затем обучает Gradient Boosting модели
на этих данных. Модель учится воспроизводить экспертную логику
и выявлять скрытые паттерны.

Использование:
    python manage.py train_model
    python manage.py train_model --limit 200
"""
from django.core.management.base import BaseCommand

from apps.emulator.models import EmulatedEntity
from apps.scoring.ml_model import extract_features, train_model, FEATURE_NAMES


class Command(BaseCommand):
    help = 'Обучить ML модель скоринга на данных EmulatedEntity'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Ограничить количество записей (0 = все)',
        )

    def handle(self, *args, **options):
        limit = options['limit']

        entities = EmulatedEntity.objects.all()
        if limit > 0:
            entities = entities[:limit]

        entity_list = list(entities)
        if not entity_list:
            self.stderr.write(self.style.ERROR(
                'Нет данных EmulatedEntity. Сначала запустите: python manage.py generate_data'
            ))
            return

        self.stdout.write(f'Подготовка данных из {len(entity_list)} записей...')

        entities_data = []
        scores = []
        recommendations = []

        for entity in entity_list:
            entity_data = {
                'giss_data': entity.giss_data,
                'ias_rszh_data': entity.ias_rszh_data,
                'easu_data': entity.easu_data,
                'is_iszh_data': entity.is_iszh_data,
                'is_esf_data': entity.is_esf_data,
                'egkn_data': entity.egkn_data,
                'treasury_data': entity.treasury_data,
                'entity_type': entity.entity_type,
            }

            # Рассчитываем «эталонный» балл правилами
            score = self._calculate_rule_score(entity_data, entity)
            rec = 'approve' if score >= 70 else ('review' if score >= 40 else 'reject')

            entities_data.append(entity_data)
            scores.append(score)
            recommendations.append(rec)

        self.stdout.write('Обучение моделей...')
        metrics = train_model(entities_data, scores, recommendations)

        self.stdout.write(self.style.SUCCESS('\n=== Результаты обучения ==='))
        self.stdout.write(f'  Обучающих примеров: {metrics["n_samples"]}')
        self.stdout.write(f'  R² (балл):         {metrics["score_r2_mean"]:.3f} ± {metrics["score_r2_std"]:.3f}')
        self.stdout.write(f'  Accuracy (рек.):   {metrics["rec_accuracy_mean"]:.3f} ± {metrics["rec_accuracy_std"]:.3f}')

        self.stdout.write('\n  Топ признаки (балл):')
        for f in metrics['top_features_score']:
            self.stdout.write(f'    {f["feature_ru"]}: {f["importance"]:.3f}')

        self.stdout.write('\n  Топ признаки (рекомендация):')
        for f in metrics['top_features_rec']:
            self.stdout.write(f'    {f["feature_ru"]}: {f["importance"]:.3f}')

        self.stdout.write(self.style.SUCCESS('\nМодель сохранена.'))

    def _calculate_rule_score(self, entity_data, entity):
        """
        Рассчитывает балл правилами — аналог SoftFactorCalculator,
        но без привязки к конкретной заявке.
        """
        giss = entity_data.get('giss_data') or {}
        ias = entity_data.get('ias_rszh_data') or {}
        is_iszh = entity_data.get('is_iszh_data') or {}
        is_esf = entity_data.get('is_esf_data') or {}
        egkn = entity_data.get('egkn_data') or {}
        treasury = entity_data.get('treasury_data') or {}

        total = 0.0

        # Factor 1: История субсидий (max 20)
        subsidy_history = ias.get('subsidy_history', [])
        total_subs = len(subsidy_history)
        successful = sum(
            1 for h in subsidy_history
            if h.get('status') == 'executed' and h.get('obligations_met', False)
        )
        success_rate = successful / total_subs if total_subs > 0 else 0
        if total_subs == 0:
            f1 = 10.0
        elif success_rate >= 0.9:
            f1 = 18 + min(total_subs, 2)
        elif success_rate >= 0.7:
            f1 = 14 + (success_rate - 0.7) * 20
        elif success_rate >= 0.5:
            f1 = 8 + (success_rate - 0.5) * 30
        else:
            f1 = success_rate * 16
        total += min(20.0, max(0.0, f1))

        # Factor 2: Рост продукции (max 20)
        growth_rate = giss.get('growth_rate', 0)
        if growth_rate >= 10:
            f2 = 20.0
        elif growth_rate >= 5:
            f2 = 14 + (growth_rate - 5) * 1.2
        elif growth_rate >= 0:
            f2 = 8 + growth_rate * 1.2
        elif growth_rate >= -5:
            f2 = 4 + (growth_rate + 5) * 0.8
        else:
            f2 = max(0, 4 + growth_rate * 0.4)
        total += min(20.0, max(0.0, f2))

        # Factor 3: Размер хозяйства (max 15)
        land_area = egkn.get('total_agricultural_area', 0)
        herd_size = is_iszh.get('total_verified', 0)
        if land_area >= 500:
            land_s = 8.0
        elif land_area >= 100:
            land_s = 4 + (land_area - 100) / 100
        elif land_area >= 10:
            land_s = land_area / 25
        else:
            land_s = 0.0
        if herd_size >= 200:
            herd_s = 7.0
        elif herd_size >= 50:
            herd_s = 3.5 + (herd_size - 50) / 42.8
        elif herd_size >= 10:
            herd_s = herd_size / 14.3
        else:
            herd_s = 0.0
        total += min(15.0, max(0.0, land_s + herd_s))

        # Factor 4: Сохранность (max 15)
        total_heads = sum(h.get('heads', 0) for h in subsidy_history)
        returns = ias.get('pending_returns', 0)
        if total_heads == 0:
            f4 = 10.0
        else:
            ret_rate = 1 - (returns / total_heads)
            ret_rate = max(0.0, min(1.0, ret_rate))
            if ret_rate >= 0.98:
                f4 = 15.0
            elif ret_rate >= 0.90:
                f4 = 11 + (ret_rate - 0.90) * 50
            elif ret_rate >= 0.80:
                f4 = 7 + (ret_rate - 0.80) * 40
            else:
                f4 = ret_rate * 8.75
        total += min(15.0, max(0.0, f4))

        # Factor 5: Соответствие нормативу (max 10)
        esf_total = is_esf.get('total_amount', 0)
        if esf_total > 0:
            f5 = 8.0
        else:
            f5 = 2.0
        total += min(10.0, f5)

        # Factor 6: Региональный приоритет (max 10) — default
        total += 5.0  # regional priority default

        # Factor 7: Тип заявителя (max 5)
        et = entity.entity_type
        if et == 'cooperative':
            f7 = 5.0
        elif et == 'legal':
            f7 = 4.0
        else:
            f7 = 3.0
        total += f7

        # Factor 8: Первичность (max 5)
        if total_subs == 0:
            f8 = 4.0
        elif total_subs <= 3:
            f8 = 3.0
        else:
            f8 = 2.0
        total += f8

        # Hard filter penalty: если ключевые проверки провалены
        if not giss.get('registered', False):
            total *= 0.3
        if giss.get('blocked', False):
            total *= 0.1
        if not egkn.get('has_agricultural_land', False):
            total *= 0.5

        return round(min(100.0, max(0.0, total)), 2)
