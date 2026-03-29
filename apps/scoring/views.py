import json
from functools import wraps

from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Avg, Count, Sum, Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
    Application, Applicant, SubsidyDirection, SubsidyType,
    Score, ScoreFactor, HardFilterResult, Decision, Budget, UserProfile,
    Notification, Payment,
)


def _get_role(user):
    """Получить роль пользователя."""
    try:
        return user.profile.role
    except (UserProfile.DoesNotExist, AttributeError):
        return 'applicant'


def role_required(*allowed_roles):
    """Декоратор: доступ только для указанных ролей."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            role = _get_role(request.user)
            if role not in allowed_roles:
                return render(request, 'scoring/access_denied.html', {
                    'required_roles': allowed_roles,
                    'user_role': role,
                }, status=403)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def home(request):
    return render(request, 'index.html')


@login_required
def dashboard(request):
    role = _get_role(request.user)
    all_apps = Application.objects.select_related('applicant', 'subsidy_type__direction', 'score')

    # Заявитель видит только свои данные
    if role == 'applicant':
        iin_bin = getattr(request.user.profile, 'iin_bin', '')
        if iin_bin:
            apps = all_apps.filter(applicant__iin_bin=iin_bin)
        else:
            apps = all_apps.none()
    else:
        apps = all_apps

    total = apps.count()
    pending = apps.filter(status__in=['submitted', 'checking']).count()
    approved = apps.filter(status__in=['approved', 'paid', 'partially_paid']).count()
    rejected = apps.filter(status='rejected').count()

    if role == 'applicant':
        avg_score_qs = Score.objects.filter(application__in=apps)
    else:
        avg_score_qs = Score.objects.all()
    avg_score = avg_score_qs.aggregate(avg=Avg('total_score'))['avg'] or 0

    budgets = Budget.objects.all()
    budget_total = budgets.aggregate(s=Sum('planned_amount'))['s'] or 0
    budget_spent = budgets.aggregate(s=Sum('spent_amount'))['s'] or 0
    budget_pct = round(budget_spent / budget_total * 100, 1) if budget_total > 0 else 0

    def display_amount(val):
        if val >= 1_000_000_000:
            return f'{val / 1_000_000_000:.1f} млрд'
        if val >= 1_000_000:
            return f'{val / 1_000_000:.0f} млн'
        return f'{val:,.0f}'

    # Score distribution (для служебных ролей — все, для заявителя — свои)
    score_ranges = ['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90-100']
    score_values = []
    for i in range(10):
        low = i * 10
        high = (i + 1) * 10 if i < 9 else 101
        count = avg_score_qs.filter(total_score__gte=low, total_score__lt=high).count()
        score_values.append(count)

    score_distribution = json.dumps({
        'labels': score_ranges,
        'values': score_values,
    })

    # Direction distribution
    dir_data = (
        apps
        .values('subsidy_type__direction__name')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')[:7]
    )
    direction_distribution = json.dumps({
        'labels': [d['subsidy_type__direction__name'] or 'Не указано' for d in dir_data],
        'values': [d['cnt'] for d in dir_data],
    })

    regions = apps.values_list('region', flat=True).distinct().order_by('region')

    recent = apps.order_by('-submitted_at')[:20]

    stats = {
        'total': total,
        'pending': pending,
        'approved': approved,
        'approved_pct': round(approved / total * 100, 1) if total > 0 else 0,
        'avg_score': round(avg_score, 1),
        'budget_pct': budget_pct,
        'budget_spent_display': display_amount(budget_spent),
        'budget_total_display': display_amount(budget_total),
        'year': timezone.now().year,
    }

    # Applicant history summary (only for applicant role)
    applicant_history_summary = None
    if role == 'applicant' and apps.exists():
        successful_statuses = ['approved', 'paid', 'partially_paid']
        hist_total = apps.count()
        hist_success = apps.filter(status__in=successful_statuses).count()
        hist_amount = (
            apps.filter(status__in=['paid', 'partially_paid'])
            .aggregate(s=Sum('total_amount'))['s'] or 0
        )
        # Applications by year
        from django.db.models.functions import ExtractYear
        by_year = list(
            apps.filter(submitted_at__isnull=False)
            .annotate(year=ExtractYear('submitted_at'))
            .values('year')
            .annotate(cnt=Count('id'), amt=Sum('total_amount'))
            .order_by('year')
        )
        applicant_history_summary = {
            'total_apps': hist_total,
            'success_rate': round(hist_success / hist_total * 100, 1) if hist_total > 0 else 0,
            'total_amount': hist_amount,
            'by_year': by_year,
            'by_year_json': json.dumps({
                'labels': [str(y['year']) for y in by_year],
                'values': [y['cnt'] for y in by_year],
            }),
        }

    return render(request, 'scoring/dashboard.html', {
        'stats': stats,
        'recent_applications': recent,
        'regions': regions,
        'score_distribution': score_distribution,
        'direction_distribution': direction_distribution,
        'user_role': role,
        'applicant_history_summary': applicant_history_summary,
    })


@role_required('applicant', 'mio_specialist', 'mio_head', 'admin')
def application_list(request):
    apps = Application.objects.select_related('applicant', 'subsidy_type__direction', 'score')

    # Заявители видят только свои заявки
    role = _get_role(request.user)
    if role == 'applicant':
        profile = request.user.profile
        if profile.iin_bin:
            apps = apps.filter(applicant__iin_bin=profile.iin_bin)
        else:
            apps = apps.none()

    search = request.GET.get('search', '')
    if search:
        apps = apps.filter(
            Q(number__icontains=search) |
            Q(applicant__iin_bin__icontains=search) |
            Q(applicant__name__icontains=search)
        )

    status = request.GET.get('status', '')
    if status:
        apps = apps.filter(status=status)

    region = request.GET.get('region', '')
    if region:
        apps = apps.filter(region=region)

    ordering = request.GET.get('ordering', '-submitted_at')
    if ordering:
        apps = apps.order_by(ordering)

    paginator = Paginator(apps, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Build query string without page
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    regions = Application.objects.values_list('region', flat=True).distinct().order_by('region')
    offset = (page_obj.number - 1) * 20

    return render(request, 'scoring/application_list.html', {
        'applications': page_obj,
        'page_obj': page_obj,
        'total_count': paginator.count,
        'offset': offset,
        'query_string': query_string,
        'regions': regions,
        'status_choices': Application.STATUS_CHOICES,
    })


@role_required('applicant', 'mio_specialist', 'mio_head', 'admin')
def application_create(request):
    directions = SubsidyDirection.objects.filter(is_active=True)
    subsidy_types = SubsidyType.objects.filter(is_active=True).select_related('direction')

    if request.method == 'POST':
        stype_id = request.POST.get('subsidy_type')
        try:
            quantity = int(request.POST.get('quantity', 1) or 1)
        except (ValueError, TypeError):
            quantity = 1
        region = request.POST.get('region', '')
        district = request.POST.get('district', '')
        iin_bin = request.POST.get('iin_bin', '')
        name = request.POST.get('name', '')
        entity_type = request.POST.get('entity_type', 'legal')
        esf_number = request.POST.get('esf_number', '')
        phone = request.POST.get('phone', '')
        bank_account = request.POST.get('bank_account', '')
        ecp_signed = request.POST.get('ecp_signed') == 'true'

        # JSON-данные выбранных элементов
        selected_animals_json = request.POST.get('selected_animals', '[]')
        selected_plots_json = request.POST.get('selected_plots', '[]')
        selected_invoices_json = request.POST.get('selected_invoices', '[]')

        try:
            selected_animals = json.loads(selected_animals_json) if selected_animals_json else []
        except (json.JSONDecodeError, TypeError):
            selected_animals = []
        try:
            selected_plots = json.loads(selected_plots_json) if selected_plots_json else []
        except (json.JSONDecodeError, TypeError):
            selected_plots = []
        try:
            selected_invoices = json.loads(selected_invoices_json) if selected_invoices_json else []
        except (json.JSONDecodeError, TypeError):
            selected_invoices = []

        if not stype_id:
            messages.error(request, 'Выберите вид субсидии')
            return redirect('/applications/new/')
        try:
            stype = SubsidyType.objects.get(id=stype_id)
        except SubsidyType.DoesNotExist:
            messages.error(request, 'Вид субсидии не найден')
            return redirect('/applications/new/')

        applicant, created = Applicant.objects.get_or_create(
            iin_bin=iin_bin,
            defaults={
                'name': name,
                'entity_type': entity_type,
                'region': region,
                'district': district,
                'registration_date': timezone.now().date(),
            },
        )
        # Обновляем телефон и банк если переданы
        updated_fields = []
        if phone and phone != applicant.phone:
            applicant.phone = phone
            updated_fields.append('phone')
        if bank_account and bank_account != applicant.bank_account:
            applicant.bank_account = bank_account
            updated_fields.append('bank_account')
        if not created and name and name != applicant.name:
            applicant.name = name
            updated_fields.append('name')
        if updated_fields:
            applicant.save(update_fields=updated_fields)

        # Вычисляем сумму выбранных ЭСФ
        esf_total = sum(inv.get('amount', 0) for inv in selected_invoices)

        import random
        for _ in range(5):
            number = f'{random.randint(10,99)}{random.randint(100,999)}{random.randint(100,999)}{random.randint(100000,999999)}'
            if not Application.objects.filter(number=number).exists():
                break

        app = Application.objects.create(
            number=number,
            applicant=applicant,
            subsidy_type=stype,
            status='submitted',
            quantity=quantity,
            unit_price=float(stype.rate),
            rate=stype.rate,
            total_amount=quantity * stype.rate,
            submitted_at=timezone.now(),
            region=region,
            district=district,
            akimat=f'ГУ "Управление сельского хозяйства {region}"',
            esf_number=esf_number,
            esf_amount=esf_total if esf_total > 0 else None,
            animals_data=selected_animals,
            plots_data=selected_plots,
            invoices_data=selected_invoices,
            bank_account=bank_account,
            ecp_signed=ecp_signed,
            ecp_signed_at=timezone.now() if ecp_signed else None,
        )

        # Загрузка документов
        from .models import ApplicationDocument
        doc_mapping = {
            'doc_purchase_agreement': 'contract',
            'doc_payment_confirmation': 'payment_confirmation',
            'doc_additional': 'other',
        }
        for field_name, doc_type in doc_mapping.items():
            files = request.FILES.getlist(field_name)
            for f in files:
                ApplicationDocument.objects.create(
                    application=app,
                    doc_type=doc_type,
                    name=f.name,
                    file=f,
                )

        # Run scoring
        try:
            from apps.scoring.scoring_engine import ScoringEngine
            ScoringEngine().run_scoring(app)
        except Exception:
            pass

        messages.success(request, f'Заявка {app.number} создана и оценена')
        return redirect(f'/applications/{app.id}/')

    regions = Application.objects.values_list('region', flat=True).distinct().order_by('region')

    # Если заявитель — передаём его ИИН/БИН для автозаполнения
    profile_iin = ''
    profile_name = ''
    role = _get_role(request.user)
    if role == 'applicant':
        try:
            profile_iin = request.user.profile.iin_bin or ''
            profile_name = request.user.profile.organization or request.user.get_full_name()
        except Exception:
            pass

    return render(request, 'scoring/application_form.html', {
        'directions': directions,
        'subsidy_types': subsidy_types,
        'regions': regions,
        'profile_iin': profile_iin,
        'profile_name': profile_name,
    })


@role_required('applicant', 'mio_specialist', 'mio_head', 'commission_member', 'admin')
def application_detail(request, pk):
    app = get_object_or_404(
        Application.objects.select_related('applicant', 'subsidy_type__direction'),
        pk=pk,
    )

    try:
        score = app.score
    except Score.DoesNotExist:
        score = None
    factors = ScoreFactor.objects.filter(score=score).order_by('-weighted_value') if score else []
    hard_filters = HardFilterResult.objects.filter(application=app).first()
    documents = app.documents.all()
    decisions = app.decisions.select_related('decided_by').all()

    # Hard filter items for display
    filter_items = []
    if hard_filters:
        filter_items = [
            ('Регистрация в ГИСС', hard_filters.giss_registered),
            ('Наличие ЭЦП', hard_filters.has_eds),
            ('Учётный номер ИАС РСЖ', hard_filters.ias_rszh_registered),
            ('Земельный участок ЕГКН', hard_filters.has_agricultural_land),
            ('Регистрация в ИС ИСЖ', hard_filters.is_iszh_registered),
            ('Регистрация в ИБСПР', hard_filters.ibspr_registered),
            ('ЭСФ подтверждена', hard_filters.esf_confirmed),
            ('Нет невыполненных обязательств', hard_filters.no_unfulfilled_obligations),
            ('Нет блокировки', hard_filters.no_block),
            ('Возраст животных', hard_filters.animals_age_valid),
            ('Не субсидировались ранее', hard_filters.animals_not_subsidized),
        ]

    # External data from emulator
    external_data = {}
    if hard_filters and hard_filters.raw_responses:
        system_names = {
            'giss': 'ГИСС — встречные обязательства',
            'ias_rszh': 'ИАС РСЖ — регистрация, история',
            'easu': 'ЕАСУ — учётные номера',
            'is_iszh': 'ИС ИСЖ — идентификация животных',
            'is_esf': 'ИС ЭСФ — счета-фактуры',
            'egkn': 'ЕГКН — земельный кадастр',
            'treasury': 'Казначейство — платежи',
        }
        for key, name in system_names.items():
            if key in hard_filters.raw_responses:
                external_data[name] = json.dumps(hard_filters.raw_responses[key], ensure_ascii=False, indent=2)

    role = _get_role(request.user)
    can_decide = role in ('commission_member', 'mio_head', 'admin')
    can_pay = role in ('mio_specialist', 'mio_head', 'admin')

    # Payment info
    payment = Payment.objects.filter(application=app).first()

    # Budget info
    budget_info = None
    try:
        budget = Budget.objects.get(
            year=timezone.now().year,
            region=app.region,
            direction=app.subsidy_type.direction,
        )
        budget_info = {
            'planned': budget.planned_amount,
            'spent': budget.spent_amount,
            'remaining': budget.remaining_amount,
            'pct': round(float(budget.spent_amount) / float(budget.planned_amount) * 100, 1) if budget.planned_amount else 0,
            'enough': budget.remaining_amount >= app.total_amount,
        }
    except Budget.DoesNotExist:
        pass

    # Applicant history — all other applications by this applicant
    applicant_history = (
        Application.objects
        .filter(applicant=app.applicant)
        .exclude(id=app.id)
        .select_related('subsidy_type__direction', 'score')
        .order_by('-submitted_at')
    )

    # History summary
    history_summary = {}
    total_hist = applicant_history.count()
    if total_hist > 0:
        successful_statuses = ['approved', 'paid', 'partially_paid']
        success_count = applicant_history.filter(status__in=successful_statuses).count()
        total_amount_received = (
            applicant_history
            .filter(status__in=['paid', 'partially_paid'])
            .aggregate(s=Sum('total_amount'))['s'] or 0
        )
        avg_hist_score = (
            Score.objects
            .filter(application__in=applicant_history)
            .aggregate(avg=Avg('total_score'))['avg']
        )
        # Trend: compare scores of last 2 applications
        recent_scores = list(
            Score.objects
            .filter(application__in=applicant_history)
            .order_by('-application__submitted_at')
            .values_list('total_score', flat=True)[:3]
        )
        if len(recent_scores) >= 2:
            if recent_scores[0] > recent_scores[-1]:
                trend = 'growing'
            elif recent_scores[0] < recent_scores[-1]:
                trend = 'declining'
            else:
                trend = 'stable'
        else:
            trend = 'stable'

        history_summary = {
            'total_apps': total_hist,
            'total_amount': total_amount_received,
            'success_rate': round(success_count / total_hist * 100, 1) if total_hist > 0 else 0,
            'avg_score': round(float(avg_hist_score), 1) if avg_hist_score else None,
            'trend': trend,
        }

    # SHAP explanation data
    shap_data = None
    if score and score.explanation and score.explanation.get('shap_values'):
        shap_items = score.explanation['shap_values'][:10]  # Top 10 factors
        max_abs = max((abs(item['shap_value']) for item in shap_items), default=1) or 1
        for item in shap_items:
            item['bar_pct'] = round(abs(item['shap_value']) / max_abs * 100, 1)
            item['direction'] = 'positive' if item['shap_value'] >= 0 else 'negative'
        shap_data = {
            'items': shap_items,
            'base_value': score.explanation.get('base_value', 0),
        }

    return render(request, 'scoring/application_detail.html', {
        'app': app,
        'score': score,
        'factors': factors,
        'hard_filters': hard_filters,
        'filter_items': filter_items,
        'documents': documents,
        'decisions': decisions,
        'external_data': external_data,
        'can_decide': can_decide,
        'can_pay': can_pay,
        'payment': payment,
        'budget_info': budget_info,
        'applicant_history': applicant_history,
        'history_summary': history_summary,
        'shap_data': shap_data,
    })


@role_required('commission_member', 'mio_head', 'admin')
def application_decide(request, pk):
    if request.method != 'POST':
        return redirect('application_detail', pk=pk)

    app = get_object_or_404(Application, pk=pk)
    decision_val = request.POST.get('decision')
    reason = request.POST.get('reason', '')

    if not decision_val or not reason:
        messages.error(request, 'Заполните все поля')
        return redirect(f'/applications/{pk}/')

    Decision.objects.create(
        application=app,
        decision=decision_val,
        decided_by=request.user,
        reason=reason,
    )

    status_map = {
        'approved': 'approved',
        'rejected': 'rejected',
        'partially_approved': 'approved',
        'review': 'checking',
    }
    app.status = status_map.get(decision_val, app.status)
    app.save()

    # Платёжный flow: при одобрении создаём платёж
    if decision_val in ('approved', 'partially_approved'):
        import random
        Payment.objects.get_or_create(
            application=app,
            defaults={
                'amount': app.total_amount,
                'status': 'initiated',
                'treasury_ref': f'TR-{timezone.now().year}-{random.randint(100000, 999999)}',
                'initiated_by': request.user,
            },
        )

    # Уведомление заявителю
    decision_labels = {
        'approved': ('approved', 'Заявка одобрена', f'Комиссия одобрила вашу заявку {app.number}. Сумма {app.total_amount} ₸ направлена на формирование платежа.'),
        'rejected': ('rejected', 'Заявка отклонена', f'Комиссия отклонила заявку {app.number}. Причина: {reason}'),
        'review': ('review', 'Доп. проверка', f'По заявке {app.number} назначена дополнительная проверка. Причина: {reason}'),
        'partially_approved': ('approved', 'Частично одобрена', f'Заявка {app.number} частично одобрена комиссией.'),
    }
    if decision_val in decision_labels:
        ntype, title, msg = decision_labels[decision_val]
        # Находим пользователя-заявителя по ИИН/БИН
        target_profile = UserProfile.objects.filter(
            iin_bin=app.applicant.iin_bin, role='applicant'
        ).select_related('user').first()
        if target_profile:
            Notification.objects.create(
                user=target_profile.user,
                application=app,
                notification_type=ntype,
                title=title,
                message=msg,
            )

    messages.success(request, f'Решение "{dict(Decision.DECISION_CHOICES).get(decision_val)}" сохранено')
    return redirect(f'/applications/{pk}/')


@role_required('mio_specialist', 'commission_member', 'mio_head', 'auditor', 'admin')
def scoring_ranking(request):
    scores = (
        Score.objects
        .select_related('application__applicant', 'application__subsidy_type__direction')
        .order_by('-total_score')
    )

    region = request.GET.get('region', '')
    if region:
        scores = scores.filter(application__region=region)

    direction = request.GET.get('direction', '')
    if direction:
        scores = scores.filter(application__subsidy_type__direction__code=direction)

    # Calculate cumulative amounts
    ranking_data = []
    cumulative = 0
    for i, s in enumerate(scores[:200], 1):
        cumulative += float(s.application.total_amount)
        ranking_data.append({
            'rank': i,
            'score': s,
            'app': s.application,
            'cumulative': cumulative,
        })

    budget = Budget.objects.filter(region=region).aggregate(s=Sum('planned_amount'))['s'] if region else \
        Budget.objects.aggregate(s=Sum('planned_amount'))['s']
    budget = float(budget or 0)

    regions = Application.objects.values_list('region', flat=True).distinct().order_by('region')
    directions = SubsidyDirection.objects.filter(is_active=True)

    return render(request, 'scoring/scoring_ranking.html', {
        'ranking_data': ranking_data,
        'budget': budget,
        'regions': regions,
        'directions': directions,
    })


@role_required('mio_specialist', 'commission_member', 'mio_head', 'auditor', 'admin')
def analytics(request):
    apps = Application.objects.all()
    scores = Score.objects.all()

    # Stats
    total = apps.count()
    by_status = {}
    for val, label in Application.STATUS_CHOICES:
        by_status[label] = apps.filter(status=val).count()

    # By region
    by_region = (
        apps.values('region')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('-count')
    )
    region_chart = json.dumps({
        'labels': [r['region'][:20] for r in by_region],
        'values': [r['count'] for r in by_region],
    })

    # Score distribution
    score_ranges = ['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90-100']
    score_values = []
    for i in range(10):
        low = i * 10
        high = (i + 1) * 10 if i < 9 else 101
        score_values.append(scores.filter(total_score__gte=low, total_score__lt=high).count())

    score_chart = json.dumps({'labels': score_ranges, 'values': score_values})

    avg_score = scores.aggregate(avg=Avg('total_score'))['avg'] or 0

    return render(request, 'scoring/analytics.html', {
        'total': total,
        'by_status': by_status,
        'avg_score': round(avg_score, 1),
        'by_region': by_region,
        'region_chart': region_chart,
        'score_chart': score_chart,
    })


@role_required('commission_member', 'mio_head', 'admin')
def commission(request):
    scores = (
        Score.objects
        .select_related('application__applicant', 'application__subsidy_type__direction')
        .filter(application__status__in=['approved', 'waiting_list', 'submitted'])
        .order_by('-total_score')
    )

    ranking_data = []
    cumulative = 0
    for i, s in enumerate(scores[:100], 1):
        cumulative += float(s.application.total_amount)
        ranking_data.append({
            'rank': i,
            'score': s,
            'app': s.application,
            'cumulative': cumulative,
        })

    budget = float(Budget.objects.aggregate(s=Sum('planned_amount'))['s'] or 0)

    return render(request, 'scoring/commission.html', {
        'ranking_data': ranking_data,
        'budget': budget,
        'total_in_queue': scores.count(),
    })


@role_required('admin')
def emulator_panel(request):
    from apps.emulator.models import EmulatedEntity
    entities = EmulatedEntity.objects.all()

    stats = {
        'total': entities.count(),
        'clean': entities.filter(risk_profile='clean').count(),
        'minor': entities.filter(risk_profile='minor_issues').count(),
        'risky': entities.filter(risk_profile='risky').count(),
        'fraudulent': entities.filter(risk_profile='fraudulent').count(),
    }

    search = request.GET.get('search', '')
    if search:
        entities = entities.filter(
            Q(iin_bin__icontains=search) | Q(name__icontains=search)
        )

    risk = request.GET.get('risk', '')
    if risk:
        entities = entities.filter(risk_profile=risk)

    paginator = Paginator(entities, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'emulator/panel.html', {
        'entities': page_obj,
        'page_obj': page_obj,
        'stats': stats,
    })


def login_view(request):
    if request.method == 'POST':
        from django.contrib.auth import authenticate, login

        login_mode = request.POST.get('login_mode', 'password')

        if login_mode == 'ecp':
            # ── Вход через ЭЦП ──
            iin_bin = request.POST.get('iin_bin', '').strip()
            if not iin_bin or len(iin_bin) != 12 or not iin_bin.isdigit():
                messages.error(request, 'Введите корректный ИИН/БИН (12 цифр)')
                return render(request, 'auth/login.html')

            from apps.emulator.models import EmulatedEntity
            try:
                entity = EmulatedEntity.objects.get(iin_bin=iin_bin)
            except EmulatedEntity.DoesNotExist:
                messages.error(request, f'Субъект с ИИН/БИН {iin_bin} не найден в государственных системах')
                return render(request, 'auth/login.html')

            # Проверяем наличие ЭЦП через ЕАСУ
            easu = entity.easu_data or {}
            if not easu.get('has_account_number', False):
                messages.error(request, 'У данного субъекта не зарегистрирована ЭЦП в системе ЕАСУ')
                return render(request, 'auth/login.html')

            # Находим или создаём пользователя
            from django.contrib.auth.models import User
            profile = UserProfile.objects.filter(iin_bin=iin_bin).select_related('user').first()
            if profile:
                user = profile.user
            else:
                # Создаём нового пользователя
                username = f'ecp_{iin_bin}'
                user = User.objects.create_user(
                    username=username,
                    password=None,  # без пароля — вход только через ЭЦП
                    first_name=entity.name[:30],
                )
                user.set_unusable_password()
                user.save()

                # Создаём профиль с данными из госсистем
                giss = entity.giss_data or {}
                UserProfile.objects.create(
                    user=user,
                    role='applicant',
                    iin_bin=iin_bin,
                    region=entity.region,
                    district=entity.district,
                    organization=entity.name,
                    phone=giss.get('phone', ''),
                )

                # Создаём / обновляем запись заявителя
                from .models import Applicant
                Applicant.objects.get_or_create(
                    iin_bin=iin_bin,
                    defaults={
                        'name': entity.name,
                        'entity_type': entity.entity_type,
                        'region': entity.region,
                        'district': entity.district,
                        'registration_date': timezone.now().date(),
                    },
                )

            login(request, user)
            return redirect('/dashboard/')

        else:
            # ── Обычный вход (для служебных ролей / демо) ──
            username = request.POST.get('username')
            password = request.POST.get('password')
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                return redirect('/dashboard/')
            messages.error(request, 'Неверные данные')

    return render(request, 'auth/login.html')


@role_required('applicant', 'mio_specialist', 'mio_head', 'admin')
def application_save_draft(request):
    if request.method != 'POST':
        return redirect('/applications/new/')

    import json as _json
    from django.http import JsonResponse

    try:
        data = _json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    stype_id = data.get('subsidy_type')
    iin_bin = data.get('iin_bin', '')
    name = data.get('name', '')
    entity_type = data.get('entity_type', 'legal')
    region = data.get('region', '')
    district = data.get('district', '')
    try:
        quantity = int(data.get('quantity', 1) or 1)
    except (ValueError, TypeError):
        quantity = 1
    esf_number = data.get('esf_number', '')

    if not iin_bin:
        return JsonResponse({'ok': False, 'error': 'ИИН/БИН обязателен'}, status=400)

    applicant, _ = Applicant.objects.get_or_create(
        iin_bin=iin_bin,
        defaults={
            'name': name,
            'entity_type': entity_type,
            'region': region,
            'district': district,
            'registration_date': timezone.now().date(),
        },
    )

    stype = SubsidyType.objects.filter(id=stype_id).first() if stype_id else None
    if not stype:
        return JsonResponse({'ok': False, 'error': 'Выберите вид субсидии'}, status=400)

    import random
    for _ in range(5):
        number = f'DR-{random.randint(10,99)}{random.randint(100,999)}{random.randint(1000,9999)}'
        if not Application.objects.filter(number=number).exists():
            break

    app = Application.objects.create(
        number=number,
        applicant=applicant,
        subsidy_type=stype,
        status='draft',
        quantity=quantity,
        unit_price=float(stype.rate),
        rate=stype.rate,
        total_amount=quantity * stype.rate,
        submitted_at=None,
        region=region,
        district=district,
        akimat=f'ГУ "Управление сельского хозяйства {region}"' if region else '',
        esf_number=esf_number,
    )

    return JsonResponse({'ok': True, 'id': app.id, 'number': app.number})


@login_required
def notifications_view(request):
    notifs = Notification.objects.filter(user=request.user)
    unread = notifs.filter(is_read=False).count()
    return render(request, 'scoring/notifications.html', {
        'notifications': notifs[:50],
        'unread_count': unread,
    })


@login_required
def notification_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, user=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    if notif.application:
        return redirect(f'/applications/{notif.application.id}/')
    return redirect('/notifications/')


@role_required('mio_specialist', 'mio_head', 'admin')
def payment_action(request, pk):
    """Продвигает платёж по flow: initiated → sent_to_treasury → completed."""
    if request.method != 'POST':
        return redirect(f'/applications/{pk}/')

    app = get_object_or_404(Application, pk=pk)
    payment = Payment.objects.filter(application=app).first()

    if not payment:
        messages.error(request, 'Платёж не найден')
        return redirect(f'/applications/{pk}/')

    action = request.POST.get('action')
    if action == 'send_to_treasury' and payment.status == 'initiated':
        payment.status = 'sent_to_treasury'
        payment.sent_at = timezone.now()
        payment.save()
        messages.success(request, f'Платёж отправлен в Казначейство (реф: {payment.treasury_ref})')
    elif action == 'complete' and payment.status == 'sent_to_treasury':
        payment.status = 'completed'
        payment.completed_at = timezone.now()
        payment.save()
        app.status = 'paid'
        app.save()
        messages.success(request, 'Выплата произведена!')
        # Уведомление владельцу заявки
        target_profile = UserProfile.objects.filter(
            iin_bin=app.applicant.iin_bin, role='applicant'
        ).select_related('user').first()
        if target_profile:
            Notification.objects.create(
                user=target_profile.user,
                application=app,
                notification_type='paid',
                title=f'Выплата по заявке {app.number}',
                message=f'На ваш счёт произведена выплата {app.total_amount} ₸ по заявке {app.number}.',
            )

    return redirect(f'/applications/{pk}/')


def logout_view(request):
    from django.contrib.auth import logout
    logout(request)
    return redirect('/')


@role_required('admin')
def entity_detail(request, pk):
    """Детальный просмотр данных эмулированной сущности."""
    from apps.emulator.models import EmulatedEntity
    entity = get_object_or_404(EmulatedEntity, pk=pk)

    # Подготовка данных для отображения на русском
    farm_indicators = _build_farm_indicators(entity)

    return render(request, 'emulator/entity_detail.html', {
        'entity': entity,
        'farm_indicators': farm_indicators,
    })


@role_required('admin')
def entity_edit(request, pk):
    """Редактирование данных эмулированной сущности (показатели хозяйства)."""
    from apps.emulator.models import EmulatedEntity
    entity = get_object_or_404(EmulatedEntity, pk=pk)

    if request.method == 'POST':
        # Обновляем основные данные
        entity.name = request.POST.get('name', entity.name)
        entity.entity_type = request.POST.get('entity_type', entity.entity_type)
        entity.region = request.POST.get('region', entity.region)
        entity.district = request.POST.get('district', entity.district)

        # ГИСС
        giss = entity.giss_data or {}
        giss['growth_rate'] = _float(request.POST.get('growth_rate'), giss.get('growth_rate', 0))
        giss['gross_production_previous_year'] = _int(request.POST.get('gross_production_prev'), giss.get('gross_production_previous_year', 0))
        giss['gross_production_year_before'] = _int(request.POST.get('gross_production_before'), giss.get('gross_production_year_before', 0))
        giss['obligations_met'] = request.POST.get('obligations_met') == 'on'
        giss['total_subsidies_received'] = _int(request.POST.get('total_subsidies_received'), giss.get('total_subsidies_received', 0))
        entity.giss_data = giss

        # ЕГКН
        egkn = entity.egkn_data or {}
        egkn['total_agricultural_area'] = _float(request.POST.get('total_agricultural_area'), egkn.get('total_agricultural_area', 0))
        egkn['has_agricultural_land'] = _float(request.POST.get('total_agricultural_area'), 0) > 0
        entity.egkn_data = egkn

        # ИС ИСЖ
        is_iszh = entity.is_iszh_data or {}
        is_iszh['total_verified'] = _int(request.POST.get('total_verified'), is_iszh.get('total_verified', 0))
        is_iszh['total_rejected'] = _int(request.POST.get('total_rejected'), is_iszh.get('total_rejected', 0))
        entity.is_iszh_data = is_iszh

        # ИАС РСЖ
        ias = entity.ias_rszh_data or {}
        ias['pending_returns'] = _int(request.POST.get('pending_returns'), ias.get('pending_returns', 0))
        entity.ias_rszh_data = ias

        # ИС ЭСФ
        is_esf = entity.is_esf_data or {}
        is_esf['total_amount'] = _int(request.POST.get('esf_total_amount'), is_esf.get('total_amount', 0))
        is_esf['invoice_count'] = _int(request.POST.get('esf_invoice_count'), is_esf.get('invoice_count', 0))
        entity.is_esf_data = is_esf

        entity.save()
        messages.success(request, f'Данные хозяйства «{entity.name}» обновлены')
        return redirect(f'/emulator/{entity.pk}/')

    farm_indicators = _build_farm_indicators(entity)

    return render(request, 'emulator/entity_edit.html', {
        'entity': entity,
        'farm_indicators': farm_indicators,
    })


@login_required
def api_entity_data(request, iin_bin):
    """API: возвращает данные сущности по ИИН/БИН для формы заявки."""
    from django.http import JsonResponse
    from apps.emulator.models import EmulatedEntity
    try:
        entity = EmulatedEntity.objects.get(iin_bin=iin_bin)
    except EmulatedEntity.DoesNotExist:
        return JsonResponse({'found': False})

    indicators = _build_farm_indicators(entity)

    # Flat values for form auto-fill
    giss = entity.giss_data or {}
    ias = entity.ias_rszh_data or {}
    is_iszh = entity.is_iszh_data or {}
    is_esf = entity.is_esf_data or {}
    egkn = entity.egkn_data or {}
    treasury = entity.treasury_data or {}
    subsidy_history = ias.get('subsidy_history', [])
    total_subs = len(subsidy_history)
    successful = sum(
        1 for h in subsidy_history
        if h.get('status') == 'executed' and h.get('obligations_met', False)
    )

    risk_labels = {
        'low': 'Низкий риск',
        'clean': 'Низкий риск',
        'medium': 'Средний риск',
        'high': 'Высокий риск',
    }
    systems_count = sum(1 for d in [
        entity.giss_data, entity.ias_rszh_data, entity.easu_data,
        entity.is_iszh_data, entity.is_esf_data, entity.egkn_data,
        entity.treasury_data,
    ] if d)

    return JsonResponse({
        'found': True,
        'entity_id': entity.pk,
        'entity_name': entity.name,
        'entity_type': entity.entity_type,
        'region': entity.region,
        'district': entity.district,
        'risk_label': risk_labels.get(entity.risk_profile, entity.risk_profile),
        'systems_count': systems_count,
        'indicators': indicators,
        'flat': {
            'gross_prod_prev': giss.get('gross_production_previous_year', 0),
            'gross_prod_before': giss.get('gross_production_year_before', 0),
            'growth_rate': giss.get('growth_rate', 0),
            'obligations_met': giss.get('obligations_met', True),
            'land_area': egkn.get('total_agricultural_area', 0),
            'land_plots': len(egkn.get('plots', [])),
            'verified_animals': is_iszh.get('total_verified', 0),
            'rejected_animals': is_iszh.get('total_rejected', 0),
            'subsidy_count': total_subs,
            'subsidy_success': successful,
            'pending_returns': ias.get('pending_returns', 0),
            'esf_total': is_esf.get('total_amount', 0),
            'esf_count': is_esf.get('invoice_count', 0),
            'total_subsidies_received': treasury.get('total_received', 0) or giss.get('total_subsidies_received', 0),
        },
        # Списки для выбора в форме
        'animals': [
            {
                'idx': i,
                'tag': a.get('tag_number', ''),
                'type': a.get('type', ''),
                'breed': a.get('breed', ''),
                'sex': a.get('sex', ''),
                'category': a.get('category', ''),
                'age_months': a.get('age_months', 0),
                'age_valid': a.get('age_valid', False),
                'vet_status': a.get('vet_status', ''),
                'previously_subsidized': a.get('previously_subsidized', False),
            }
            for i, a in enumerate(is_iszh.get('animals', []))
        ],
        'plots': [
            {
                'idx': i,
                'cadastral': p.get('cadastral_number', ''),
                'area': p.get('area_hectares', 0),
                'purpose': p.get('sub_purpose', p.get('purpose', '')),
                'ownership': p.get('ownership_type', ''),
                'district': p.get('district', ''),
            }
            for i, p in enumerate(egkn.get('plots', []))
        ],
        'invoices': [
            {
                'idx': i,
                'number': inv.get('esf_number', ''),
                'date': inv.get('date', ''),
                'amount': inv.get('total_amount', 0),
                'seller': inv.get('seller_name', ''),
                'confirmed': inv.get('payment_confirmed', False),
                'items_desc': ', '.join(it.get('description', '') for it in inv.get('items', [])),
            }
            for i, inv in enumerate(is_esf.get('invoices', []))
        ],
        'accounts': (entity.easu_data or {}).get('account_numbers', []),
        # Предварительные проверки (hard filters preview)
        'checks': {
            'giss_registered': giss.get('registered', False),
            'ias_registered': ias.get('registered', False),
            'has_eds': (entity.easu_data or {}).get('has_account_number', False),
            'has_land': egkn.get('has_agricultural_land', False),
            'not_blocked': not giss.get('blocked', False),
            'obligations_met': giss.get('obligations_met', True),
        },
    })


@role_required('mio_specialist', 'mio_head', 'admin')
def model_info_view(request):
    """Страница с информацией о ML модели."""
    from apps.scoring.ml_model import get_model_info
    info = get_model_info()
    return render(request, 'scoring/model_info.html', {'info': info})


def _build_farm_indicators(entity):
    """Собирает показатели хозяйства из JSON-полей в читаемый формат."""
    giss = entity.giss_data or {}
    ias = entity.ias_rszh_data or {}
    is_iszh = entity.is_iszh_data or {}
    is_esf = entity.is_esf_data or {}
    egkn = entity.egkn_data or {}
    treasury = entity.treasury_data or {}

    subsidy_history = ias.get('subsidy_history', [])
    total_subs = len(subsidy_history)
    successful = sum(
        1 for h in subsidy_history
        if h.get('status') == 'executed' and h.get('obligations_met', False)
    )

    animals = is_iszh.get('animals', [])

    return {
        'production': {
            'label': 'Производство',
            'items': [
                {'key': 'Валовая продукция (пред. год)', 'value': f'{giss.get("gross_production_previous_year", 0):,.0f} ₸', 'raw': giss.get('gross_production_previous_year', 0)},
                {'key': 'Валовая продукция (год ранее)', 'value': f'{giss.get("gross_production_year_before", 0):,.0f} ₸', 'raw': giss.get('gross_production_year_before', 0)},
                {'key': 'Темп роста продукции', 'value': f'{giss.get("growth_rate", 0):+.1f}%', 'raw': giss.get('growth_rate', 0)},
            ],
        },
        'land': {
            'label': 'Земельные ресурсы',
            'items': [
                {'key': 'Общая с/х площадь', 'value': f'{egkn.get("total_agricultural_area", 0):.1f} га', 'raw': egkn.get('total_agricultural_area', 0)},
                {'key': 'Количество участков', 'value': str(len(egkn.get('plots', []))), 'raw': len(egkn.get('plots', []))},
                {'key': 'Наличие с/х земли', 'value': 'Да' if egkn.get('has_agricultural_land') else 'Нет', 'raw': egkn.get('has_agricultural_land', False)},
            ],
        },
        'livestock': {
            'label': 'Поголовье',
            'items': [
                {'key': 'Верифицированных голов', 'value': str(is_iszh.get('total_verified', 0)), 'raw': is_iszh.get('total_verified', 0)},
                {'key': 'Отклонённых голов', 'value': str(is_iszh.get('total_rejected', 0)), 'raw': is_iszh.get('total_rejected', 0)},
                {'key': 'Всего животных в базе', 'value': str(len(animals)), 'raw': len(animals)},
            ],
        },
        'subsidies': {
            'label': 'История субсидий',
            'items': [
                {'key': 'Всего субсидий', 'value': str(total_subs), 'raw': total_subs},
                {'key': 'Успешно выполненных', 'value': str(successful), 'raw': successful},
                {'key': 'Невозвращённые субсидии', 'value': str(ias.get('pending_returns', 0)), 'raw': ias.get('pending_returns', 0)},
                {'key': 'Всего получено (тг)', 'value': f'{giss.get("total_subsidies_received", 0):,.0f} ₸', 'raw': giss.get('total_subsidies_received', 0)},
            ],
        },
        'obligations': {
            'label': 'Обязательства и статус',
            'items': [
                {'key': 'Встречные обязательства выполнены', 'value': 'Да' if giss.get('obligations_met') else 'Нет', 'raw': giss.get('obligations_met', False)},
                {'key': 'Зарегистрирован в ГИСС', 'value': 'Да' if giss.get('registered') else 'Нет', 'raw': giss.get('registered', False)},
                {'key': 'Заблокирован', 'value': 'Да' if giss.get('blocked') else 'Нет', 'raw': giss.get('blocked', False)},
            ],
        },
        'finance': {
            'label': 'Финансы (ЭСФ)',
            'items': [
                {'key': 'Общая сумма ЭСФ', 'value': f'{is_esf.get("total_amount", 0):,.0f} ₸', 'raw': is_esf.get('total_amount', 0)},
                {'key': 'Количество ЭСФ', 'value': str(is_esf.get('invoice_count', 0)), 'raw': is_esf.get('invoice_count', 0)},
            ],
        },
    }


def _float(val, default=0):
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _int(val, default=0):
    try:
        return int(float(val)) if val else default
    except (ValueError, TypeError):
        return default


# === Form Progress (Redis cache) ===

@login_required
@require_http_methods(['GET', 'POST', 'DELETE'])
def api_form_progress(request):
    """
    Save/load/delete form progress to Redis.
    GET  — load saved progress
    POST — save progress (JSON body)
    DELETE — clear saved progress
    """
    cache_key = f'form_progress:{request.user.id}'

    if request.method == 'GET':
        data = cache.get(cache_key)
        if data:
            return JsonResponse({'saved': True, 'data': data})
        return JsonResponse({'saved': False, 'data': None})

    elif request.method == 'POST':
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        # Save for 24 hours
        cache.set(cache_key, body, timeout=86400)
        return JsonResponse({'saved': True})

    elif request.method == 'DELETE':
        cache.delete(cache_key)
        return JsonResponse({'deleted': True})
