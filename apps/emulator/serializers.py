from rest_framework import serializers


class IINBINSerializer(serializers.Serializer):
    iin_bin = serializers.CharField(max_length=12, min_length=12)


class LivestockVerifySerializer(serializers.Serializer):
    iin_bin = serializers.CharField(max_length=12, min_length=12)
    account_number = serializers.CharField(required=False)
    animals = serializers.ListField(child=serializers.DictField(), required=False)


class InvoiceRequestSerializer(serializers.Serializer):
    iin_bin = serializers.CharField(max_length=12, min_length=12)
    counterparty_bin = serializers.CharField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class PaymentSerializer(serializers.Serializer):
    payment_id = serializers.CharField()
    applicant_iin_bin = serializers.CharField(max_length=12, min_length=12)
    bank_account = serializers.CharField(required=False)
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    subsidy_type = serializers.CharField(required=False)
    xml_data = serializers.CharField(required=False)
