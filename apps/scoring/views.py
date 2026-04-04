import json
from functools import wraps

from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Avg, Count, Sum, Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
    Application, Applicant, SubsidyDirection, SubsidyType,
    Score, ScoreFactor, HardFilterResult, Decision, Budget, UserProfile,
    Notification, Payment, AuditLog, log_action,
)


def _fmt_tg(val):
    """Форматирует сумму в тенге."""
    if val is None:
        return '—'
    val = float(val)
    if val >= 1_000_000:
        return f'{val / 1_000_000:.1f} млн ₸'
    if val >= 1_000:
        return f'{val / 1_000:.0f} тыс ₸'
    return f'{val:,.0f} ₸'


def _factor_formula(factor_code, raw_data, value, max_value):
    """Генерирует человекопонятное объяснение формулы расчёта для каждого фактора."""
    lines = []

    if factor_code == 'subsidy_history':
        total = raw_data.get('total_subsidies', 0)
        successful = raw_data.get('successful', 0)
        rate = raw_data.get('success_rate', 0)
        penalty = raw_data.get('counter_obligations_penalty', 0)
        received = raw_data.get('total_subsidies_received_tenge', 0)
        db_used = raw_data.get('db_history_used', False)

        lines.append({'label': 'Всего субсидий', 'value': str(total), 'source': 'ИАС РСЖ + БД' if db_used else 'ИАС РСЖ'})
        lines.append({'label': 'Успешных', 'value': str(successful)})
        lines.append({'label': 'Доля успеха', 'value': f'{rate:.0%}'})
        if total == 0:
            lines.append({'label': 'Формула', 'value': 'Первичный заявитель → 10 баллов (нейтральный)', 'is_formula': True})
        elif rate >= 0.9:
            lines.append({'label': 'Формула', 'value': f'Успех ≥ 90% → 18 + min({total}, 2) = {value}', 'is_formula': True})
        elif rate >= 0.7:
            lines.append({'label': 'Формула', 'value': f'Успех 70-90% → 14 + ({rate:.2f} - 0.7) × 20 = {value}', 'is_formula': True})
        elif rate >= 0.5:
            lines.append({'label': 'Формула', 'value': f'Успех 50-70% → 8 + ({rate:.2f} - 0.5) × 30 = {value}', 'is_formula': True})
        else:
            lines.append({'label': 'Формула', 'value': f'Успех < 50% → {rate:.2f} × 16 = {value}', 'is_formula': True})
        if penalty > 0:
            lines.append({'label': 'Штраф (Приказ №108)', 'value': f'-{penalty:.0f} баллов (получено {_fmt_tg(received)} субсидий, падение продукции)', 'is_penalty': True})

    elif factor_code == 'production_growth':
        growth = raw_data.get('growth_rate', 0)
        prev = raw_data.get('gross_production_previous_year', 0)
        before = raw_data.get('gross_production_year_before', 0)

        lines.append({'label': 'Продукция прошлый год', 'value': _fmt_tg(prev), 'source': 'ГИСС'})
        lines.append({'label': 'Продукция позапрошлый год', 'value': _fmt_tg(before), 'source': 'ГИСС'})
        lines.append({'label': 'Темп роста', 'value': f'{growth:+.1f}%'})
        if growth >= 10:
            lines.append({'label': 'Формула', 'value': f'Рост ≥ 10% → максимум 20 баллов', 'is_formula': True})
        elif growth >= 5:
            lines.append({'label': 'Формула', 'value': f'Рост 5-10% → 14 + ({growth:.1f} - 5) × 1.2 = {value}', 'is_formula': True})
        elif growth >= 0:
            lines.append({'label': 'Формула', 'value': f'Рост 0-5% → 8 + {growth:.1f} × 1.2 = {value}', 'is_formula': True})
        elif growth >= -5:
            lines.append({'label': 'Формула', 'value': f'Снижение 0-5% → 4 + ({growth:.1f} + 5) × 0.8 = {value}', 'is_formula': True})
        else:
            lines.append({'label': 'Формула', 'value': f'Снижение > 5% → max(0, 4 + {growth:.1f} × 0.4) = {value}', 'is_formula': True})

    elif factor_code == 'farm_size':
        land = raw_data.get('land_area', 0)
        herd = raw_data.get('herd_size', 0)
        land_s = raw_data.get('land_score', 0)
        herd_s = raw_data.get('herd_score', 0)

        lines.append({'label': 'Площадь с/х земли', 'value': f'{land:.1f} га', 'source': 'ЕГКН'})
        lines.append({'label': 'Верифицированное поголовье', 'value': f'{herd} голов', 'source': 'ИС ИСЖ'})
        lines.append({'label': 'Балл за землю', 'value': f'{land_s:.1f} из 8'})
        lines.append({'label': 'Балл за поголовье', 'value': f'{herd_s:.1f} из 7'})
        lines.append({'label': 'Формула', 'value': f'{land_s:.1f} (земля) + {herd_s:.1f} (поголовье) = {value}', 'is_formula': True})

    elif factor_code == 'efficiency':
        total_heads = raw_data.get('total_heads_subsidized', 0)
        returns = raw_data.get('pending_returns', 0)
        retention = raw_data.get('retention_rate')
        co_bonus = raw_data.get('counter_obligations_bonus', 0)
        co_penalty = raw_data.get('counter_obligations_penalty', 0)
        co_required = raw_data.get('counter_obligations_required', False)

        lines.append({'label': 'Субсидированных голов', 'value': str(total_heads), 'source': 'ИАС РСЖ'})
        lines.append({'label': 'Возвратов/потерь', 'value': str(returns)})
        if retention is not None:
            lines.append({'label': 'Сохранность', 'value': f'{retention:.0%}'})
        if co_required:
            lines.append({'label': 'Встречные обязательства', 'value': 'Требуются (субсидий > 100 млн ₸)', 'source': 'ГИСС'})
        if co_bonus > 0:
            lines.append({'label': 'Бонус за рост продукции', 'value': f'+{co_bonus:.0f} баллов', 'is_bonus': True})
        if co_penalty > 0:
            lines.append({'label': 'Штраф за снижение', 'value': f'-{co_penalty:.0f} баллов', 'is_penalty': True})
        lines.append({'label': 'Формула', 'value': f'Базовый балл сохранности ± обязательства = {value}', 'is_formula': True})

    elif factor_code == 'rate_compliance':
        esf_total = raw_data.get('esf_total', 0)
        requested = raw_data.get('requested', 0)
        expected = raw_data.get('expected', 0)
        rate_match = raw_data.get('rate_match', False)
        esf_covers = raw_data.get('esf_covers', False)

        lines.append({'label': 'Запрошено', 'value': _fmt_tg(requested)})
        lines.append({'label': 'По нормативу', 'value': _fmt_tg(expected)})
        lines.append({'label': 'Сумма ЭСФ', 'value': _fmt_tg(esf_total), 'source': 'ИС ЭСФ'})
        lines.append({'label': 'Совпадает с нормативом?', 'value': 'Да' if rate_match else 'Нет'})
        lines.append({'label': 'ЭСФ покрывает стоимость?', 'value': 'Да' if esf_covers else 'Нет'})
        if rate_match and esf_covers:
            lines.append({'label': 'Формула', 'value': 'Норматив совпал + ЭСФ покрывает → 10 баллов (максимум)', 'is_formula': True})
        elif rate_match:
            lines.append({'label': 'Формула', 'value': 'Норматив совпал, но ЭСФ не покрывает → 6 баллов', 'is_formula': True})
        elif esf_covers:
            lines.append({'label': 'Формула', 'value': 'Норматив не совпал, но ЭСФ покрывает → 4 балла', 'is_formula': True})
        else:
            lines.append({'label': 'Формула', 'value': 'Ни норматив, ни ЭСФ не совпали → 2 балла', 'is_formula': True})

    elif factor_code == 'region_priority':
        region = raw_data.get('region', '')
        direction = raw_data.get('direction_code', '')
        priority = raw_data.get('priority', 0.5)

        lines.append({'label': 'Регион', 'value': region})
        lines.append({'label': 'Направление', 'value': direction})
        lines.append({'label': 'Приоритет региона', 'value': f'{priority:.1f} из 1.0', 'source': 'Справочник МСХ'})
        lines.append({'label': 'Формула', 'value': f'{priority:.1f} × 10 = {value}', 'is_formula': True})

    elif factor_code == 'entity_type':
        etype = raw_data.get('entity_type', '')
        labels = {'cooperative': 'СПК (5 баллов)', 'legal': 'Юрлицо (4 балла)', 'individual': 'Физлицо (3 балла)'}
        lines.append({'label': 'Тип заявителя', 'value': labels.get(etype, etype), 'source': 'ЕАСУ'})
        lines.append({'label': 'Формула', 'value': f'СПК=5, Юрлицо=4, Физлицо=3 → {value}', 'is_formula': True})

    elif factor_code == 'applicant_history':
        total = raw_data.get('total_subsidies', 0)
        same_dir = raw_data.get('has_same_direction', False)
        db_total = raw_data.get('db_total_apps', 0)
        db_avg = raw_data.get('db_avg_score')

        lines.append({'label': 'Всего заявок', 'value': str(total), 'source': 'ИАС РСЖ + БД'})
        if db_avg:
            lines.append({'label': 'Средний балл прошлых заявок', 'value': f'{db_avg:.1f}', 'source': 'БД'})
        if total == 0:
            lines.append({'label': 'Формула', 'value': 'Первичный заявитель → 4 балла (приоритет новых)', 'is_formula': True})
        elif not same_dir and db_total == 0:
            lines.append({'label': 'Формула', 'value': 'Диверсификация (новое направление) → 5 баллов', 'is_formula': True})
        elif total <= 3:
            lines.append({'label': 'Формула', 'value': f'Умеренный повторный заявитель ({total} заявок) → 3 балла', 'is_formula': True})
        else:
            lines.append({'label': 'Формула', 'value': f'Частый заявитель ({total} заявок) → 2 балла', 'is_formula': True})

    return lines


