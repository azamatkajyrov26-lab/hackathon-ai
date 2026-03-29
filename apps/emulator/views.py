from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import EmulatedEntity
from .serializers import (
    IINBINSerializer,
    LivestockVerifySerializer,
    InvoiceRequestSerializer,
    PaymentSerializer,
)

NOT_FOUND = {"error": "Entity not found"}


def get_entity_or_none(iin_bin):
    try:
        return EmulatedEntity.objects.get(iin_bin=iin_bin)
    except EmulatedEntity.DoesNotExist:
        return None


class GISSCheckObligationsView(APIView):
    """ГИСС — Статистика и встречные обязательства."""

    def post(self, request):
        serializer = IINBINSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(entity.giss_data)


class IASRSZHCheckRegistrationView(APIView):
    """ИАС «РСЖ» — Регистрация и поголовье."""

    def post(self, request):
        serializer = IINBINSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(entity.ias_rszh_data)


class EASUGetAccountNumbersView(APIView):
    """ЕАСУ — Учётные номера."""

    def post(self, request):
        serializer = IINBINSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(entity.easu_data)


class ISISZHVerifyLivestockView(APIView):
    """ИС «ИСЖ» — Идентификация животных."""

    def post(self, request):
        serializer = LivestockVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(entity.is_iszh_data)


class ISESFGetInvoicesView(APIView):
    """ИС «ЭСФ» — Электронные счета-фактуры."""

    def post(self, request):
        serializer = InvoiceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(entity.is_esf_data)


class EGKNGetLandPlotsView(APIView):
    """ЕГКН — Земельный кадастр."""

    def post(self, request):
        serializer = IINBINSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(entity.egkn_data)


class TreasurySubmitPaymentView(APIView):
    """ИС «Клиент-Казначейство» — Подача платежа."""

    def post(self, request):
        serializer = PaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity = get_entity_or_none(serializer.validated_data["applicant_iin_bin"])
        if not entity:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        data = entity.treasury_data.copy() if entity.treasury_data else {}
        data.setdefault("status", "accepted")
        data.setdefault("payment_id", serializer.validated_data["payment_id"])
        return Response(data)


class EntityListView(APIView):
    """Список сущностей эмулятора (для демо)."""

    def get(self, request):
        page_size = int(request.query_params.get('page_size', 6))
        entities = EmulatedEntity.objects.all()[:page_size]
        results = [
            {
                'iin_bin': e.iin_bin,
                'name': e.name,
                'entity_type': e.entity_type,
                'risk_profile': e.risk_profile,
                'region': e.region,
            }
            for e in entities
        ]
        return Response({'results': results})


class TreasuryPaymentStatusView(APIView):
    """ИС «Клиент-Казначейство» — Статус платежа."""

    def get(self, request, payment_id):
        # Search across all entities for a matching payment_id in treasury_data
        entities = EmulatedEntity.objects.all()
        for entity in entities:
            if entity.treasury_data and entity.treasury_data.get("payment_id") == payment_id:
                return Response(entity.treasury_data)
        # Fallback: return a generic status
        return Response({
            "payment_id": payment_id,
            "status": "not_found",
        }, status=status.HTTP_404_NOT_FOUND)
