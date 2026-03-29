from django.urls import path

from .views import (
    GISSCheckObligationsView,
    IASRSZHCheckRegistrationView,
    EASUGetAccountNumbersView,
    ISISZHVerifyLivestockView,
    ISESFGetInvoicesView,
    EGKNGetLandPlotsView,
    TreasurySubmitPaymentView,
    TreasuryPaymentStatusView,
    EntityListView,
)

app_name = "emulator"

urlpatterns = [
    path("entities/", EntityListView.as_view(), name="entity-list"),
    path("giss/check-obligations/", GISSCheckObligationsView.as_view(), name="giss-check-obligations"),
    path("ias-rszh/check-registration/", IASRSZHCheckRegistrationView.as_view(), name="ias-rszh-check-registration"),
    path("easu/get-account-numbers/", EASUGetAccountNumbersView.as_view(), name="easu-get-account-numbers"),
    path("is-iszh/verify-livestock/", ISISZHVerifyLivestockView.as_view(), name="is-iszh-verify-livestock"),
    path("is-esf/get-invoices/", ISESFGetInvoicesView.as_view(), name="is-esf-get-invoices"),
    path("egkn/get-land-plots/", EGKNGetLandPlotsView.as_view(), name="egkn-get-land-plots"),
    path("treasury/submit-payment/", TreasurySubmitPaymentView.as_view(), name="treasury-submit-payment"),
    path("treasury/payment-status/<str:payment_id>/", TreasuryPaymentStatusView.as_view(), name="treasury-payment-status"),
]