def _shap_value_explain(feature, feature_value):
    """Человекопонятное объяснение SHAP значения признака."""
    explanations = {
        'giss_registered': lambda v: 'Зарегистрирован в ГИСС' if v else 'Не зарегистрирован в ГИСС',
        'growth_rate': lambda v: f'Темп роста продукции: {v:+.1f}%',
        'gross_production_prev': lambda v: f'Валовая продукция: {v:.1f} млн ₸',
        'gross_production_before': lambda v: f'Валовая продукция (год ранее): {v:.1f} млн ₸',
        'obligations_met': lambda v: 'Обязательства выполнены' if v else 'Обязательства не выполнены',
        'total_subsidies_received': lambda v: f'Получено субсидий: {v:.1f} млн ₸',
        'ias_registered': lambda v: 'Зарегистрирован в ИАС РСЖ' if v else 'Не зарегистрирован',
        'subsidy_history_count': lambda v: f'{int(v)} субсидий в истории',
        'subsidy_success_rate': lambda v: f'Доля успешных субсидий: {v:.0%}',
        'pending_returns': lambda v: f'{int(v)} невозвращённых субсидий',
        'total_verified_animals': lambda v: f'{int(v)} верифицированных животных',
        'total_rejected_animals': lambda v: f'{int(v)} отклонённых животных',
        'animal_age_valid_ratio': lambda v: f'Доля с допустимым возрастом: {v:.0%}',
        'esf_total_amount': lambda v: f'Сумма ЭСФ: {v:.1f} млн ₸',
        'esf_invoice_count': lambda v: f'{int(v)} счетов-фактур',
        'esf_confirmed_ratio': lambda v: f'Подтверждённых ЭСФ: {v:.0%}',
        'has_agricultural_land': lambda v: 'Есть с/х земля' if v else 'Нет с/х земли',
        'total_agricultural_area': lambda v: f'Площадь с/х земли: {v:.1f} га',
        'entity_type_encoded': lambda v: {0: 'Физлицо', 1: 'Юрлицо', 2: 'СПК (кооператив)'}.get(int(v), f'Тип {int(v)}'),
        'treasury_payment_count': lambda v: f'{int(v)} платежей через Казначейство',
    }
    fn = explanations.get(feature)
    if fn:
        try:
            return fn(feature_value)
        except (ValueError, TypeError):
            pass
    return f'{feature_value}'


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
        try:
            user_unit_price = float(request.POST.get('unit_price', 0) or 0)
        except (ValueError, TypeError):
            user_unit_price = 0
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

        # Серверная пре-валидация: проверяем базовые условия до создания заявки
        from apps.emulator.models import EmulatedEntity
        pre_entity = EmulatedEntity.objects.filter(iin_bin=iin_bin).first()
        if pre_entity:
            pre_giss = pre_entity.giss_data or {}
            pre_easu = pre_entity.easu_data or {}
            pre_ias = pre_entity.ias_rszh_data or {}
            pre_errors = []
            if not pre_giss.get('registered', False):
                pre_errors.append('Нет регистрации в ГИСС')
            if pre_giss.get('blocked', False):
                pre_errors.append('Аккаунт заблокирован в ГИСС')
            if not pre_easu.get('has_account_number', False):
                pre_errors.append('Нет ЭЦП (ЕАСУ)')
            if not pre_ias.get('registered', False) and entity_type != 'cooperative':
                pre_errors.append('Нет регистрации в ИАС РСЖ')
            # Проверка дублирующей заявки — нельзя подать на тот же тип субсидии в текущем году
            from django.utils import timezone as tz
            dup_exists = Application.objects.filter(
                applicant__iin_bin=iin_bin,
                subsidy_type=stype,
                created_at__year=tz.now().year,
            ).exclude(status='rejected').exists()
            if dup_exists:
                pre_errors.append(
                    f'У вас уже есть заявка на "{stype.name}" в {tz.now().year} году. '
                    f'Повторная подача не допускается (Приказ №108 МСХ РК).'
                )
            # Проверяем выбранных животных на ранее субсидированных
            for a in selected_animals:
                if a.get('previously_subsidized', False):
                    pre_errors.append(f'Животное {a.get("tag", a.get("tag_number", ""))} ранее субсидировалось')
            # Проверка 50% стоимости
            if user_unit_price > 0 and float(stype.rate) > user_unit_price * 0.5:
                pre_errors.append(
                    f'Ставка субсидии ({stype.rate} ₸) превышает 50% от стоимости покупки ({user_unit_price * 0.5:.0f} ₸)'
                )
            if pre_errors:
                for err in pre_errors:
                    messages.error(request, err)
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
            unit_price=user_unit_price if user_unit_price > 0 else float(stype.rate),
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

        log_action(
            user=request.user, action='create',
            entity_type='Application', entity_id=app.id,
            description=f'Создана заявка {app.number} на сумму {app.total_amount} ₸',
            request=request,
            metadata={'number': app.number, 'subsidy_type': stype.name, 'amount': str(app.total_amount)},
        )

        messages.success(request, f'Заявка {app.number} создана и оценена')
        return redirect(f'/applications/{app.id}/success/')

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

    return render(request, 'scoring/application_form_v2.html', {
        'directions': directions,
        'subsidy_types': subsidy_types,
        'regions': regions,
        'profile_iin': profile_iin,
        'profile_name': profile_name,
    })


@login_required
def application_success(request, pk):
    """Экран успешной подачи заявки."""
    app = get_object_or_404(Application, pk=pk)
    try:
        score = app.score
    except Score.DoesNotExist:
        score = None
    return render(request, 'scoring/application_success.html', {
        'app': app,
        'score': score,
    })


