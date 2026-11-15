"""Explicit presentation settings; financial policy is never writable here."""
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from xml.sax.saxutils import escape

from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .currency import CURRENCY_CODE, CURRENCY_NAME, CURRENCY_SYMBOL
from .models import OrganisationSettings, AuditLog, COMMISSION_RATE
from .permissions import IsSuperAdmin

EDITABLE_FIELDS = ('display_name', 'address', 'telephone', 'contact_email',
                   'receipt_heading', 'receipt_footer', 'timezone', 'date_format')


def current_settings():
    # Reads do not create records or change historical transactions.
    return OrganisationSettings.objects.filter(pk=1).first() or OrganisationSettings(pk=1)


class OrganisationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganisationSettings
        fields = EDITABLE_FIELDS

    def validate(self, attrs):
        errors = {key: 'This field cannot be edited here.' for key in set(self.initial_data) - set(EDITABLE_FIELDS)}
        for key, value in attrs.items():
            if any(ord(c) < 32 and not (key in ('address', 'receipt_footer') and c == '\n') or ord(c) == 127 for c in value):
                errors[key] = 'Control characters are not allowed.'
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError('Enter a valid IANA timezone, such as Africa/Lagos.')
        return value

    def validate_telephone(self, value):
        if value and not re.fullmatch(r'[+0-9() .-]{3,40}', value):
            raise serializers.ValidationError('Use digits, spaces, +, parentheses, dots or hyphens.')
        return value


def settings_response(record):
    return {**OrganisationSettingsSerializer(record).data,
            'financial_policy': {'currency': CURRENCY_CODE, 'currency_name': CURRENCY_NAME,
                                 'currency_symbol': CURRENCY_SYMBOL, 'commission_rate': str(COMMISSION_RATE)},
            'system_information': {'application': 'Treasureland Investment Management System', 'settings_version': 1}}


class OrganisationSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get(self, request):
        return Response(settings_response(current_settings()))

    @transaction.atomic
    def patch(self, request):
        # Validate before creating even the singleton. The database constraint and
        # get_or_create handle concurrent first writers; the row lock serializes edits.
        serializer = OrganisationSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        OrganisationSettings.objects.get_or_create(pk=1)
        record = OrganisationSettings.objects.select_for_update().get(pk=1)
        changed = sorted(key for key, value in serializer.validated_data.items() if getattr(record, key) != value)
        for key in changed:
            setattr(record, key, serializer.validated_data[key])
        if changed:
            record.save(update_fields=changed)
            AuditLog.objects.create(user=request.user, action='ORGANISATION_SETTINGS_UPDATED',
                                    model_name='OrganisationSettings', object_id='1',
                                    new_values={'changed_fields': changed, 'actor_id': request.user.pk})
        return Response(settings_response(record))


def receipt_presentation(record, generated_at):
    """Only presentation is dynamic. All supplied transaction values remain snapshots."""
    formats = {'DD/MM/YYYY': '%d/%m/%Y', 'MM/DD/YYYY': '%m/%d/%Y', 'YYYY-MM-DD': '%Y-%m-%d'}
    return {
        'name': escape(record.display_name), 'address': escape(record.address).replace('\n', '<br/>'),
        'contact': escape(' / '.join(filter(None, [record.telephone, record.contact_email]))),
        'heading': escape(record.receipt_heading), 'footer': escape(record.receipt_footer).replace('\n', '<br/>'),
        'generated_at': generated_at.astimezone(ZoneInfo(record.timezone)).strftime(formats[record.date_format] + ' %H:%M:%S %Z'),
    }
