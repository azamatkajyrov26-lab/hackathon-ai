from django.contrib import admin
from .models import EmulatedEntity


@admin.register(EmulatedEntity)
class EmulatedEntityAdmin(admin.ModelAdmin):
    list_display = ('iin_bin', 'name', 'entity_type', 'region', 'district', 'risk_profile', 'registration_date', 'source_row')
    list_filter = ('entity_type', 'risk_profile', 'region')
    search_fields = ('iin_bin', 'name', 'district')
    readonly_fields = ('created_at',)
