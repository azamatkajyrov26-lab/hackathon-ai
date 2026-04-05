import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.emulator.models import EmulatedEntity
from apps.scoring.hard_filters import HardFilterChecker
from apps.scoring.ml_model import predict_score, extract_features, explain_with_shap
from apps.scoring.models import Application, Score, ScoreFactor, Budget, Notification
from apps.scoring.soft_factors import SoftFactorCalculator

logger = logging.getLogger(__name__)

MODEL_VERSION = '2.0-ml'


class ScoringEngine:
    """
    Оркестрирует полный процесс скоринга заявки:
      1. Hard Filters — бинарные проверки (pass/fail)
      2. Soft Factors — расчёт 8 факторов (0-100 баллов)
      3. Score + Recommendation — итоговая оценка
      4. Explainability — обоснование на русском языке
    """

    def run_scoring(self, application: Application) -> dict:
        """
        Запускает полный скоринг для одной заявки.

        Возвращает словарь:
            {
                'success': bool,
                'hard_filters': {...},
                'score': Score | None,
                'factors': [...],
                'total_score': float,
                'recommendation': str,
                'recommendation_reason': str,
            }
        """
        logger.info('Запуск скоринга для заявки %s', application.number)

        # --- Шаг 1: Загрузка данных из EmulatedEntity ---
        entity = self._get_entity(application)
        if entity is None:
            logger.error(
                'EmulatedEntity не найден для ИИН/БИН %s',
                application.applicant.iin_bin,
            )
            return {
                'success': False,
                'error': f'Данные не найдены для ИИН/БИН {application.applicant.iin_bin}',
                'hard_filters': None,
                'score': None,
                'factors': [],
                'total_score': 0,
                'recommendation': 'reject',
                'recommendation_reason': (
                    'Данные заявителя не найдены в информационных системах. '
                    'Невозможно выполнить скоринг.'
                ),
            }

        # --- Шаг 2: Hard Filters ---
        checker = HardFilterChecker(application)
        hf_result = checker.check_all()

        if not hf_result['all_passed']:
            # Hard filter не пройден — ОТКАЗ по Приказу №108 МСХ РК.
            # Заявка отклоняется автоматически с указанием причин.
            reject_message = self._build_info_notification(hf_result['failed_reasons'])

            application.status = 'rejected'
            application.save(update_fields=['status', 'updated_at'])

            # Отправляем уведомление фермеру с причинами отказа
            self._send_hard_filter_notification(application, hf_result['failed_reasons'])

            logger.info(
                'Заявка %s: hard filters FAIL — ОТКАЗ — %s',
                application.number,
                ', '.join(hf_result['failed_reasons']),
            )

            return {
                'success': True,
                'hard_filters': hf_result,
                'score': None,
                'factors': [],
                'total_score': 0,
                'recommendation': 'reject',
                'recommendation_reason': reject_message,
            }

        # --- Шаг 3: Soft Factors ---
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

        # --- Шаг 3.1: Обогащение данными из БД (история заявок) ---
        past_apps = Application.objects.filter(
            applicant=application.applicant,
        ).exclude(id=application.id)

        total_past_apps = past_apps.count()
        success_count = past_apps.filter(status__in=['approved', 'paid', 'partially_paid']).count()
        from django.db.models import Sum as DbSum, Avg as DbAvg
        total_past_amount = past_apps.filter(
            status__in=['paid', 'partially_paid']
        ).aggregate(s=DbSum('total_amount'))['s'] or 0
        avg_past_score = Score.objects.filter(
            application__in=past_apps,
        ).aggregate(avg=DbAvg('total_score'))['avg']

        entity_data['db_history'] = {
            'total_past_apps': total_past_apps,
            'success_count': success_count,
            'success_rate': round(success_count / total_past_apps, 4) if total_past_apps > 0 else 0,
            'total_past_amount': float(total_past_amount),
            'avg_past_score': round(float(avg_past_score), 2) if avg_past_score else None,
        }

        calculator = SoftFactorCalculator(application, entity_data)
        factors = calculator.calculate_all()

        # --- Шаг 4: Итоговый балл (правила) ---
        # Суммируем value (не weighted_value), т.к. max_value по факторам уже = 100
        # (20+20+15+15+10+10+5+5 = 100)
        rule_score = sum(f['value'] for f in factors)
        rule_score = round(min(100.0, max(0.0, rule_score)), 2)

        # --- Шаг 4.1: ML-предсказание ---
        ml_result = predict_score(entity_data)
        shap_explanation = {}
        if ml_result:
            # Гибридный скоринг: 60% ML + 40% правила
            ml_score = ml_result['ml_score']
            total_score = round(0.6 * ml_score + 0.4 * rule_score, 2)
            ml_recommendation = ml_result['ml_recommendation']
            ml_confidence = ml_result['confidence']
            feature_contributions = ml_result['feature_contributions']
            logger.info(
                'ML предсказание: %.2f (уверенность %.1f%%), правила: %.2f → итого: %.2f',
                ml_score, ml_confidence * 100, rule_score, total_score,
            )

            # --- SHAP explainability ---
            shap_result = explain_with_shap(entity_data)
            if shap_result:
                shap_explanation = shap_result
                logger.info('SHAP-объяснение вычислено: base=%.2f, %d факторов',
                            shap_result['base_value'], len(shap_result['shap_values']))
        else:
            # Fallback: только правила
            total_score = rule_score
            ml_result = None
            ml_confidence = 0
            feature_contributions = []

        total_score = round(min(100.0, max(0.0, total_score)), 2)

        # --- Шаг 5: Рекомендация ---
        recommendation = self._get_recommendation(total_score)
        recommendation_reason = self._build_recommendation_reason(
            total_score, recommendation, factors, application,
            ml_result=ml_result, rule_score=rule_score,
            db_history=entity_data.get('db_history'),
        )

        # --- Шаг 6: Сохранение в БД ---
        with transaction.atomic():
            score_obj, _ = Score.objects.update_or_create(
                application=application,
                defaults={
                    'total_score': Decimal(str(total_score)),
                    'recommendation': recommendation,
                    'recommendation_reason': recommendation_reason,
                    'explanation': shap_explanation,
                    'model_version': MODEL_VERSION,
                },
            )

            # Удаляем старые факторы и создаём новые
            ScoreFactor.objects.filter(score=score_obj).delete()
            for f in factors:
                ScoreFactor.objects.create(
                    score=score_obj,
                    factor_code=f['factor_code'],
                    factor_name=f['factor_name'],
                    value=Decimal(str(f['value'])),
                    max_value=Decimal(str(f['max_value'])),
                    weight=Decimal(str(f['weight'])),
                    weighted_value=Decimal(str(f['weighted_value'])),
                    explanation=f['explanation'],
                    data_source=f['data_source'],
                    raw_data=f.get('raw_data', {}),
                )

            # --- Шаг 6.1: Проверка бюджета ---
            budget_available = self._check_budget(application)

            # ИИ-скоринг НЕ меняет статус заявки — только даёт рекомендацию.
            # Статус проходит через: submitted → checking (специалист) → approved/rejected (комиссия)
            # Единственное исключение: hard filter rejection (критический отказ)
            if recommendation == 'reject' and total_score < 20:
                # Автоматический отказ только при критически низком балле (жёсткие фильтры)
                application.status = 'rejected'
            elif application.status == 'draft':
                application.status = 'submitted'
            application.save(update_fields=['status', 'updated_at'])

            # --- Шаг 6.2: Уведомление заявителю ---
            self._create_notification(application, total_score, recommendation, budget_available)

        # --- Шаг 6.3: Проверка встречных обязательств (Приказ №108) ---
        try:
            self._check_subsidy_obligations(application, entity)
        except Exception as e:
            logger.warning('Ошибка проверки встречных обязательств: %s', e)

        # --- Шаг 7: Обновление рейтинга ---
        try:
            self.update_rankings(
                application.region,
                application.subsidy_type.direction.code,
            )
        except Exception as e:
            logger.warning('Ошибка обновления рейтинга: %s', e)

        logger.info(
            'Заявка %s: скоринг завершён — %.2f баллов, рекомендация: %s',
            application.number,
            total_score,
            recommendation,
        )

        return {
            'success': True,
            'hard_filters': hf_result,
            'score': score_obj,
            'factors': factors,
            'total_score': total_score,
            'recommendation': recommendation,
            'recommendation_reason': recommendation_reason,
        }

    def update_rankings(self, region: str, direction_code: str):
        """
        Пересчитывает ранг (позицию в рейтинге) для всех оценённых заявок
        в заданном регионе и направлении.

        Ранг определяется по убыванию total_score в рамках одной
        комбинации (region + direction).
        """
        scores = (
            Score.objects.filter(
                application__region=region,
                application__subsidy_type__direction__code=direction_code,
                application__status__in=['approved', 'checking', 'waiting_list'],
            )
            .select_related('application')
            .order_by('-total_score', 'application__submitted_at')
        )

        with transaction.atomic():
            for rank, score in enumerate(scores, start=1):
                if score.rank != rank:
                    score.rank = rank
                    score.save(update_fields=['rank'])

        logger.info(
            'Рейтинг обновлён: %s / %s — %d заявок',
            region,
            direction_code,
            scores.count(),
        )

    @staticmethod
    def _find_applicant_user(application):
        """Находит Django User, привязанного к заявителю по ИИН/БИН."""
        from apps.scoring.models import UserProfile
        iin_bin = application.applicant.iin_bin
        profile = UserProfile.objects.filter(
            iin_bin=iin_bin,
            role='applicant',
        ).select_related('user').first()
        if profile:
            return profile.user
        return None

    def _get_entity(self, application: Application):
        """Получает EmulatedEntity по ИИН/БИН заявителя."""
        try:
            return EmulatedEntity.objects.get(
                iin_bin=application.applicant.iin_bin
            )
        except EmulatedEntity.DoesNotExist:
            return None

    def _get_recommendation(self, total_score: float) -> str:
        """Определяет рекомендацию по итоговому баллу."""
        if total_score >= 70:
            return 'approve'
        elif total_score >= 40:
            return 'review'
        else:
            return 'reject'

    # Подробные рекомендации по каждому фильтру — что делать фермеру
    FILTER_ACTIONS = {
        'giss_registered': (
            'Вы не зарегистрированы в ГИСС (Государственная информационная система субсидирования). '
            'Обратитесь в местное управление сельского хозяйства для регистрации в системе Qoldau (qoldau.kz).'
        ),
        'has_eds': (
            'Отсутствует действующая электронная цифровая подпись (ЭЦП). '
            'Получите или обновите ЭЦП в ЦОН или через eGov.kz (раздел NCALayer).'
        ),
        'ias_rszh_registered': (
            'Нет учётной записи в ИАС «РСЖ». '
            'Обратитесь в районное управление сельского хозяйства для регистрации.'
        ),
        'has_agricultural_land': (
            'В ЕГКН не найдены земельные участки сельскохозяйственного назначения на ваше имя. '
            'Если земля есть — проверьте правильность регистрации в земельном кадастре. '
            'Обратитесь в ЦОН или акимат для актуализации данных.'
        ),
        'esf_confirmed': (
            'Не найдены подтверждённые электронные счёт-фактуры (ЭСФ). '
            'Убедитесь что ваши покупки скота, кормов и оборудования оформлены через ЭСФ (esf.gov.kz). '
            'При покупке требуйте от продавца выписку ЭСФ на ваш ИИН/БИН.'
        ),
        'no_unfulfilled_obligations': (
            'У вас есть невыполненные обязательства по предыдущим субсидиям. '
            'Необходимо исполнить условия ранее полученных субсидий или урегулировать вопрос '
            'с управлением сельского хозяйства.'
        ),
        'no_block': (
            'Ваш аккаунт заблокирован в системе субсидирования. '
            'Причина указана в профиле. Обратитесь в управление сельского хозяйства '
            'для разблокировки после устранения нарушений.'
        ),
        'animals_age_valid': (
            'Возраст некоторых животных не соответствует требованиям для данного типа субсидии. '
            'Проверьте возрастные ограничения в Приказе №108 для выбранного направления. '
            'Обновите данные в ИС ИЖ через ветеринарного инспектора.'
        ),
        'animals_not_subsidized': (
            'Часть заявленных животных уже получала субсидию ранее. '
            'Субсидия на одно животное выделяется однократно. '
            'Исключите ранее субсидированных животных из заявки.'
        ),
        'application_period_valid': (
            'Заявка подана вне установленного периода приёма. '
            'Проверьте сроки подачи заявок для вашего направления '
            'в разделе "Периоды приёма" или уточните в управлении сельского хозяйства.'
        ),
        'subsidy_amount_valid': (
            'Запрашиваемая сумма субсидии превышает 50% от стоимости. '
            'Скорректируйте количество голов или проверьте правильность расчёта.'
        ),
        'min_herd_size_met': (
            'Ваше поголовье не соответствует минимальным требованиям для данного типа субсидии. '
            'Проверьте требования к минимальному размеру стада для выбранного направления.'
        ),
        'no_duplicate_application': (
            'Вы уже подавали заявку на этот тип субсидии в текущем году. '
            'Повторная подача на тот же тип субсидии в рамках одного года не допускается.'
        ),
        'is_iszh_registered': (
            'Ваши животные не зарегистрированы в ИС ИЖ (система идентификации животных). '
            'Обратитесь к районному ветеринару для биркования и регистрации скота.'
        ),
        'ibspr_registered': (
            'Нет регистрации в ИБСПР. '
            'Обратитесь в управление сельского хозяйства для регистрации.'
        ),
    }

    def _build_rejection_reason(self, failed_reasons: list[str]) -> str:
        """Формирует мотивированный отказ по результатам hard filters."""
        reasons_text = '; '.join(failed_reasons)
        return (
            f'Заявка не прошла обязательные проверки. '
            f'Не выполнены следующие условия: {reasons_text}. '
            f'Рекомендация: устранить указанные несоответствия и подать заявку повторно.'
        )

    def _build_info_notification(self, failed_reasons: list[str]) -> str:
        """Формирует сообщение об отказе по результатам обязательных проверок (Приказ №108)."""
        reasons_text = '; '.join(failed_reasons)
        return (
            f'Заявка отклонена по результатам обязательных проверок (Приказ №108 МСХ РК). '
            f'Не выполнены условия: {reasons_text}. '
            f'Устраните несоответствия и подайте заявку повторно.'
        )

    def _send_hard_filter_notification(self, application, failed_reasons: list[str]):
        """Отправляет подробное уведомление фермеру с рекомендациями по каждому фильтру."""
        from apps.scoring.models import Notification, UserProfile
        from apps.scoring.hard_filters import HardFilterChecker

        target_user = self._find_applicant_user(application)
        if not target_user:
            return

        # Собираем подробные рекомендации
        details = []
        for i, reason in enumerate(failed_reasons, 1):
            # Пытаемся найти ключ фильтра по описанию
            action = None
            for key, label in HardFilterChecker.FILTER_LABELS.items():
                if label in reason or reason in label:
                    action = self.FILTER_ACTIONS.get(key)
                    break
            if not action:
                # Поиск по ключевым словам
                for key, act in self.FILTER_ACTIONS.items():
                    if any(word in reason.lower() for word in key.replace('_', ' ').split()):
                        action = act
                        break
            if not action:
                action = 'Обратитесь в управление сельского хозяйства для уточнения.'

            details.append(f'{i}. {reason}\n   Что делать: {action}')

        details_text = '\n\n'.join(details)

        message = (
            f'Заявка {application.number} отклонена по результатам обязательных проверок '
            f'(Приказ №108 МСХ РК).\n\n'
            f'Не выполнены следующие условия:\n\n'
            f'{details_text}\n\n'
            f'После устранения указанных несоответствий вы можете подать заявку повторно.\n\n'
            f'По вопросам обращайтесь в управление сельского хозяйства вашего района.'
        )

        Notification.objects.create(
            user=target_user,
            application=application,
            notification_type='hard_filter_fail',
            title=f'Отказ по заявке {application.number} — обязательные проверки не пройдены',
            message=message,
        )

    def _build_recommendation_reason(
        self,
        total_score: float,
        recommendation: str,
        factors: list[dict],
        application: Application,
        ml_result: dict | None = None,
        rule_score: float = 0,
        db_history: dict | None = None,
    ) -> str:
        """Генерирует текстовое обоснование рекомендации на русском языке."""
        # Сортируем факторы по weighted_value (лучшие первыми)
        sorted_factors = sorted(factors, key=lambda f: f['weighted_value'], reverse=True)

        # Сильные стороны (>= 70% от максимума)
        strengths = [
            f for f in sorted_factors
            if f['max_value'] > 0 and (f['value'] / f['max_value']) >= 0.7
        ]

        # Слабые стороны (< 40% от максимума)
        weaknesses = [
            f for f in sorted_factors
            if f['max_value'] > 0 and (f['value'] / f['max_value']) < 0.4
        ]

        parts = []

        # ML model info
        if ml_result:
            ml_score = ml_result['ml_score']
            confidence = ml_result['confidence']
            parts.append(
                f'[AI модель: {ml_score:.1f} баллов, уверенность {confidence:.0%}; '
                f'Правила: {rule_score:.1f}; Итого: {total_score:.1f}/100]'
            )
            # Top ML feature contributions
            contribs = ml_result.get('feature_contributions', [])[:3]
            if contribs:
                contrib_text = ', '.join(
                    f'{c["feature_ru"]} ({c["contribution_pct"]}%)'
                    for c in contribs
                )
                parts.append(f'Ключевые факторы AI: {contrib_text}.')

        # DB history context
        if db_history and db_history.get('total_past_apps', 0) > 0:
            hist_total = db_history['total_past_apps']
            hist_success = db_history['success_count']
            hist_rate = db_history['success_rate']
            hist_avg = db_history.get('avg_past_score')
            hist_text = f'История в БД: {hist_total} заявок, {hist_success} успешных ({hist_rate:.0%})'
            if hist_avg:
                hist_text += f', средний балл {hist_avg:.1f}'
            parts.append(f'[{hist_text}]')

        if recommendation == 'approve':
            parts.append(
                f'Высокий балл ({total_score:.1f}/100) — рекомендовано к одобрению.'
            )
            if strengths:
                strong_names = ', '.join(f['factor_name'].lower() for f in strengths[:3])
                parts.append(f'Сильные стороны: {strong_names}.')
            parts.append(
                f'Заявитель: {application.applicant.name}, '
                f'{application.region}, '
                f'{application.subsidy_type.direction.name}.'
            )

        elif recommendation == 'review':
            parts.append(
                f'Средний балл ({total_score:.1f}/100) — требует внимания комиссии.'
            )
            if weaknesses:
                weak_names = ', '.join(f['factor_name'].lower() for f in weaknesses[:3])
                parts.append(f'Требуют внимания: {weak_names}.')
            if strengths:
                strong_names = ', '.join(f['factor_name'].lower() for f in strengths[:2])
                parts.append(f'Положительные факторы: {strong_names}.')

        else:  # reject
            parts.append(
                f'Низкий балл ({total_score:.1f}/100) — высокий риск, рекомендован отказ.'
            )
            if weaknesses:
                for w in weaknesses[:3]:
                    parts.append(f'— {w["factor_name"]}: {w["explanation"]}')

        return ' '.join(parts)

    def _check_budget(self, application: Application) -> bool:
        """
        Проверяет доступность бюджета для заявки.
        Возвращает True если бюджет достаточен.
        """
        from django.utils import timezone
        try:
            budget = Budget.objects.get(
                year=timezone.now().year,
                region=application.region,
                direction=application.subsidy_type.direction,
            )
            return budget.remaining_amount >= application.total_amount
        except Budget.DoesNotExist:
            return True  # Нет бюджета = пропускаем проверку

    def _create_notification(self, application, total_score, recommendation, budget_available):
        """Создаёт уведомление для заявителя о результатах скоринга."""
        from apps.scoring.models import UserProfile
        target_user = self._find_applicant_user(application)
        if not target_user:
            return

        rec_labels = {'approve': 'ОДОБРИТЬ', 'review': 'НА РАССМОТРЕНИЕ', 'reject': 'ОТКЛОНИТЬ', 'info': 'ИНФОРМИРОВАНИЕ'}
        rec_label = rec_labels.get(recommendation, recommendation)

        if recommendation == 'approve' and budget_available:
            ntype = 'approved'
            title = f'Заявка {application.number} — рекомендована к одобрению'
            message = (
                f'Ваша заявка набрала {total_score:.1f} баллов из 100. '
                f'Рекомендация AI: {rec_label}. '
                f'Бюджет доступен — заявка передана на рассмотрение комиссии.'
            )
        elif recommendation == 'approve' and not budget_available:
            ntype = 'waiting_list'
            title = f'Заявка {application.number} — лист ожидания'
            message = (
                f'Ваша заявка набрала {total_score:.1f} баллов из 100. '
                f'Рекомендация AI: {rec_label}. '
                f'Бюджет по направлению в регионе исчерпан — заявка помещена в лист ожидания.'
            )
        elif recommendation == 'reject':
            ntype = 'rejected'
            title = f'Заявка {application.number} — рекомендован отказ'
            message = (
                f'Ваша заявка набрала {total_score:.1f} баллов из 100. '
                f'Рекомендация AI: {rec_label}. '
                f'Рекомендуем устранить замечания и подать заявку повторно.'
            )
        else:
            ntype = 'scored'
            title = f'Заявка {application.number} — скоринг завершён'
            message = (
                f'Ваша заявка набрала {total_score:.1f} баллов из 100. '
                f'Рекомендация AI: {rec_label}. '
                f'Заявка передана на рассмотрение комиссии.'
            )

        Notification.objects.create(
            user=target_user,
            application=application,
            notification_type=ntype,
            title=title,
            message=message,
        )

    def _check_subsidy_obligations(self, application: Application, entity):
        """
        Проверка встречных обязательств по Приказу №108.

        Если заявитель получил >100 млн тенге субсидий и имеет снижение
        валовой продукции 2 года подряд — блокировка:
          - 1 год при первом нарушении
          - 2 года при повторном нарушении
        """
        applicant = application.applicant

        # Уже заблокирован — пропускаем
        if applicant.is_blocked and applicant.block_until and applicant.block_until > date.today():
            return

        giss = entity.giss_data or {}
        total_subsidies = giss.get('total_subsidies_received', 0)

        # Порог: более 100 млн тенге
        if total_subsidies <= 100_000_000:
            return

        # Проверяем снижение валовой продукции 2 года подряд
        prod_prev = giss.get('gross_production_previous_year', 0)
        prod_before = giss.get('gross_production_year_before', 0)
        growth_rate = giss.get('growth_rate', 0)

        # Снижение = отрицательный рост И текущий год ниже предыдущего
        if growth_rate >= 0 or prod_prev >= prod_before:
            return

        # Обязательства не выполнены 2 года подряд (declining production)
        obligations_met = giss.get('obligations_met', True)
        if obligations_met:
            return

        # Определяем срок блокировки: повторное нарушение = 2 года, первое = 1 год
        had_previous_block = bool(applicant.block_reason)
        if had_previous_block:
            block_years = 2
            reason = (
                'Повторное невыполнение встречных обязательств по субсидиям '
                '(снижение валовой продукции 2 года подряд). '
                f'Блокировка на 2 года согласно Приказу №108.'
            )
        else:
            block_years = 1
            reason = (
                'Невыполнение встречных обязательств по субсидиям '
                '(снижение валовой продукции 2 года подряд). '
                f'Блокировка на 1 год согласно Приказу №108.'
            )

        applicant.is_blocked = True
        applicant.block_reason = reason
        applicant.block_until = date.today() + timedelta(days=365 * block_years)
        applicant.save(update_fields=['is_blocked', 'block_reason', 'block_until'])

        logger.warning(
            'Заявитель %s заблокирован на %d год(а): %s',
            applicant.iin_bin, block_years, reason,
        )

        # Уведомление
        target_user = self._find_applicant_user(application)
        if target_user:
            Notification.objects.create(
                user=target_user,
                application=application,
                notification_type='rejected',
                title=f'Блокировка заявителя {applicant.name}',
                message=reason,
            )


