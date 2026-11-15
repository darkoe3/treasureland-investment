import csv
import re
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Q
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from .models import AuditLog, User
from .permissions import IsSuperAdmin
from .serializers import AgencyBriefSerializer


def safe_metadata(value):
    # An allowlist deliberately excludes arbitrary legacy strings and nested payloads.
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key in {'actor_id', 'agency_id', 'payer_id', 'obligation_id', 'game_id', 'sub_agent_number_id', 'holiday_override_id', 'daily_sheet_id'} and (item is None or type(item) is int):
            result[key] = item
        elif key in {'is_active', 'can_create', 'can_edit', 'can_delete', 'can_export', 'can_view_history'} and type(item) is bool:
            result[key] = item
        elif key == 'changed_fields' and isinstance(item, list):
            result[key] = [field for field in item if field in {'full_name', 'password', 'role', 'is_active', 'agency_assignments', 'display_name', 'address', 'telephone', 'contact_email', 'receipt_heading', 'receipt_footer', 'timezone', 'date_format'}]
    return result


def record_event(user, action, fields=()):
    AuditLog.objects.create(user=user, action=action, model_name='User', object_id=str(user.pk), new_values={'changed_fields': list(fields)})


class SafeAuditSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source='user.full_name')
    actor_role = serializers.CharField(source='user.role')
    agency_name = serializers.CharField(source='agency.name', default=None)
    action_label = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    metadata = serializers.SerializerMethodField()
    object_id = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ('id', 'created_at', 'user', 'actor', 'actor_role', 'agency', 'agency_name', 'action', 'action_label', 'model_name', 'object_id', 'result', 'description', 'metadata')
        read_only_fields = fields

    def get_action_label(self, obj):
        return obj.action.replace('_', ' ').capitalize()

    def get_description(self, obj):
        # Legacy descriptions include personal data, comments and exception text.
        return self.get_action_label(obj)

    def get_result(self, obj):
        return 'FAILED' if obj.action.endswith('_FAILED') else 'SUCCESS'

    def get_object_id(self, obj):
        return obj.object_id if re.fullmatch(r'[0-9]+', obj.object_id) else '[redacted]'

    def get_metadata(self, obj):
        return {'before': safe_metadata(obj.old_values), 'after': safe_metadata(obj.new_values)}


class AuditPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class AuditFilters(serializers.Serializer):
    search = serializers.CharField(required=False, max_length=200)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    user = serializers.IntegerField(required=False, min_value=1)
    agency = serializers.IntegerField(required=False, min_value=1)
    daily_sheet = serializers.IntegerField(required=False, min_value=1)
    role = serializers.ChoiceField(required=False, choices=['SUPER_ADMIN', 'ACCOUNTANT'])
    model_name = serializers.CharField(required=False, max_length=120)
    action = serializers.CharField(required=False, max_length=40)
    result = serializers.ChoiceField(required=False, choices=['SUCCESS', 'FAILED'])

    def validate(self, data):
        if data.get('date_from') and data.get('date_to') and data['date_from'] > data['date_to']:
            raise serializers.ValidationError({'date_to': 'Must be on or after date from.'})
        return data


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SafeAuditSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    pagination_class = AuditPagination
    filter_backends = []

    def get_queryset(self):
        validator = AuditFilters(data=self.request.query_params)
        validator.is_valid(raise_exception=True)
        filters = validator.validated_data
        qs = AuditLog.objects.select_related('user', 'agency').order_by('-created_at', '-id')
        for param, field in [('user', 'user_id'), ('agency', 'agency_id'), ('daily_sheet', 'daily_sheet_id'), ('role', 'user__role'), ('model_name', 'model_name'), ('action', 'action')]:
            if param in filters:
                qs = qs.filter(**{field: filters[param]})
        if 'date_from' in filters:
            qs = qs.filter(created_at__date__gte=filters['date_from'])
        if 'date_to' in filters:
            qs = qs.filter(created_at__date__lte=filters['date_to'])
        if 'search' in filters:
            term = filters['search']
            qs = qs.filter(Q(user__full_name__icontains=term) | Q(object_id__icontains=term) | Q(action__icontains=term.replace(" ", "_")) | Q(model_name__icontains=term))
        if filters.get('result') == 'FAILED':
            qs = qs.filter(action__endswith='_FAILED')
        elif filters.get('result') == 'SUCCESS':
            qs = qs.exclude(action__endswith='_FAILED')
        return qs

    @action(detail=False, methods=['get'], url_path='export')
    def export_csv(self, request):
        qs = self.get_queryset()
        if qs.count() > 10000:
            raise serializers.ValidationError({'detail': 'Export limit is 10,000 events. Narrow your filters.'})
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="audit-log.csv"'
        response['Cache-Control'] = 'no-store'
        writer = csv.writer(response)
        columns = ['created_at', 'actor', 'actor_role', 'action_label', 'model_name', 'agency_name', 'object_id', 'result', 'description']
        writer.writerow(columns)
        for obj in qs[:10000].iterator(chunk_size=500):
            data = self.get_serializer(obj).data
            # Neutralize spreadsheet formula injection, including whitespace prefixes.
            writer.writerow([("'" + str(data[key])) if str(data[key] or '').lstrip().startswith(('=', '+', '-', '@')) else data[key] for key in columns])
        return response


class ProfileSerializer(serializers.ModelSerializer):
    agencies = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'full_name', 'email', 'role', 'is_active', 'last_login', 'agencies')
        read_only_fields = ('id', 'email', 'role', 'is_active', 'last_login', 'agencies')

    def get_agencies(self, user):
        return AgencyBriefSerializer([a.agency for a in user.agency_assignments.select_related('agency')], many=True).data

    def validate(self, attrs):
        forbidden = set(self.initial_data) - {'full_name'}
        if forbidden:
            raise serializers.ValidationError({key: 'This field cannot be edited here.' for key in forbidden})
        return attrs

    def validate_full_name(self, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise serializers.ValidationError('Enter a valid display name.')
        return value.strip()


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(ProfileSerializer(request.user).data)

    @transaction.atomic
    def patch(self, request):
        user = User.objects.select_for_update().get(pk=request.user.pk)
        serializer = ProfileSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = [key for key, value in serializer.validated_data.items() if getattr(user, key) != value]
        serializer.save()
        if changed:
            record_event(user, 'PROFILE_UPDATED', changed)
        return Response(serializer.data)


class PasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(trim_whitespace=False, write_only=True)
    confirm_password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate(self, data):
        user = self.context['user']
        if not user.check_password(data['current_password']):
            raise serializers.ValidationError({'current_password': 'Current password is incorrect.'})
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return data


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    @transaction.atomic
    def post(self, request):
        user = User.objects.select_for_update().get(pk=request.user.pk)
        serializer = PasswordSerializer(data=request.data, context={'user': user})
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['new_password']
        try:
            validate_password(new_password, user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'new_password': error.messages})
        user.set_password(new_password)
        user.save(update_fields=['password', 'updated_at'])
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)
        record_event(user, 'PASSWORD_CHANGED', ['password'])
        return Response({'detail': 'Password changed. Please sign in again.', 'reauthenticate': True})