@login_required
def scoring_methodology(request):
    """Страница с описанием методологии скоринга — формулы и объяснения."""
    return render(request, 'scoring/scoring_methodology.html')


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

    # Hard filter items for display — rich data for farmer-friendly view
    filter_items = []
    if hard_filters:
        raw = hard_filters.raw_responses or {}
        giss = raw.get('giss', {})
        ias = raw.get('ias_rszh', {})
        egkn = raw.get('egkn', {})
        is_iszh = raw.get('is_iszh', {})
        esf = raw.get('is_esf', {})
        easu = raw.get('easu', {})

        filter_items = [
            {
                'name': 'Регистрация в ГИСС',
                'passed': hard_filters.giss_registered,
                'icon': 'fa-landmark',
                'color': 'blue',
                'system': 'ГИСС',
                'description': 'Проверяем, зарегистрированы ли вы в Государственной информационной системе субсидирования.',
                'detail': f'Статус: {"Зарегистрирован" if giss.get("registered") else "Не найден"}',
                'action': 'Обратитесь в местное управление сельского хозяйства для регистрации в ГИСС.',
            },
            {
                'name': 'Электронная цифровая подпись (ЭЦП)',
                'passed': hard_filters.has_eds,
                'icon': 'fa-key',
                'color': 'purple',
                'system': 'ЕАСУ',
                'description': 'Проверяем наличие действующей ЭЦП для подписания документов.',
                'detail': f'Учётная запись ЕАСУ: {"Активна" if easu.get("has_account_number") else "Не найдена"}',
                'action': 'Получите ЭЦП в ЦОНе или на сайте НУЦ РК (pki.gov.kz).',
            },
            {
                'name': 'Учётный номер в ИАС «РСЖ»',
                'passed': hard_filters.ias_rszh_registered,
                'icon': 'fa-id-card',
                'color': 'green',
                'system': 'ИАС РСЖ',
                'description': 'Проверяем регистрацию в информационно-аналитической системе развития сельского хозяйства.',
                'detail': f'Регистрация: {"Подтверждена" if ias.get("registered") else "Не найдена"}. {("Учётный номер: " + str(ias.get("account_number", ""))) if ias.get("account_number") else ""}',
                'action': 'Зарегистрируйтесь в ИАС РСЖ через местное управление сельского хозяйства.',
            },
            {
                'name': 'Земельный участок с/х назначения',
                'passed': hard_filters.has_agricultural_land,
                'icon': 'fa-map',
                'color': 'cyan',
                'system': 'ЕГКН',
                'description': 'Проверяем наличие земельного участка сельскохозяйственного назначения в кадастровой базе.',
                'detail': f'Земля с/х назначения: {"Есть" if egkn.get("has_agricultural_land") else "Не найдена"}. Общая площадь: {egkn.get("total_area", 0)} га',
                'action': 'Убедитесь, что ваш земельный участок зарегистрирован в ЕГКН. Обратитесь в ЦОН или Земельный комитет.',
            },
            {
                'name': 'Идентификация животных (ИС ИСЖ)',
                'passed': hard_filters.is_iszh_registered,
                'icon': 'fa-cow',
                'color': 'amber',
                'system': 'ИС ИСЖ',
                'description': 'Проверяем наличие верифицированных (с биркой) животных в системе идентификации.',
                'detail': f'Верифицировано животных: {is_iszh.get("total_verified", 0)} из {is_iszh.get("total_animals", 0)}',
                'action': 'Обратитесь к ветеринарному врачу для идентификации (биркования) ваших животных.',
            },
            {
                'name': 'Регистрация в ИБСПР',
                'passed': hard_filters.ibspr_registered,
                'icon': 'fa-building',
                'color': 'indigo',
                'system': 'ИАС РСЖ',
                'description': 'Проверяем регистрацию в интегрированной базе субъектов предпринимательства.',
                'detail': f'ИБСПР: {"Зарегистрирован" if ias.get("ibspr_registered", ias.get("registered")) else "Не найден"}',
                'action': 'Регистрация в ИБСПР происходит автоматически через ИАС РСЖ. Обратитесь в управление сельского хозяйства.',
            },
            {
                'name': 'Подтверждение затрат через ЭСФ',
                'passed': hard_filters.esf_confirmed,
                'icon': 'fa-file-invoice-dollar',
                'color': 'pink',
                'system': 'ИС ЭСФ',
                'description': 'Проверяем наличие подтверждённых электронных счетов-фактур, подтверждающих ваши расходы.',
                'detail': f'Всего ЭСФ: {esf.get("invoice_count", 0)}. Подтверждённых: {sum(1 for inv in esf.get("invoices", []) if inv.get("payment_confirmed"))}',
                'action': 'Убедитесь, что продавец выписал ЭСФ и что она подтверждена в системе ИС ЭСФ (esf.gov.kz).',
            },
            {
                'name': 'Выполнение встречных обязательств',
                'passed': hard_filters.no_unfulfilled_obligations,
                'icon': 'fa-handshake',
                'color': 'teal',
                'system': 'ГИСС',
                'description': 'Проверяем, выполнены ли ваши предыдущие обязательства по субсидиям (рост продукции +2%/год).',
                'detail': f'Обязательства: {"Выполнены" if giss.get("obligations_met") else "Не выполнены" if giss.get("obligations_required") else "Не требуются"}. Рост продукции: {giss.get("growth_rate", "—")}%',
                'action': 'Выполните встречные обязательства: обеспечьте рост валовой продукции не менее 2% в год.',
            },
            {
                'name': 'Отсутствие блокировки',
                'passed': hard_filters.no_block,
                'icon': 'fa-lock-open',
                'color': 'red',
                'system': 'ГИСС',
                'description': 'Проверяем, нет ли блокировки за нарушения (снижение продукции при субсидиях >100 млн ₸).',
                'detail': f'Блокировка ГИСС: {"Нет" if not giss.get("blocked") else "Заблокирован"}. Блокировка по заявителю: {"Нет" if not app.applicant.is_blocked else "До " + str(app.applicant.block_until)}',
                'action': 'Блокировка снимается автоматически после истечения срока. При вопросах обратитесь в управление с/х.',
            },
            {
                'name': 'Возраст животных',
                'passed': hard_filters.animals_age_valid,
                'icon': 'fa-calendar-check',
                'color': 'orange',
                'system': 'ИС ИСЖ',
                'description': 'Проверяем, что возраст ваших животных соответствует требованиям данного вида субсидии.',
                'detail': f'Животных в системе: {len(is_iszh.get("animals", []))}. Все в допустимом возрасте: {"Да" if hard_filters.animals_age_valid else "Нет"}',
                'action': 'Убедитесь, что животные соответствуют возрастным требованиям субсидии. Проверьте данные в ИС ИСЖ.',
            },
            {
                'name': 'Животные не субсидировались ранее',
                'passed': hard_filters.animals_not_subsidized,
                'icon': 'fa-ban',
                'color': 'gray',
                'system': 'ИС ИСЖ',
                'description': 'Проверяем, что заявленные животные не получали субсидии ранее (запрет двойного субсидирования).',
                'detail': f'Ранее субсидированных: {sum(1 for a in is_iszh.get("animals", []) if a.get("previously_subsidized"))} из {len(is_iszh.get("animals", []))}',
                'action': 'Нельзя получить субсидию на животное повторно. Подайте заявку только на новых животных.',
            },
        ]
        # Add extra filters 12-15 if available
        if hasattr(hard_filters, 'application_period_valid'):
            filter_items.extend([
                {
                    'name': 'Период подачи заявки',
                    'passed': hard_filters.application_period_valid,
                    'icon': 'fa-calendar',
                    'color': 'violet',
                    'system': 'Приказ №108',
                    'description': 'Проверяем, что заявка подана в установленный период приёма заявок.',
                    'detail': f'Дата подачи: {app.submitted_at.strftime("%d.%m.%Y") if app.submitted_at else "—"}',
                    'action': 'Подайте заявку в период приёма. Сроки уточняйте в управлении сельского хозяйства.',
                },
                {
                    'name': 'Сумма субсидии в пределах нормы',
                    'passed': hard_filters.subsidy_amount_valid,
                    'icon': 'fa-calculator',
                    'color': 'emerald',
                    'system': 'Приказ №108',
                    'description': 'Проверяем, что сумма субсидии не превышает 50% стоимости приобретённых животных.',
                    'detail': f'Запрошенная сумма: {app.total_amount:,.0f} ₸',
                    'action': 'Уменьшите запрашиваемую сумму до 50% от фактической стоимости животных.',
                },
                {
                    'name': 'Минимальное поголовье',
                    'passed': hard_filters.min_herd_size_met,
                    'icon': 'fa-hashtag',
                    'color': 'lime',
                    'system': 'Приказ №108',
                    'description': 'Проверяем, что поголовье соответствует минимальным требованиям для данного типа хозяйства.',
                    'detail': f'Верифицировано: {is_iszh.get("total_verified", 0)} голов',
                    'action': 'Увеличьте поголовье до минимальных требований для вашего типа хозяйства.',
                },
                {
                    'name': 'Нет дублирующих заявок',
                    'passed': hard_filters.no_duplicate_application,
                    'icon': 'fa-copy',
                    'color': 'slate',
                    'system': 'SubsidyAI',
                    'description': 'Проверяем, что у вас нет уже одобренной заявки на этот же вид субсидии в текущем году.',
                    'detail': '',
                    'action': 'Нельзя подать две заявки на один вид субсидии в одном году.',
                },
                {
                    'name': 'Падёж скота в пределах нормы',
                    'passed': hard_filters.mortality_within_norm,
                    'icon': 'fa-heartbeat',
                    'color': 'rose',
                    'system': 'Пр��каз №3-3/1061',
                    'description': 'Проверяем, что процент падежа скота не превышает установленные нормы естественной убыли.',
                    'detail': '',
                    'action': 'Улучшите условия содержания животных. Обратитесь к ветеринарной службе.',
                },
                {
                    'name': 'Нагрузка на пастбища в норме',
                    'passed': hard_filters.pasture_load_valid,
                    'icon': 'fa-leaf',
                    'color': 'green',
                    'system': 'Приказ №3-3/332',
                    'description': 'Проверяем, что поголовье не превышает допустимую нагрузку на имеющиеся пастбища.',
                    'detail': '',
                    'action': 'Увеличьте площадь пастбищ или уменьшите поголовье до допустимой нормы.',
                },
                {
                    'name': 'Племенное свидетельство',
                    'passed': hard_filters.pedigree_valid,
                    'icon': 'fa-certificate',
                    'color': 'amber',
                    'system': 'Приказ №108',
                    'description': 'Для племенных субсидий (формы 1-8) все животные должны иметь племенное свидетельство.',
                    'detail': '',
                    'action': 'Получите племенное свидетельство на животных в аттестованной племенной организации.',
                },
            ])

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
            # Человекопонятное описание значения признака
            item['value_explanation'] = _shap_value_explain(
                item.get('feature', ''), item.get('feature_value', 0)
            )
        shap_data = {
            'items': shap_items,
            'base_value': score.explanation.get('base_value', 0),
        }

    # Enriched factors with raw_data for detailed display
    factors_enriched = []
    for f in factors:
        fe = {
            'factor_name': f.factor_name,
            'factor_code': f.factor_code,
            'value': f.value,
            'max_value': f.max_value,
            'weight': f.weight,
            'weighted_value': f.weighted_value,
            'explanation': f.explanation,
            'data_source': f.data_source,
            'raw_data': f.raw_data or {},
            'formula': _factor_formula(f.factor_code, f.raw_data or {}, f.value, f.max_value),
        }
        factors_enriched.append(fe)

    # ML vs Rules breakdown
    scoring_breakdown = None
    if score and score.recommendation_reason:
        reason = score.recommendation_reason
        rule_score = None
        ml_score = None
        ml_confidence = None
        # Parse from recommendation_reason: "[AI модель: XX.X баллов, уверенность XX%; Правила: XX.X; Итого: XX.X/100]"
        import re
        m = re.search(r'AI модель:\s*([\d.]+)\s*баллов.*?уверенность\s*([\d.]+)%.*?Правила:\s*([\d.]+)', reason)
        if m:
            ml_score = float(m.group(1))
            ml_confidence = float(m.group(2))
            rule_score = float(m.group(3))
        scoring_breakdown = {
            'ml_score': ml_score,
            'ml_confidence': ml_confidence,
            'rule_score': rule_score,
            'total_score': float(score.total_score),
            'has_ml': ml_score is not None,
            'ml_weight': 60,
            'rule_weight': 40,
        }

    return render(request, 'scoring/application_detail.html', {
        'app': app,
        'score': score,
        'factors': factors_enriched,
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
        'scoring_breakdown': scoring_breakdown,
        'user_role': role,
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

    dec = Decision.objects.create(
        application=app,
        decision=decision_val,
        decided_by=request.user,
        reason=reason,
    )

    log_action(
        user=request.user, action='decide',
        entity_type='Decision', entity_id=dec.id,
        description=f'Решение «{dec.get_decision_display()}» по заявке {app.number}: {reason}',
        request=request,
        metadata={'application_number': app.number, 'decision': decision_val},
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
        .filter(application__status__in=['approved', 'waiting_list', 'submitted', 'checking'])
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


@role_required('commission_member', 'mio_head')
@require_http_methods(['POST'])
def batch_decide(request):
    """Пакетное решение по нескольким заявкам."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Некорректный JSON'}, status=400)

    application_ids = body.get('application_ids', [])
    decision_val = body.get('decision', '')
    reason = body.get('reason', '')

    if not application_ids or not isinstance(application_ids, list):
        return JsonResponse({'error': 'Укажите список заявок'}, status=400)

    if decision_val not in ('approved', 'rejected'):
        return JsonResponse({'error': 'Допустимые решения: approved, rejected'}, status=400)

    if not reason or not reason.strip():
        return JsonResponse({'error': 'Укажите обоснование'}, status=400)

    status_map = {
        'approved': 'approved',
        'rejected': 'rejected',
    }

    processed = 0

    with transaction.atomic():
        apps = Application.objects.filter(pk__in=application_ids)
        for app in apps:
            Decision.objects.create(
                application=app,
                decision=decision_val,
                decided_by=request.user,
                reason=reason.strip(),
            )
            app.status = status_map[decision_val]
            app.save()

            # Платёжный flow: при одобрении создаём платёж
            if decision_val == 'approved':
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
            if decision_val == 'approved':
                ntype, title, msg = 'approved', 'Заявка одобрена', f'Комиссия одобрила вашу заявку {app.number}. Сумма {app.total_amount} ₸ направлена на формирование платежа.'
            else:
                ntype, title, msg = 'rejected', 'Заявка отклонена', f'Комиссия отклонила заявку {app.number}. Причина: {reason.strip()}'

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

            log_action(
                user=request.user,
                action='decide',
                entity_type='Application',
                entity_id=app.pk,
                description=f'Пакетное решение: {decision_val} — {reason.strip()[:100]}',
                request=request,
                metadata={'batch': True, 'decision': decision_val},
            )

            processed += 1

    decision_label = 'одобрено' if decision_val == 'approved' else 'отклонено'
    return JsonResponse({
        'success': True,
        'processed': processed,
        'message': f'Решение "{decision_label}" применено к {processed} заявкам',
    })


@role_required('applicant')
def farmer_dashboard(request):
    """Личный кабинет фермера — данные из всех внешних систем."""
    from apps.emulator.models import EmulatedEntity
    from collections import defaultdict

    iin_bin = getattr(request.user.profile, 'iin_bin', '')
    entity = None
    if iin_bin:
        entity = EmulatedEntity.objects.filter(iin_bin=iin_bin).first()

    if not entity:
        return render(request, 'scoring/farmer_dashboard.html', {'entity': None})

    # --- Animals grouped by type ---
    animals = entity.is_iszh_data.get('animals', [])
    animals_by_type = defaultdict(list)
    for a in animals:
        animals_by_type[a.get('type', 'other')].append(a)
    animals_by_type = dict(animals_by_type)

    animal_summary = {
        'total': len(animals),
        'verified': entity.is_iszh_data.get('total_verified', 0),
        'rejected': entity.is_iszh_data.get('total_rejected', 0),
        'cattle': len(animals_by_type.get('cattle', [])),
        'sheep': len(animals_by_type.get('sheep', [])),
        'horse': len(animals_by_type.get('horse', [])),
        'poultry': len(animals_by_type.get('poultry', [])),
    }

    # --- Pre-scoring estimate (5 of 8 factors, no Application needed) ---
    giss = entity.giss_data or {}
    rszh = entity.ias_rszh_data or {}
    egkn = entity.egkn_data or {}
    iszh = entity.is_iszh_data or {}
    esf = entity.is_esf_data or {}

    pre_factors = []

    # Factor 1: Subsidy History
    history = rszh.get('subsidy_history', [])
    total_subs = len(history)
    successful = sum(1 for h in history if h.get('status') == 'executed' and h.get('obligations_met', False))
    sr = successful / total_subs if total_subs > 0 else 0
    if total_subs == 0:
        f1_score = 10.0
    elif sr >= 0.9:
        f1_score = 18 + min(total_subs, 2)
    elif sr >= 0.7:
        f1_score = 14 + (sr - 0.7) * 20
    elif sr >= 0.5:
        f1_score = 8 + (sr - 0.5) * 30
    else:
        f1_score = sr * 16
    # Counter-obligations penalty
    total_received = giss.get('total_subsidies_received', 0)
    if total_received > 100_000_000:
        prev_yr = giss.get('gross_production_previous_year', 0)
        yr_before = giss.get('gross_production_year_before', 0)
        if yr_before > 0 and prev_yr < yr_before:
            consec = giss.get('consecutive_decline_years', 0)
            f1_score -= 6.0 if consec >= 2 else 3.0
    f1_score = min(20.0, max(0.0, f1_score))
    pre_factors.append({
        'name': 'История субсидий', 'value': round(f1_score, 1),
        'max_value': 20, 'percentage': round(f1_score / 20 * 100),
        'status': 'good' if f1_score >= 14 else ('warn' if f1_score >= 8 else 'bad'),
        'explanation': f'{total_subs} субсидий, {successful} успешных ({sr:.0%})' if total_subs > 0 else 'Нет истории — нейтральный балл',
    })

    # Factor 2: Production Growth
    gr = giss.get('growth_rate', 0)
    if gr >= 10:
        f2_score = 20.0
    elif gr >= 5:
        f2_score = 14 + (gr - 5) * 1.2
    elif gr >= 0:
        f2_score = 8 + gr * 1.2
    elif gr >= -5:
        f2_score = 4 + (gr + 5) * 0.8
    else:
        f2_score = max(0, 4 + gr * 0.4)
    f2_score = min(20.0, max(0.0, f2_score))
    pre_factors.append({
        'name': 'Рост производства', 'value': round(f2_score, 1),
        'max_value': 20, 'percentage': round(f2_score / 20 * 100),
        'status': 'good' if gr >= 3 else ('warn' if gr >= 0 else 'bad'),
        'explanation': f'Рост {gr:+.1f}%' if gr != 0 else 'Нет данных о производстве',
    })

    # Factor 3: Farm Size
    land_area = egkn.get('total_agricultural_area', 0)
    herd_size = iszh.get('total_verified', 0)
    l_sc = min(8.0, max(0.0, (4 + (land_area - 100) / 100) if land_area >= 100 else (land_area / 25 if land_area >= 10 else 0)))
    h_sc = min(7.0, max(0.0, (3.5 + (herd_size - 50) / 42.8) if herd_size >= 50 else (herd_size / 14.3 if herd_size >= 10 else 0)))
    if land_area >= 500:
        l_sc = 8.0
    if herd_size >= 200:
        h_sc = 7.0
    f3_score = min(15.0, l_sc + h_sc)
    pre_factors.append({
        'name': 'Размер хозяйства', 'value': round(f3_score, 1),
        'max_value': 15, 'percentage': round(f3_score / 15 * 100),
        'status': 'good' if f3_score >= 10 else ('warn' if f3_score >= 5 else 'bad'),
        'explanation': f'{land_area:.0f} га земли, {herd_size} голов',
    })

    # Factor 4: Efficiency
    total_heads = sum(h.get('heads', 0) for h in history)
    returns = rszh.get('pending_returns', 0)
    if total_heads == 0:
        f4_score = 10.0
    else:
        ret_rate = max(0.0, min(1.0, 1 - (returns / total_heads)))
        if ret_rate >= 0.98:
            f4_score = 15.0
        elif ret_rate >= 0.90:
            f4_score = 11 + (ret_rate - 0.90) * 50
        elif ret_rate >= 0.80:
            f4_score = 7 + (ret_rate - 0.80) * 40
        else:
            f4_score = ret_rate * 8.75
    # Counter-obligations bonus/penalty
    prev_yr = giss.get('gross_production_previous_year', 0)
    yr_before = giss.get('gross_production_year_before', 0)
    if total_received > 100_000_000 and yr_before > 0:
        if prev_yr >= yr_before:
            f4_score += 2.0
        elif giss.get('consecutive_decline_years', 0) >= 2:
            f4_score -= 5.0
        else:
            f4_score -= 2.0
    elif yr_before > 0 and prev_yr >= yr_before:
        f4_score += 1.0
    f4_score = min(15.0, max(0.0, f4_score))
    pre_factors.append({
        'name': 'Эффективность', 'value': round(f4_score, 1),
        'max_value': 15, 'percentage': round(f4_score / 15 * 100),
        'status': 'good' if f4_score >= 10 else ('warn' if f4_score >= 6 else 'bad'),
        'explanation': f'{returns} невозвратов' if total_heads > 0 else 'Нет истории',
    })

    # Factor 5: Entity Type (no application needed)
    et = entity.entity_type
    f5_score = 5.0 if et == 'cooperative' else (4.0 if et == 'legal' else 3.0)
    pre_factors.append({
        'name': 'Тип заявителя', 'value': round(f5_score, 1),
        'max_value': 5, 'percentage': round(f5_score / 5 * 100),
        'status': 'good' if f5_score >= 4 else 'warn',
        'explanation': {'cooperative': 'СПК', 'legal': 'Юрлицо', 'individual': 'Физлицо'}.get(et, et),
    })

    # Neutral estimates for application-dependent factors
    pre_factors.append({
        'name': 'Соответствие нормативу', 'value': 7.0, 'max_value': 10,
        'percentage': 70, 'status': 'warn',
        'explanation': 'Зависит от конкретной заявки',
    })
    pre_factors.append({
        'name': 'Региональный приоритет', 'value': 5.0, 'max_value': 10,
        'percentage': 50, 'status': 'warn',
        'explanation': f'{entity.region} — зависит от направления',
    })
    pre_factors.append({
        'name': 'Первичность заявителя', 'value': 3.0, 'max_value': 5,
        'percentage': 60, 'status': 'warn',
        'explanation': 'Зависит от направления',
    })

    total_pre_score = sum(f['value'] for f in pre_factors)
    max_possible = sum(f['max_value'] for f in pre_factors)

    weak_areas = [f['name'] for f in pre_factors if f['status'] == 'bad']
    if total_pre_score >= 70:
        rec = 'Хорошие шансы на одобрение'
        rec_class = 'rec-approve'
    elif total_pre_score >= 45:
        rec = 'Средние шансы — обратите внимание на слабые места'
        rec_class = 'rec-review'
    else:
        rec = 'Низкие шансы — рекомендуем улучшить показатели'
        rec_class = 'rec-reject'

    pre_score = {
        'total': round(total_pre_score, 1),
        'max': max_possible,
        'factors': pre_factors,
        'recommendation': rec,
        'rec_class': rec_class,
        'weak_areas': weak_areas,
    }

    # --- Hard filter quick summary ---
    hf_passed = 0
    hf_failed = []
    if giss.get('registered'):
        hf_passed += 1
    else:
        hf_failed.append('Не зарегистрирован в ГИСС')
    if rszh.get('registered'):
        hf_passed += 1
    else:
        hf_failed.append('Не зарегистрирован в ИАС РСЖ')
    if not giss.get('blocked', False):
        hf_passed += 1
    else:
        hf_failed.append(f'Заблокирован: {giss.get("block_reason", "?")}')
    if entity.easu_data and entity.easu_data.get('has_account_number'):
        hf_passed += 1
    else:
        hf_failed.append('Нет расчётного счёта')
    if egkn.get('has_agricultural_land'):
        hf_passed += 1
    else:
        hf_failed.append('Нет с/х земли')
    if rszh.get('pending_returns', 0) == 0:
        hf_passed += 1
    else:
        hf_failed.append(f'Невозврат: {rszh["pending_returns"]} тг')
    confirmed_esf = any(
        inv.get('status') == 'confirmed'
        for inv in esf.get('invoices', [])
    )
    if confirmed_esf:
        hf_passed += 1
    else:
        hf_failed.append('Нет подтверждённых ЭСФ')

    # --- Regulatory checks (Приказы №3-3/1061, №3-3/332) ---
    mortality_data = iszh.get('mortality_data', {})
    total_mort_pct = mortality_data.get('total_mortality_pct', 0)
    if mortality_data and total_mort_pct <= 3.0:
        hf_passed += 1
    elif mortality_data:
        hf_failed.append(f'Падёж {total_mort_pct:.1f}% выше нормы (Приказ №3-3/1061)')

    pasture_area = egkn.get('pasture_area', 0)
    if pasture_area > 0:
        hf_passed += 1
    else:
        hf_failed.append('Нет данных о пастбищах (Приказ №3-3/332)')

    hard_filter_summary = {
        'total': 18,
        'passed': hf_passed,
        'checkable': hf_passed + len(hf_failed),
        'failed_reasons': hf_failed,
    }

    # --- My applications ---
    my_apps = Application.objects.filter(
        applicant__iin_bin=iin_bin
    ).select_related('subsidy_type__direction').order_by('-created_at')[:10]

    context = {
        'entity': entity,
        'animals': animals,
        'animals_by_type': animals_by_type,
        'animal_summary': animal_summary,
        'subsidy_history': history,
        'giss_data': giss,
        'ias_rszh_data': rszh,
        'invoices': esf.get('invoices', []),
        'esf_summary': esf,
        'plots': egkn.get('plots', []),
        'plots_json': json.dumps(egkn.get('plots', []), ensure_ascii=False),
        'egkn_data': egkn,
        'easu_data': entity.easu_data or {},
        'payments': (entity.treasury_data or {}).get('payments', []),
        'pre_score': pre_score,
        'my_applications': my_apps,
        'hard_filter_summary': hard_filter_summary,
        'mortality_data': mortality_data,
        'pasture_area': egkn.get('pasture_area', 0),
        'pasture_zone': egkn.get('pasture_zone', ''),
    }
    return render(request, 'scoring/farmer_dashboard.html', context)


@role_required('applicant')
def farmer_analytics(request):
    """Страница аналитики фермера — pre-scoring, субсидии, обязательства, ЭСФ, финансы."""
    from apps.emulator.models import EmulatedEntity
    from collections import defaultdict

    iin_bin = getattr(request.user.profile, 'iin_bin', '')
    entity = None
    if iin_bin:
        entity = EmulatedEntity.objects.filter(iin_bin=iin_bin).first()

    if not entity:
        return render(request, 'scoring/farmer_analytics.html', {'entity': None})

    # --- Animals grouped by type (needed for summary stats) ---
    animals = entity.is_iszh_data.get('animals', [])
    animals_by_type = defaultdict(list)
    for a in animals:
        animals_by_type[a.get('type', 'other')].append(a)
    animals_by_type = dict(animals_by_type)

    animal_summary = {
        'total': len(animals),
        'verified': entity.is_iszh_data.get('total_verified', 0),
        'rejected': entity.is_iszh_data.get('total_rejected', 0),
        'cattle': len(animals_by_type.get('cattle', [])),
        'sheep': len(animals_by_type.get('sheep', [])),
        'horse': len(animals_by_type.get('horse', [])),
        'poultry': len(animals_by_type.get('poultry', [])),
    }

    # --- Pre-scoring estimate (5 of 8 factors, no Application needed) ---
    giss = entity.giss_data or {}
    rszh = entity.ias_rszh_data or {}
    egkn = entity.egkn_data or {}
    iszh = entity.is_iszh_data or {}
    esf = entity.is_esf_data or {}

    pre_factors = []

    # Factor 1: Subsidy History
    history = rszh.get('subsidy_history', [])
    total_subs = len(history)
    successful = sum(1 for h in history if h.get('status') == 'executed' and h.get('obligations_met', False))
    sr = successful / total_subs if total_subs > 0 else 0
    if total_subs == 0:
        f1_score = 10.0
    elif sr >= 0.9:
        f1_score = 18 + min(total_subs, 2)
    elif sr >= 0.7:
        f1_score = 14 + (sr - 0.7) * 20
    elif sr >= 0.5:
        f1_score = 8 + (sr - 0.5) * 30
    else:
        f1_score = sr * 16
    total_received = giss.get('total_subsidies_received', 0)
    if total_received > 100_000_000:
        prev_yr = giss.get('gross_production_previous_year', 0)
        yr_before = giss.get('gross_production_year_before', 0)
        if yr_before > 0 and prev_yr < yr_before:
            consec = giss.get('consecutive_decline_years', 0)
            f1_score -= 6.0 if consec >= 2 else 3.0
    f1_score = min(20.0, max(0.0, f1_score))
    pre_factors.append({
        'name': 'История субсидий', 'value': round(f1_score, 1),
        'max_value': 20, 'percentage': round(f1_score / 20 * 100),
        'status': 'good' if f1_score >= 14 else ('warn' if f1_score >= 8 else 'bad'),
        'explanation': f'{total_subs} субсидий, {successful} успешных ({sr:.0%})' if total_subs > 0 else 'Нет истории — нейтральный балл',
    })

    # Factor 2: Production Growth
    gr = giss.get('growth_rate', 0)
    if gr >= 10:
        f2_score = 20.0
    elif gr >= 5:
        f2_score = 14 + (gr - 5) * 1.2
    elif gr >= 0:
        f2_score = 8 + gr * 1.2
    elif gr >= -5:
        f2_score = 4 + (gr + 5) * 0.8
    else:
        f2_score = max(0, 4 + gr * 0.4)
    f2_score = min(20.0, max(0.0, f2_score))
    pre_factors.append({
        'name': 'Рост производства', 'value': round(f2_score, 1),
        'max_value': 20, 'percentage': round(f2_score / 20 * 100),
        'status': 'good' if gr >= 3 else ('warn' if gr >= 0 else 'bad'),
        'explanation': f'Рост {gr:+.1f}%' if gr != 0 else 'Нет данных о производстве',
    })

    # Factor 3: Farm Size
    land_area = egkn.get('total_agricultural_area', 0)
    herd_size = iszh.get('total_verified', 0)
    l_sc = min(8.0, max(0.0, (4 + (land_area - 100) / 100) if land_area >= 100 else (land_area / 25 if land_area >= 10 else 0)))
    h_sc = min(7.0, max(0.0, (3.5 + (herd_size - 50) / 42.8) if herd_size >= 50 else (herd_size / 14.3 if herd_size >= 10 else 0)))
    if land_area >= 500:
        l_sc = 8.0
    if herd_size >= 200:
        h_sc = 7.0
    f3_score = min(15.0, l_sc + h_sc)
    pre_factors.append({
        'name': 'Размер хозяйства', 'value': round(f3_score, 1),
        'max_value': 15, 'percentage': round(f3_score / 15 * 100),
        'status': 'good' if f3_score >= 10 else ('warn' if f3_score >= 5 else 'bad'),
        'explanation': f'{land_area:.0f} га земли, {herd_size} голов',
    })

    # Factor 4: Efficiency
    total_heads = sum(h.get('heads', 0) for h in history)
    returns = rszh.get('pending_returns', 0)
    if total_heads == 0:
        f4_score = 10.0
    else:
        ret_rate = max(0.0, min(1.0, 1 - (returns / total_heads)))
        if ret_rate >= 0.98:
            f4_score = 15.0
        elif ret_rate >= 0.90:
            f4_score = 11 + (ret_rate - 0.90) * 50
        elif ret_rate >= 0.80:
            f4_score = 7 + (ret_rate - 0.80) * 40
        else:
            f4_score = ret_rate * 8.75
    prev_yr = giss.get('gross_production_previous_year', 0)
    yr_before = giss.get('gross_production_year_before', 0)
    if total_received > 100_000_000 and yr_before > 0:
        if prev_yr >= yr_before:
            f4_score += 2.0
        elif giss.get('consecutive_decline_years', 0) >= 2:
            f4_score -= 5.0
        else:
            f4_score -= 2.0
    elif yr_before > 0 and prev_yr >= yr_before:
        f4_score += 1.0
    f4_score = min(15.0, max(0.0, f4_score))
    pre_factors.append({
        'name': 'Эффективность', 'value': round(f4_score, 1),
        'max_value': 15, 'percentage': round(f4_score / 15 * 100),
        'status': 'good' if f4_score >= 10 else ('warn' if f4_score >= 6 else 'bad'),
        'explanation': f'{returns} невозвратов' if total_heads > 0 else 'Нет истории',
    })

    # Factor 5: Entity Type
    et = entity.entity_type
    f5_score = 5.0 if et == 'cooperative' else (4.0 if et == 'legal' else 3.0)
    pre_factors.append({
        'name': 'Тип заявителя', 'value': round(f5_score, 1),
        'max_value': 5, 'percentage': round(f5_score / 5 * 100),
        'status': 'good' if f5_score >= 4 else 'warn',
        'explanation': {'cooperative': 'СПК', 'legal': 'Юрлицо', 'individual': 'Физлицо'}.get(et, et),
    })

    # Neutral estimates for application-dependent factors
    pre_factors.append({
        'name': 'Соответствие нормативу', 'value': 7.0, 'max_value': 10,
        'percentage': 70, 'status': 'warn',
        'explanation': 'Зависит от конкретной заявки',
    })
    pre_factors.append({
        'name': 'Региональный приоритет', 'value': 5.0, 'max_value': 10,
        'percentage': 50, 'status': 'warn',
        'explanation': f'{entity.region} — зависит от направления',
    })
    pre_factors.append({
        'name': 'Первичность заявителя', 'value': 3.0, 'max_value': 5,
        'percentage': 60, 'status': 'warn',
        'explanation': 'Зависит от направления',
    })

    total_pre_score = sum(f['value'] for f in pre_factors)
    max_possible = sum(f['max_value'] for f in pre_factors)

    weak_areas = [f['name'] for f in pre_factors if f['status'] == 'bad']
    if total_pre_score >= 70:
        rec = 'Хорошие шансы на одобрение'
        rec_class = 'rec-approve'
    elif total_pre_score >= 45:
        rec = 'Средние шансы — обратите внимание на слабые места'
        rec_class = 'rec-review'
    else:
        rec = 'Низкие шансы — рекомендуем улучшить показатели'
        rec_class = 'rec-reject'

    pre_score = {
        'total': round(total_pre_score, 1),
        'max': max_possible,
        'factors': pre_factors,
        'recommendation': rec,
        'rec_class': rec_class,
        'weak_areas': weak_areas,
    }

    # --- Hard filter quick summary ---
    hf_passed = 0
    hf_failed = []
    if giss.get('registered'):
        hf_passed += 1
    else:
        hf_failed.append('Не зарегистрирован в ГИСС')
    if rszh.get('registered'):
        hf_passed += 1
    else:
        hf_failed.append('Не зарегистрирован в ИАС РСЖ')
    if not giss.get('blocked', False):
        hf_passed += 1
    else:
        hf_failed.append(f'Заблокирован: {giss.get("block_reason", "?")}')
    if entity.easu_data and entity.easu_data.get('has_account_number'):
        hf_passed += 1
    else:
        hf_failed.append('Нет расчётного счёта')
    if egkn.get('has_agricultural_land'):
        hf_passed += 1
    else:
        hf_failed.append('Нет с/х земли')
    if rszh.get('pending_returns', 0) == 0:
        hf_passed += 1
    else:
        hf_failed.append(f'Невозврат: {rszh["pending_returns"]} тг')
    confirmed_esf = any(
        inv.get('status') == 'confirmed'
        for inv in esf.get('invoices', [])
    )
    if confirmed_esf:
        hf_passed += 1
    else:
        hf_failed.append('Нет подтверждённых ЭСФ')

    # --- Regulatory checks (Приказы №3-3/1061, №3-3/332) ---
    mortality_data = iszh.get('mortality_data', {})
    total_mort_pct = mortality_data.get('total_mortality_pct', 0)
    if mortality_data and total_mort_pct <= 3.0:
        hf_passed += 1
    elif mortality_data:
        hf_failed.append(f'Падёж {total_mort_pct:.1f}% выше нормы (Приказ №3-3/1061)')

    pasture_area = egkn.get('pasture_area', 0)
    if pasture_area > 0:
        hf_passed += 1
    else:
        hf_failed.append('Нет данных о пастбищах (Приказ №3-3/332)')

    hard_filter_summary = {
        'total': 18,
        'passed': hf_passed,
        'checkable': hf_passed + len(hf_failed),
        'failed_reasons': hf_failed,
    }

    # --- My applications ---
    my_apps = Application.objects.filter(
        applicant__iin_bin=iin_bin
    ).select_related('subsidy_type__direction').order_by('-created_at')[:10]

    context = {
        'entity': entity,
        'animals': animals,
        'animals_by_type': animals_by_type,
        'animal_summary': animal_summary,
        'subsidy_history': history,
        'giss_data': giss,
        'ias_rszh_data': rszh,
        'invoices': esf.get('invoices', []),
        'esf_summary': esf,
        'plots': egkn.get('plots', []),
        'egkn_data': egkn,
        'easu_data': entity.easu_data or {},
        'payments': (entity.treasury_data or {}).get('payments', []),
        'pre_score': pre_score,
        'my_applications': my_apps,
        'hard_filter_summary': hard_filter_summary,
    }
    return render(request, 'scoring/farmer_analytics.html', context)


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
            log_action(
                user=user, action='login',
                entity_type='User', entity_id=user.id,
                description=f'Вход через ЭЦП (ИИН/БИН: {iin_bin})',
                request=request,
                metadata={'method': 'ecp', 'iin_bin': iin_bin},
            )
            return redirect('/dashboard/')

        else:
            # ── Обычный вход (для служебных ролей / демо) ──
            username = request.POST.get('username')
            password = request.POST.get('password')
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                log_action(
                    user=user, action='login',
                    entity_type='User', entity_id=user.id,
                    description=f'Вход по логину/паролю ({username})',
                    request=request,
                    metadata={'method': 'password'},
                )
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

    try:
        draft_unit_price = float(data.get('unit_price', 0) or 0)
    except (ValueError, TypeError):
        draft_unit_price = 0

    app = Application.objects.create(
        number=number,
        applicant=applicant,
        subsidy_type=stype,
        status='draft',
        quantity=quantity,
        unit_price=draft_unit_price if draft_unit_price > 0 else float(stype.rate),
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
        log_action(
            user=request.user, action='payment',
            entity_type='Payment', entity_id=payment.id,
            description=f'Платёж по заявке {app.number} отправлен в Казначейство (реф: {payment.treasury_ref})',
            request=request,
            metadata={'application_number': app.number, 'treasury_ref': payment.treasury_ref, 'step': 'send_to_treasury'},
        )
        messages.success(request, f'Платёж отправлен в Казначейство (реф: {payment.treasury_ref})')
    elif action == 'complete' and payment.status == 'sent_to_treasury':
        payment.status = 'completed'
        payment.completed_at = timezone.now()
        payment.save()
        app.status = 'paid'
        app.save()
        log_action(
            user=request.user, action='payment',
            entity_type='Payment', entity_id=payment.id,
            description=f'Выплата {payment.amount} ₸ по заявке {app.number} произведена',
            request=request,
            metadata={'application_number': app.number, 'amount': str(payment.amount), 'step': 'completed'},
        )
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
                'rfid_tag': a.get('rfid_tag'),
                'rfid_active': a.get('rfid_active', False),
                'rfid_last_scan': a.get('rfid_last_scan'),
                'rfid_scan_count_30d': a.get('rfid_scan_count_30d', 0),
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
        # СПК данные (ШАГ 9 AS-IS)
        'spk_name': (entity.easu_data or {}).get('spk_name', ''),
        'spk_members': (entity.easu_data or {}).get('spk_members', []),
        # RFID summary
        'rfid_summary': {
            'total_animals': len(is_iszh.get('animals', [])),
            'with_rfid': sum(1 for a in is_iszh.get('animals', []) if a.get('rfid_tag')),
            'active_rfid': sum(1 for a in is_iszh.get('animals', []) if a.get('rfid_active')),
            'inactive_rfid': sum(1 for a in is_iszh.get('animals', []) if a.get('rfid_tag') and not a.get('rfid_active')),
            'no_rfid': sum(1 for a in is_iszh.get('animals', []) if not a.get('rfid_tag')),
            'coverage_pct': round(sum(1 for a in is_iszh.get('animals', []) if a.get('rfid_tag')) / max(len(is_iszh.get('animals', [])), 1) * 100),
        },
        # Предварительные проверки (hard filters preview)
        'checks': {
            'giss_registered': giss.get('registered', False),
            'ias_registered': ias.get('registered', False),
            'has_eds': (entity.easu_data or {}).get('has_account_number', False),
            'has_land': egkn.get('has_agricultural_land', False),
            'not_blocked': not giss.get('blocked', False),
            'obligations_met': giss.get('obligations_met', True),
            'block_reason': giss.get('block_reason', ''),
        },
    })


@login_required
@require_http_methods(["POST"])
def api_save_land_polygons(request):
    """API: сохраняет GeoJSON полигоны земельных участков фермера."""
    from apps.emulator.models import EmulatedEntity
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'No profile'}, status=403)

    entity = EmulatedEntity.objects.filter(iin_bin=profile.iin_bin).first()
    if not entity:
        return JsonResponse({'error': 'Entity not found'}, status=404)

    try:
        data = json.loads(request.body)
        polygons = data.get('polygons', [])
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    egkn = entity.egkn_data or {}
    plots = egkn.get('plots', [])

    # Assign polygons to plots (by index, or append as new)
    for i, polygon in enumerate(polygons):
        if i < len(plots):
            plots[i]['geometry'] = polygon
        # Extra polygons beyond existing plots are stored as custom_polygons

    # Store any extra drawn polygons
    if len(polygons) > len(plots):
        egkn['custom_polygons'] = polygons[len(plots):]

    egkn['plots'] = plots
    entity.egkn_data = egkn
    entity.save(update_fields=['egkn_data'])

    return JsonResponse({'ok': True, 'plots_updated': len(plots)})


def api_rfid_status(request, iin_bin):
    """API: возвращает RFID-мониторинг для всех животных по ИИН/БИН."""
    from django.http import JsonResponse
    from apps.emulator.models import EmulatedEntity, RFIDMonitoring

    try:
        entity = EmulatedEntity.objects.get(iin_bin=iin_bin)
    except EmulatedEntity.DoesNotExist:
        return JsonResponse({'found': False})

    records = RFIDMonitoring.objects.filter(entity=entity).order_by('-last_scan_date')
    animals = (entity.is_iszh_data or {}).get('animals', [])

    rfid_list = []
    for r in records:
        rfid_list.append({
            'animal_tag': r.animal_tag,
            'rfid_tag': r.rfid_tag,
            'status': r.status,
            'status_display': r.get_status_display(),
            'last_scan_date': r.last_scan_date.isoformat() if r.last_scan_date else None,
            'scan_location': r.scan_location,
            'scan_count_30d': r.scan_count_30d,
            'animal_type': r.animal_type,
            'reader_type': r.reader_type,
        })

    total = len(animals)
    with_rfid = sum(1 for a in animals if a.get('rfid_tag'))
    active = sum(1 for a in animals if a.get('rfid_active'))

    return JsonResponse({
        'found': True,
        'entity_name': entity.name,
        'iin_bin': entity.iin_bin,
        'rfid_records': rfid_list,
        'summary': {
            'total_animals': total,
            'with_rfid': with_rfid,
            'active_rfid': active,
            'inactive_rfid': with_rfid - active,
            'no_rfid': total - with_rfid,
            'coverage_pct': round(with_rfid / max(total, 1) * 100),
            'active_pct': round(active / max(total, 1) * 100),
        },
    })


def rfid_dashboard(request):
    """RFID-мониторинг: дашборд для фермера и проверяющего."""
    from apps.emulator.models import EmulatedEntity, RFIDMonitoring
    from apps.scoring.models import UserProfile

    context = {'page_title': 'RFID-мониторинг'}

    # If farmer — show their own farm
    profile = getattr(request.user, 'profile', None)
    if profile and profile.iin_bin:
        try:
            entity = EmulatedEntity.objects.get(iin_bin=profile.iin_bin)
            animals = (entity.is_iszh_data or {}).get('animals', [])
            records = RFIDMonitoring.objects.filter(entity=entity)
            total = len(animals)
            with_rfid = sum(1 for a in animals if a.get('rfid_tag'))
            active = sum(1 for a in animals if a.get('rfid_active'))
            context.update({
                'entity': entity,
                'animals': animals,
                'rfid_records': records,
                'total_animals': total,
                'with_rfid': with_rfid,
                'active_rfid': active,
                'no_rfid': total - with_rfid,
                'coverage_pct': round(with_rfid / max(total, 1) * 100),
                'active_pct': round(active / max(total, 1) * 100),
            })
        except EmulatedEntity.DoesNotExist:
            pass

    return render(request, 'scoring/rfid_dashboard.html', context)


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
def api_check_duplicate(request):
    """Проверяет, есть ли уже заявка на данный тип субсидии в текущем году."""
    iin_bin = request.GET.get('iin_bin', '')
    stype_id = request.GET.get('subsidy_type', '')
    if not iin_bin or not stype_id:
        return JsonResponse({'duplicate': False})
    from django.utils import timezone as tz
    dup = Application.objects.filter(
        applicant__iin_bin=iin_bin,
        subsidy_type_id=stype_id,
        created_at__year=tz.now().year,
    ).exclude(status='rejected').first()
    if dup:
        return JsonResponse({
            'duplicate': True,
            'message': f'У вас уже есть заявка №{dup.number} на этот вид субсидии ({dup.get_status_display()}). Повторная подача не допускается.',
            'app_number': dup.number,
            'app_status': dup.status,
        })
    return JsonResponse({'duplicate': False})


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


@role_required('admin', 'auditor')
def audit_log_view(request):
    """Журнал аудита — доступен администраторам и аудиторам."""
    logs = AuditLog.objects.select_related('user').all()

    action_filter = request.GET.get('action', '')
    if action_filter:
        logs = logs.filter(action=action_filter)

    search = request.GET.get('q', '')
    if search:
        logs = logs.filter(
            Q(description__icontains=search) |
            Q(entity_type__icontains=search) |
            Q(user__username__icontains=search) |
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search)
        )

    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'scoring/audit_log.html', {
        'logs': page_obj,
        'page_obj': page_obj,
        'action_choices': AuditLog.ACTION_CHOICES,
        'current_action': action_filter,
        'search_query': search,
    })


@role_required('mio_specialist', 'commission_member', 'mio_head', 'admin', 'auditor')
def export_application_pdf(request, pk):
    """Export application card as PDF."""
    import io
    import os

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )

    # Register Cyrillic font
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        font_path_bold = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('DejaVu', font_path))
            if os.path.exists(font_path_bold):
                pdfmetrics.registerFont(TTFont('DejaVu-Bold', font_path_bold))
            else:
                pdfmetrics.registerFont(TTFont('DejaVu-Bold', font_path))
            FONT = 'DejaVu'
            FONT_BOLD = 'DejaVu-Bold'
        else:
            FONT = 'Helvetica'
            FONT_BOLD = 'Helvetica-Bold'
    except Exception:
        FONT = 'Helvetica'
        FONT_BOLD = 'Helvetica-Bold'

    app = get_object_or_404(
        Application.objects.select_related('applicant', 'subsidy_type__direction'),
        pk=pk,
    )

    try:
        score = app.score
    except Score.DoesNotExist:
        score = None
    factors = list(ScoreFactor.objects.filter(score=score).order_by('-weighted_value')) if score else []
    hard_filters = HardFilterResult.objects.filter(application=app).first()
    decisions = app.decisions.select_related('decided_by').order_by('-decided_at')

    # Build PDF
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=15 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm)

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle('TitleCyr', parent=styles['Title'],
                                 fontName=FONT_BOLD, fontSize=16, leading=20)
    style_h2 = ParagraphStyle('H2Cyr', parent=styles['Heading2'],
                               fontName=FONT_BOLD, fontSize=12, leading=15,
                               spaceBefore=12, spaceAfter=6)
    style_normal = ParagraphStyle('NormalCyr', parent=styles['Normal'],
                                   fontName=FONT, fontSize=9, leading=12)
    style_small = ParagraphStyle('SmallCyr', parent=styles['Normal'],
                                  fontName=FONT, fontSize=8, leading=10)

    elements = []

    # --- Header ---
    elements.append(Paragraph(
        f'\u041a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u0437\u0430\u044f\u0432\u043a\u0438 \u2116{app.number}',
        style_title,
    ))
    elements.append(Spacer(1, 4 * mm))

    # --- Applicant info ---
    elements.append(Paragraph(
        '1. \u0417\u0430\u044f\u0432\u0438\u0442\u0435\u043b\u044c', style_h2))
    applicant_data = [
        ['\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435', app.applicant.name],
        ['\u0418\u0418\u041d/\u0411\u0418\u041d', app.applicant.iin_bin],
        ['\u041e\u0431\u043b\u0430\u0441\u0442\u044c', app.region],
        ['\u0420\u0430\u0439\u043e\u043d', app.district or '\u2014'],
        ['\u0422\u0438\u043f \u0441\u0443\u0431\u044a\u0435\u043a\u0442\u0430', app.applicant.get_entity_type_display()],
    ]
    t = Table(applicant_data, colWidths=[55 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), FONT_BOLD),
        ('FONTNAME', (1, 0), (1, -1), FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
        ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 3 * mm))

    # --- Subsidy info ---
    elements.append(Paragraph(
        '2. \u0421\u0443\u0431\u0441\u0438\u0434\u0438\u044f', style_h2))
    subsidy_data = [
        ['\u041d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435', app.subsidy_type.direction.name],
        ['\u0412\u0438\u0434 \u0441\u0443\u0431\u0441\u0438\u0434\u0438\u0438', app.subsidy_type.name],
        ['\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e', f'{app.quantity} {app.subsidy_type.unit}'],
        ['\u041d\u043e\u0440\u043c\u0430\u0442\u0438\u0432', f'{app.rate:,.2f} \u20b8'],
        ['\u0421\u0443\u043c\u043c\u0430', f'{app.total_amount:,.2f} \u20b8'],
    ]
    t = Table(subsidy_data, colWidths=[55 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), FONT_BOLD),
        ('FONTNAME', (1, 0), (1, -1), FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
        ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 3 * mm))

    # --- Scoring results ---
    if score:
        elements.append(Paragraph(
            '3. \u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u0441\u043a\u043e\u0440\u0438\u043d\u0433\u0430',
            style_h2,
        ))

        rec_map = {
            'approve': '\u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c',
            'review': '\u041d\u0430 \u0443\u0441\u043c\u043e\u0442\u0440\u0435\u043d\u0438\u0435',
            'reject': '\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c',
        }

        # ML/rule score from explanation if available
        ml_score = ''
        rule_score = ''
        if score.explanation:
            ml_score = score.explanation.get('ml_score', '')
            rule_score = score.explanation.get('rule_score', '')

        score_data = [
            ['\u0418\u0442\u043e\u0433\u043e\u0432\u044b\u0439 \u0431\u0430\u043b\u043b', f'{score.total_score} / 100'],
            ['\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f',
             rec_map.get(score.recommendation, score.recommendation)],
        ]
        if ml_score:
            score_data.append(['ML Score', str(ml_score)])
        if rule_score:
            score_data.append(['Rule Score', str(rule_score)])
        score_data.append([
            '\u0412\u0435\u0440\u0441\u0438\u044f \u043c\u043e\u0434\u0435\u043b\u0438',
            score.model_version,
        ])

        t = Table(score_data, colWidths=[55 * mm, 120 * mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), FONT_BOLD),
            ('FONTNAME', (1, 0), (1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
            ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3 * mm))

    # --- Hard filters ---
    if hard_filters:
        elements.append(Paragraph(
            '4. \u0416\u0451\u0441\u0442\u043a\u0438\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 (Hard Filters)',
            style_h2,
        ))

        filter_items_pdf = [
            ('\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u0432 \u0413\u0418\u0421\u0421',
             hard_filters.giss_registered),
            ('\u041d\u0430\u043b\u0438\u0447\u0438\u0435 \u042d\u0426\u041f', hard_filters.has_eds),
            ('\u0423\u0447\u0451\u0442\u043d\u044b\u0439 \u043d\u043e\u043c\u0435\u0440 \u0418\u0410\u0421 \u0420\u0421\u0416',
             hard_filters.ias_rszh_registered),
            ('\u0417\u0435\u043c\u0435\u043b\u044c\u043d\u044b\u0439 \u0443\u0447\u0430\u0441\u0442\u043e\u043a \u0415\u0413\u041a\u041d',
             hard_filters.has_agricultural_land),
            ('\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u0432 \u0418\u0421 \u0418\u0421\u0416',
             hard_filters.is_iszh_registered),
            ('\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u0432 \u0418\u0411\u0421\u041f\u0420',
             hard_filters.ibspr_registered),
            ('\u042d\u0421\u0424 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430',
             hard_filters.esf_confirmed),
            ('\u041d\u0435\u0442 \u043d\u0435\u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043d\u044b\u0445 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u0441\u0442\u0432',
             hard_filters.no_unfulfilled_obligations),
            ('\u041d\u0435\u0442 \u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u043a\u0438', hard_filters.no_block),
            ('\u0412\u043e\u0437\u0440\u0430\u0441\u0442 \u0436\u0438\u0432\u043e\u0442\u043d\u044b\u0445',
             hard_filters.animals_age_valid),
            ('\u041d\u0435 \u0441\u0443\u0431\u0441\u0438\u0434\u0438\u0440\u043e\u0432\u0430\u043b\u0438\u0441\u044c \u0440\u0430\u043d\u0435\u0435',
             hard_filters.animals_not_subsidized),
            ('\u0421\u0440\u043e\u043a \u043f\u043e\u0434\u0430\u0447\u0438',
             hard_filters.application_period_valid),
            ('\u041b\u0438\u043c\u0438\u0442 \u0441\u0443\u043c\u043c\u044b',
             hard_filters.subsidy_amount_valid),
            ('\u041c\u0438\u043d. \u043f\u043e\u0433\u043e\u043b\u043e\u0432\u044c\u0435',
             hard_filters.min_herd_size_met),
            ('\u041d\u0435\u0442 \u0434\u0443\u0431\u043b\u0438\u043a\u0430\u0442\u043e\u0432',
             hard_filters.no_duplicate_application),
            ('Падёж в норме (Приказ №3-3/1061)',
             hard_filters.mortality_within_norm),
            ('Нагрузка на пастбища (Приказ №3-3/332)',
             hard_filters.pasture_load_valid),
            ('Племенное свидетельство (Приказ №108)',
             hard_filters.pedigree_valid),
        ]

        hf_table_data = [['\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430', '\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442']]
        for name, passed in filter_items_pdf:
            hf_table_data.append([name, 'PASS' if passed else 'FAIL'])

        t = Table(hf_table_data, colWidths=[120 * mm, 55 * mm])
        row_colors = []
        for i, (name, passed) in enumerate(filter_items_pdf):
            row_idx = i + 1
            if passed:
                row_colors.append(
                    ('TEXTCOLOR', (1, row_idx), (1, row_idx), colors.Color(0, 0.5, 0)))
            else:
                row_colors.append(
                    ('TEXTCOLOR', (1, row_idx), (1, row_idx), colors.Color(0.8, 0, 0)))

        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('FONTNAME', (0, 1), (0, -1), FONT),
            ('FONTNAME', (1, 1), (1, -1), FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ] + row_colors))
        elements.append(t)

        overall = 'PASS' if hard_filters.all_passed else 'FAIL'
        overall_color = '006600' if hard_filters.all_passed else 'CC0000'
        elements.append(Spacer(1, 2 * mm))
        elements.append(Paragraph(
            f'<font color="#{overall_color}"><b>'
            f'\u0418\u0442\u043e\u0433: {overall} '
            f'({sum(1 for _, p in filter_items_pdf if p)}/{len(filter_items_pdf)})'
            f'</b></font>',
            style_normal,
        ))
        elements.append(Spacer(1, 3 * mm))

    # --- SHAP top 5 ---
    if score and score.explanation and score.explanation.get('shap_values'):
        elements.append(Paragraph(
            '5. SHAP \u2014 \u0442\u043e\u043f 5 \u0444\u0430\u043a\u0442\u043e\u0440\u043e\u0432',
            style_h2,
        ))
        shap_items = score.explanation['shap_values'][:5]
        shap_table_data = [
            ['\u0424\u0430\u043a\u0442\u043e\u0440',
             '\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435 SHAP',
             '\u0412\u043b\u0438\u044f\u043d\u0438\u0435'],
        ]
        for item in shap_items:
            val = item.get('shap_value', 0)
            direction = ('\u2191 \u041f\u043e\u0432\u044b\u0448\u0430\u0435\u0442'
                         if val >= 0
                         else '\u2193 \u0421\u043d\u0438\u0436\u0430\u0435\u0442')
            shap_table_data.append([
                item.get('feature_ru', item.get('feature', '')),
                f'{val:+.2f}',
                direction,
            ])

        t = Table(shap_table_data, colWidths=[90 * mm, 40 * mm, 45 * mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3 * mm))

    # --- Soft factors ---
    if factors:
        section_num = 6 if (
            score and score.explanation and score.explanation.get('shap_values')
        ) else 5
        elements.append(Paragraph(
            f'{section_num}. \u0424\u0430\u043a\u0442\u043e\u0440\u044b \u0441\u043a\u043e\u0440\u0438\u043d\u0433\u0430 (Soft Factors)',
            style_h2,
        ))

        factors_table_data = [
            ['\u0424\u0430\u043a\u0442\u043e\u0440',
             '\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435',
             '\u041c\u0430\u043a\u0441\u0438\u043c\u0443\u043c',
             '\u0412\u0435\u0441',
             '\u0412\u0437\u0432\u0435\u0448\u0435\u043d\u043d\u043e\u0435'],
        ]
        for f in factors[:8]:
            factors_table_data.append([
                f.factor_name,
                f'{f.value}',
                f'{f.max_value}',
                f'{f.weight}',
                f'{f.weighted_value}',
            ])

        t = Table(factors_table_data, colWidths=[70 * mm, 25 * mm, 25 * mm, 25 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('FONTNAME', (0, 1), (-1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3 * mm))

    # --- Decision ---
    last_decision = decisions.first()
    if last_decision:
        dec_map = {
            'approved': '\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e',
            'rejected': '\u041e\u0442\u043a\u0430\u0437',
            'review': '\u0414\u043e\u043f. \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430',
            'partially_approved': '\u0427\u0430\u0441\u0442\u0438\u0447\u043d\u043e \u043e\u0434\u043e\u0431\u0440\u0435\u043d\u043e',
        }
        section_num_dec = 7
        elements.append(Paragraph(
            f'{section_num_dec}. \u0420\u0435\u0448\u0435\u043d\u0438\u0435', style_h2))
        dec_data = [
            ['\u0420\u0435\u0448\u0435\u043d\u0438\u0435',
             dec_map.get(last_decision.decision, last_decision.decision)],
            ['\u041f\u0440\u0438\u043d\u044f\u043b',
             last_decision.decided_by.get_full_name()],
            ['\u041e\u0431\u043e\u0441\u043d\u043e\u0432\u0430\u043d\u0438\u0435',
             last_decision.reason or '\u2014'],
            ['\u0414\u0430\u0442\u0430',
             last_decision.decided_at.strftime('%d.%m.%Y %H:%M')
             if last_decision.decided_at else '\u2014'],
        ]

        t = Table(dec_data, colWidths=[55 * mm, 120 * mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), FONT_BOLD),
            ('FONTNAME', (1, 0), (1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
            ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ]))
        elements.append(t)

    # --- Footer ---
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(
        f'\u0421\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d\u043e: '
        f'{timezone.now().strftime("%d.%m.%Y %H:%M")} | '
        f'\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c: '
        f'{request.user.get_full_name() or request.user.username} | '
        f'SubsidyAI',
        style_small,
    ))

    doc.build(elements)
    buf.seek(0)

    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="application_{app.number}.pdf"'
    )
    return response
