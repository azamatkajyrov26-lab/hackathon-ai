from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('applications/', views.application_list, name='application_list'),
    path('applications/new/', views.application_create, name='application_create'),
    path('applications/draft/', views.application_save_draft, name='application_save_draft'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/<int:pk>/decide/', views.application_decide, name='application_decide'),
    path('applications/<int:pk>/payment/', views.payment_action, name='payment_action'),
    path('scoring/', views.scoring_ranking, name='scoring_ranking'),
    path('analytics/', views.analytics, name='analytics'),
    path('commission/', views.commission, name='commission'),
    path('emulator/', views.emulator_panel, name='emulator_panel'),
    path('emulator/<int:pk>/', views.entity_detail, name='entity_detail'),
    path('emulator/<int:pk>/edit/', views.entity_edit, name='entity_edit'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/<int:pk>/read/', views.notification_read, name='notification_read'),
    path('api/entity-data/<str:iin_bin>/', views.api_entity_data, name='api_entity_data'),
    path('model-info/', views.model_info_view, name='model_info'),
    path('api/form-progress/', views.api_form_progress, name='api_form_progress'),
]
