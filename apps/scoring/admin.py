from django.contrib import admin
from .models import (
    UserProfile, Applicant, SubsidyDirection, SubsidyType,
    Application, ApplicationDocument, HardFilterResult,
    Score, ScoreFactor, Decision, Budget, ApplicationPeriod,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'region', 'district', 'organization', 'phone')
    list_filter = ('role', 'region')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'organization', 'phone')


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = ('iin_bin', 'name', 'entity_type', 'region', 'district', 'is_blocked', 'registration_date')
    list_filter = ('entity_type', 'region', 'is_blocked')
    search_fields = ('iin_bin', 'name', 'email', 'phone')


@admin.register(SubsidyDirection)
class SubsidyDirectionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')


@admin.register(SubsidyType)
class SubsidyTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'direction', 'form_number', 'rate', 'unit', 'origin', 'requires_commission', 'is_active')
    list_filter = ('direction', 'origin', 'requires_commission', 'is_active')
    search_fields = ('name',)


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0
    readonly_fields = ('uploaded_at',)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('number', 'applicant', 'subsidy_type', 'status', 'quantity', 'total_amount', 'region', 'submitted_at')
    list_filter = ('status', 'region', 'subsidy_type__direction')
    search_fields = ('number', 'applicant__name', 'applicant__iin_bin')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ApplicationDocumentInline]


@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = ('application', 'doc_type', 'name', 'verified', 'verified_by', 'uploaded_at')
    list_filter = ('doc_type', 'verified')
    search_fields = ('name', 'application__number')


@admin.register(HardFilterResult)
class HardFilterResultAdmin(admin.ModelAdmin):
    list_display = (
        'application', 'all_passed',
        'giss_registered', 'has_eds', 'ias_rszh_registered',
        'esf_confirmed', 'no_block', 'checked_at',
    )
    list_filter = ('all_passed', 'giss_registered', 'has_eds', 'esf_confirmed', 'no_block')
    search_fields = ('application__number',)


class ScoreFactorInline(admin.TabularInline):
    model = ScoreFactor
    extra = 0
    readonly_fields = ('factor_code', 'factor_name', 'value', 'max_value', 'weight', 'weighted_value', 'data_source')


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ('application', 'total_score', 'rank', 'recommendation', 'model_version', 'calculated_at')
    list_filter = ('recommendation', 'model_version')
    search_fields = ('application__number',)
    inlines = [ScoreFactorInline]


@admin.register(ScoreFactor)
class ScoreFactorAdmin(admin.ModelAdmin):
    list_display = ('score', 'factor_code', 'factor_name', 'value', 'max_value', 'weight', 'weighted_value', 'data_source')
    list_filter = ('factor_code', 'data_source')
    search_fields = ('factor_name', 'score__application__number')


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ('application', 'decision', 'decided_by', 'approved_amount', 'decided_at', 'confirmed_by', 'confirmed_at')
    list_filter = ('decision',)
    search_fields = ('application__number', 'reason')
    readonly_fields = ('decided_at',)


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('year', 'region', 'direction', 'planned_amount', 'spent_amount')
    list_filter = ('year', 'region', 'direction')
    search_fields = ('region', 'direction__name')


@admin.register(ApplicationPeriod)
class ApplicationPeriodAdmin(admin.ModelAdmin):
    list_display = ('direction', 'is_year_round', 'start_day', 'start_month', 'end_day', 'end_month')
    list_filter = ('is_year_round',)
    search_fields = ('direction__name',)