def calculate_merit_score(application):
    """
    Рассчитывает Merit Score для приоритизации выплат.

    Merit Score = 30% × масштаб хозяйства + 25% × финансовая эффективность
                + 25% × история субсидий + 20% × приоритет направления

    Данные берутся из уже рассчитанных ScoreFactor при скоринге заявки.
    """
    from apps.scoring.models import ScoreFactor, Score

    breakdown = {
        'farm_scale': 0,
        'financial': 0,
        'history': 0,
        'direction_priority': 0,
    }

    try:
        score = application.score
    except Score.DoesNotExist:
        return 0, breakdown

    factors = {f.factor_code: f for f in ScoreFactor.objects.filter(score=score)}

    # 1. Масштаб хозяйства (30%) — из factor "farm_size"
    farm = factors.get('farm_size')
    if farm:
        breakdown['farm_scale'] = round(float(farm.value) / float(farm.max_value) * 100, 1)
    else:
        breakdown['farm_scale'] = 50  # нейтральный

    # 2. Финансовая эффективность (25%) — из factor "financial_stability"
    fin = factors.get('financial_stability')
    if fin:
        breakdown['financial'] = round(float(fin.value) / float(fin.max_value) * 100, 1)
    else:
        breakdown['financial'] = 50

    # 3. История субсидий (25%) — из factor "subsidy_history"
    hist = factors.get('subsidy_history')
    if hist:
        breakdown['history'] = round(float(hist.value) / float(hist.max_value) * 100, 1)
    else:
        breakdown['history'] = 50

    # 4. Приоритет направления (20%) — по коду направления
    direction_priorities = {
        'breeding': 90,        # Племенное — высший приоритет
        'feed_production': 80, # Кормопроизводство
        'livestock': 75,       # Животноводство
        'veterinary': 70,      # Ветеринария
        'crop': 60,            # Растениеводство
    }
    direction_code = application.subsidy_type.direction.code if application.subsidy_type else ''
    breakdown['direction_priority'] = direction_priorities.get(direction_code, 50)

    # Итоговый Merit Score
    merit = (
        breakdown['farm_scale'] * 0.30
        + breakdown['financial'] * 0.25
        + breakdown['history'] * 0.25
        + breakdown['direction_priority'] * 0.20
    )

    return round(merit, 2), breakdown
