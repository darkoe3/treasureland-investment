from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    AgentType,
    Agency,
    AuditLog,
    DailySheet,
    DailySheetGame,
    DailySheetStatus,
    Game,
    OmittedTerminal,
    Person,
    TPMCode,
    TPMDailyTransaction,
    TransactionGameSale,
    User,
    UserAgencyAssignment,
    UserRole,
    WeeklyGameSchedule,
    money,
)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_active", "is_staff", "created_at", "updated_at")
        read_only_fields = fields


class AgencyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agency
        fields = ("id", "name", "code")
        read_only_fields = fields


class UserAgencyProfileSerializer(serializers.ModelSerializer):
    agency = AgencyBriefSerializer(read_only=True)

    class Meta:
        model = UserAgencyAssignment
        fields = ("agency", "can_create", "can_edit", "can_delete", "can_export", "can_view_history")
        read_only_fields = fields


class CurrentUserSerializer(serializers.ModelSerializer):
    agency_assignments = serializers.SerializerMethodField()
    active_agencies = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_active", "agency_assignments", "active_agencies")
        read_only_fields = fields

    def get_agency_assignments(self, user):
        if user.role != UserRole.ACCOUNTANT:
            return []
        assignments = user.agency_assignments.select_related("agency").filter(agency__is_active=True)
        return UserAgencyProfileSerializer(assignments, many=True).data

    def get_active_agencies(self, user):
        if user.role != UserRole.SUPER_ADMIN:
            return []
        return AgencyBriefSerializer(Agency.objects.filter(is_active=True).order_by("name"), many=True).data


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )
        if not user:
            raise serializers.ValidationError("No active account found with the given credentials.")
        if not user.is_active:
            raise serializers.ValidationError("This account is inactive.")

        refresh = self.get_token(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": CurrentUserSerializer(user).data,
        }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = user.role
        return token


class AgencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Agency
        fields = ("id", "name", "code", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")


class UserAgencyAssignmentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    agency_name = serializers.CharField(source="agency.name", read_only=True)
    assigned_by_email = serializers.EmailField(source="assigned_by.email", read_only=True)

    class Meta:
        model = UserAgencyAssignment
        fields = (
            "id",
            "user",
            "user_email",
            "agency",
            "agency_name",
            "can_create",
            "can_edit",
            "can_delete",
            "can_export",
            "can_view_history",
            "assigned_by",
            "assigned_by_email",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("assigned_by", "created_at", "updated_at")

    def validate_user(self, user):
        if user.role != UserRole.ACCOUNTANT:
            raise serializers.ValidationError("Only accountants can be assigned to agencies.")
        return user


class AccountantAssignmentInputSerializer(serializers.Serializer):
    agency = serializers.PrimaryKeyRelatedField(queryset=Agency.objects.filter(is_active=True))
    can_create = serializers.BooleanField(default=False)
    can_edit = serializers.BooleanField(default=False)
    can_delete = serializers.BooleanField(default=False)
    can_export = serializers.BooleanField(default=False)
    can_view_history = serializers.BooleanField(default=False)


class AccountantSerializer(serializers.ModelSerializer):
    agency_assignments = UserAgencyProfileSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_active", "agency_assignments", "created_at", "updated_at")
        read_only_fields = ("id", "role", "agency_assignments", "created_at", "updated_at")


class AccountantCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    agency_assignments = AccountantAssignmentInputSerializer(many=True, required=False)

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "password", "is_active", "agency_assignments")

    def validate_email(self, email):
        normalized = User.objects.normalize_email(email).lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized

    def validate_password(self, password):
        validate_password(password)
        return password

    def validate_agency_assignments(self, assignments):
        agency_ids = [item["agency"].id for item in assignments]
        if len(agency_ids) != len(set(agency_ids)):
            raise serializers.ValidationError("Duplicate agency assignments are not allowed.")
        return assignments

    @transaction.atomic
    def create(self, validated_data):
        assignments = validated_data.pop("agency_assignments", [])
        password = validated_data.pop("password")
        user = User(
            role=UserRole.ACCOUNTANT,
            is_staff=False,
            is_superuser=False,
            **validated_data,
        )
        user.set_password(password)
        user.save()
        assigned_by = self.context["request"].user
        UserAgencyAssignment.objects.bulk_create(
            [
                UserAgencyAssignment(
                    user=user,
                    agency=item["agency"],
                    can_create=item["can_create"],
                    can_edit=item["can_edit"],
                    can_delete=item["can_delete"],
                    can_export=item["can_export"],
                    can_view_history=item["can_view_history"],
                    assigned_by=assigned_by,
                )
                for item in assignments
            ]
        )
        return user


class AccountantUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("email", "full_name", "is_active")

    def validate_email(self, email):
        normalized = User.objects.normalize_email(email).lower()
        queryset = User.objects.filter(email__iexact=normalized)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized


class AccountantSetAgenciesSerializer(serializers.Serializer):
    agency_assignments = AccountantAssignmentInputSerializer(many=True)

    def validate_agency_assignments(self, assignments):
        agency_ids = [item["agency"].id for item in assignments]
        if len(agency_ids) != len(set(agency_ids)):
            raise serializers.ValidationError("Duplicate agency assignments are not allowed.")
        return assignments


class AccountantPasswordResetSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, password):
        validate_password(password)
        return password


class PersonSerializer(serializers.ModelSerializer):
    agency_name = serializers.CharField(source="agency.name", read_only=True)
    tpm_codes = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ("id", "agency", "agency_name", "full_name", "agent_type", "is_active", "tpm_codes", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")

    def get_tpm_codes(self, obj):
        return [
            {"id": code.id, "code": code.code, "is_active": code.is_active}
            for code in obj.tpm_codes.all().order_by("code")
        ]


class TPMCodeSerializer(serializers.ModelSerializer):
    person_name = serializers.CharField(source="person.full_name", read_only=True)
    agency = serializers.IntegerField(source="person.agency_id", read_only=True)
    agency_name = serializers.CharField(source="person.agency.name", read_only=True)

    class Meta:
        model = TPMCode
        fields = ("id", "person", "person_name", "agency", "agency_name", "code", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")

    def validate_code(self, code):
        queryset = TPMCode.objects.filter(code__iexact=code.strip())
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A TPM code with this value already exists.")
        return code.strip()


class GameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = ("id", "name", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")


class WeeklyGameScheduleSerializer(serializers.ModelSerializer):
    game_name = serializers.CharField(source="game.name", read_only=True)
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = WeeklyGameSchedule
        fields = (
            "id",
            "game",
            "game_name",
            "weekday",
            "weekday_display",
            "closing_time",
            "draw_time",
            "display_order",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class DailySheetGameSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySheetGame
        fields = (
            "id",
            "daily_sheet",
            "game",
            "game_name_snapshot",
            "closing_time_snapshot",
            "draw_time_snapshot",
            "display_order",
            "created_at",
        )
        read_only_fields = fields


class TransactionGameSaleSerializer(serializers.ModelSerializer):
    game_name = serializers.CharField(source="daily_sheet_game.game_name_snapshot", read_only=True)

    class Meta:
        model = TransactionGameSale
        fields = ("id", "transaction", "daily_sheet_game", "game_name", "amount", "created_at", "updated_at")
        read_only_fields = ("id", "transaction", "game_name", "created_at", "updated_at")

    def validate_amount(self, amount):
        if amount < 0:
            raise serializers.ValidationError("Sale amount cannot be negative.")
        return money(amount)


class TPMDailyTransactionSerializer(serializers.ModelSerializer):
    sales = TransactionGameSaleSerializer(many=True)
    tpm_code_value = serializers.CharField(source="tpm_code.code", read_only=True)
    net_sales = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    commission = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    to_pay = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    person_total = serializers.SerializerMethodField()

    class Meta:
        model = TPMDailyTransaction
        fields = (
            "id",
            "daily_sheet",
            "tpm_code",
            "tpm_code_value",
            "person_name_snapshot",
            "agent_type_snapshot",
            "sales",
            "net_sales",
            "commission",
            "to_pay",
            "person_total",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "person_name_snapshot",
            "agent_type_snapshot",
            "net_sales",
            "commission",
            "to_pay",
            "person_total",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )

    def get_person_total(self, obj):
        tpm_ids = TPMCode.objects.filter(person_id=obj.tpm_code.person_id).values("id")
        total = TransactionGameSale.objects.filter(
            transaction__daily_sheet=obj.daily_sheet,
            transaction__tpm_code_id__in=tpm_ids,
        ).aggregate(total=Sum("amount"))["total"]
        return money(money(total) * Decimal("0.95"))

    def validate(self, attrs):
        request = self.context.get("request")
        sales = attrs.get("sales")
        instance = getattr(self, "instance", None)
        daily_sheet = attrs.get("daily_sheet") or (instance.daily_sheet if instance else None)
        tpm_code = attrs.get("tpm_code") or (instance.tpm_code if instance else None)
        if daily_sheet and tpm_code:
            if not tpm_code.is_active or not tpm_code.person.is_active:
                raise serializers.ValidationError({"tpm_code": "TPM code and person must be active."})
            if tpm_code.person.agency_id != daily_sheet.agency_id:
                raise serializers.ValidationError({"tpm_code": "TPM code must belong to the DailySheet agency."})
            if OmittedTerminal.objects.filter(daily_sheet=daily_sheet, tpm_code=tpm_code).exists():
                raise serializers.ValidationError({"tpm_code": "TPM code cannot be both entered and omitted."})
        if sales is None:
            raise serializers.ValidationError({"sales": "Sales are required."})
        game_ids = [sale["daily_sheet_game"].id for sale in sales]
        if len(game_ids) != len(set(game_ids)):
            raise serializers.ValidationError({"sales": "Duplicate sales entries for the same game are not allowed."})
        if daily_sheet:
            expected_ids = set(daily_sheet.sheet_games.values_list("id", flat=True))
            if set(game_ids) != expected_ids:
                raise serializers.ValidationError({"sales": "Provide exactly one sale entry for every game on the sheet."})
        if daily_sheet and not daily_sheet.is_accountant_editable:
            raise serializers.ValidationError("This sheet is locked against changes.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        sales_data = validated_data.pop("sales")
        transaction_obj = TPMDailyTransaction.objects.create(
            **validated_data,
            created_by=request.user,
            updated_by=request.user,
        )
        TransactionGameSale.objects.bulk_create(
            [
                TransactionGameSale(
                    transaction=transaction_obj,
                    daily_sheet_game=sale["daily_sheet_game"],
                    amount=money(sale["amount"]),
                )
                for sale in sales_data
            ]
        )
        return transaction_obj

    @transaction.atomic
    def update(self, instance, validated_data):
        request = self.context["request"]
        sales_data = validated_data.pop("sales")
        instance.tpm_code = validated_data.get("tpm_code", instance.tpm_code)
        instance.updated_by = request.user
        instance.save()
        TransactionGameSale.objects.filter(transaction=instance).delete()
        TransactionGameSale.objects.bulk_create(
            [
                TransactionGameSale(
                    transaction=instance,
                    daily_sheet_game=sale["daily_sheet_game"],
                    amount=money(sale["amount"]),
                )
                for sale in sales_data
            ]
        )
        return instance


class OmittedTerminalSerializer(serializers.ModelSerializer):
    tpm_code_value = serializers.CharField(source="tpm_code.code", read_only=True)
    person_name = serializers.CharField(source="tpm_code.person.full_name", read_only=True)

    class Meta:
        model = OmittedTerminal
        fields = ("id", "daily_sheet", "tpm_code", "tpm_code_value", "person_name", "reason", "recorded_by", "is_active", "created_at", "updated_at")
        read_only_fields = ("recorded_by", "created_at", "updated_at")

    def validate(self, attrs):
        daily_sheet = attrs.get("daily_sheet") or getattr(self.instance, "daily_sheet", None)
        tpm_code = attrs.get("tpm_code") or getattr(self.instance, "tpm_code", None)
        if tpm_code and (not tpm_code.is_active or not tpm_code.person.is_active):
            raise serializers.ValidationError({"tpm_code": "Only active TPM codes for active people may be omitted."})
        if daily_sheet and tpm_code:
            if tpm_code.person.agency_id != daily_sheet.agency_id:
                raise serializers.ValidationError({"tpm_code": "TPM code must belong to the DailySheet agency."})
            if attrs.get("is_active", getattr(self.instance, "is_active", True)) and TPMDailyTransaction.objects.filter(daily_sheet=daily_sheet, tpm_code=tpm_code).exists():
                raise serializers.ValidationError({"tpm_code": "TPM code cannot be both entered and omitted."})
        if not (attrs.get("reason") or getattr(self.instance, "reason", "")).strip():
            raise serializers.ValidationError({"reason": "Reason is required."})
        return attrs


class DailySheetSerializer(serializers.ModelSerializer):
    agency_name = serializers.CharField(source="agency.name", read_only=True)
    sheet_games = DailySheetGameSerializer(many=True, read_only=True)
    gross_sales = serializers.SerializerMethodField()
    total_to_pay = serializers.SerializerMethodField()
    commission = serializers.SerializerMethodField()
    subagent_sales = serializers.SerializerMethodField()
    subagent_share = serializers.SerializerMethodField()
    organisation_share_on_subagent_sales = serializers.SerializerMethodField()
    manual_tax = serializers.SerializerMethodField()
    variance = serializers.SerializerMethodField()
    variance_status = serializers.SerializerMethodField()
    zero_sales_count = serializers.SerializerMethodField()
    total_terminals = serializers.SerializerMethodField()
    entered_terminals = serializers.SerializerMethodField()
    omitted_terminals = serializers.SerializerMethodField()
    game_totals = serializers.SerializerMethodField()
    person_totals = serializers.SerializerMethodField()

    class Meta:
        model = DailySheet
        fields = (
            "id",
            "agency",
            "agency_name",
            "transaction_date",
            "status",
            "incoming_funds",
            "tax",
            "reconciliation_note",
            "return_comment",
            "reopen_reason",
            "created_by",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "returned_by",
            "returned_at",
            "reopened_by",
            "reopened_at",
            "created_at",
            "updated_at",
            "sheet_games",
            "gross_sales",
            "total_to_pay",
            "commission",
            "subagent_sales",
            "subagent_share",
            "organisation_share_on_subagent_sales",
            "manual_tax",
            "variance",
            "variance_status",
            "zero_sales_count",
            "total_terminals",
            "entered_terminals",
            "omitted_terminals",
            "game_totals",
            "person_totals",
        )
        read_only_fields = (
            "status",
            "return_comment",
            "reopen_reason",
            "created_by",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "returned_by",
            "returned_at",
            "reopened_by",
            "reopened_at",
            "created_at",
            "updated_at",
            "sheet_games",
        )

    def _totals(self, obj):
        return obj.totals()

    def get_gross_sales(self, obj):
        return self._totals(obj)["gross_sales"]

    def get_total_to_pay(self, obj):
        return self._totals(obj)["total_to_pay"]

    def get_commission(self, obj):
        return self._totals(obj)["commission"]

    def get_subagent_sales(self, obj):
        return self._totals(obj)["subagent_sales"]

    def get_subagent_share(self, obj):
        return self._totals(obj)["subagent_share"]

    def get_organisation_share_on_subagent_sales(self, obj):
        return self._totals(obj)["organisation_share_on_subagent_sales"]

    def get_manual_tax(self, obj):
        return self._totals(obj)["tax"]

    def get_variance(self, obj):
        return self._totals(obj)["variance"]

    def get_variance_status(self, obj):
        return self._totals(obj)["variance_status"]

    def _active_tpm_queryset(self, obj):
        return TPMCode.objects.select_related("person").filter(person__agency=obj.agency, person__is_active=True, is_active=True)

    def get_zero_sales_count(self, obj):
        rows = obj.transactions.annotate(net=Sum("sales__amount")).filter(net=0)
        return rows.count()

    def get_total_terminals(self, obj):
        return self._active_tpm_queryset(obj).count()

    def get_entered_terminals(self, obj):
        return obj.transactions.filter(tpm_code__is_active=True, tpm_code__person__is_active=True).values("tpm_code").distinct().count()

    def get_omitted_terminals(self, obj):
        active_ids = set(self._active_tpm_queryset(obj).values_list("id", flat=True))
        entered_ids = set(obj.transactions.values_list("tpm_code_id", flat=True))
        explicit = {
            item.tpm_code_id: item
            for item in obj.omitted_terminals.select_related("tpm_code", "tpm_code__person").filter(is_active=True)
        }
        omitted_ids = sorted((active_ids - entered_ids) | set(explicit.keys()))
        items = []
        tpm_by_id = {tpm.id: tpm for tpm in self._active_tpm_queryset(obj).filter(id__in=omitted_ids)}
        for tpm_id in omitted_ids:
            tpm = tpm_by_id.get(tpm_id) or getattr(explicit.get(tpm_id), "tpm_code", None)
            if tpm:
                items.append({
                    "tpm_code": tpm.id,
                    "code": tpm.code,
                    "person_name": tpm.person.full_name,
                    "reason": getattr(explicit.get(tpm_id), "reason", ""),
                })
        return {"count": len(items), "items": items}

    def get_game_totals(self, obj):
        totals = {
            row["daily_sheet_game_id"]: money(row["total"])
            for row in TransactionGameSale.objects.filter(transaction__daily_sheet=obj)
            .values("daily_sheet_game_id")
            .annotate(total=Sum("amount"))
        }
        return [
            {
                "daily_sheet_game": game.id,
                "game_name": game.game_name_snapshot,
                "total": totals.get(game.id, money("0")),
            }
            for game in obj.sheet_games.all().order_by("display_order", "closing_time_snapshot", "id")
        ]

    def get_person_totals(self, obj):
        rows = (
            TransactionGameSale.objects.filter(transaction__daily_sheet=obj)
            .values("transaction__tpm_code__person_id", "transaction__person_name_snapshot")
            .annotate(net=Sum("amount"))
            .order_by("transaction__person_name_snapshot", "transaction__tpm_code__person_id")
        )
        return [
            {
                "person": row["transaction__tpm_code__person_id"],
                "person_name": row["transaction__person_name_snapshot"],
                "net_sales": money(row["net"]),
                "to_pay": money(money(row["net"] or 0) * Decimal("0.95")),
            }
            for row in rows
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        agency = attrs.get("agency") or getattr(self.instance, "agency", None)
        if agency and not agency.is_active:
            raise serializers.ValidationError({"agency": "Daily sheet must belong to an active agency."})
        if attrs.get("incoming_funds") is not None and attrs["incoming_funds"] < 0:
            raise serializers.ValidationError({"incoming_funds": "Incoming funds cannot be negative."})
        if attrs.get("tax") is not None and attrs["tax"] < 0:
            raise serializers.ValidationError({"tax": "Tax cannot be negative."})
        if self.instance and not self.instance.is_accountant_editable:
            raise serializers.ValidationError("This sheet is locked against changes.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        sheet = DailySheet.objects.create(**validated_data, created_by=request.user)
        sheet.copy_weekday_games()
        return sheet


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    agency_name = serializers.CharField(source="agency.name", read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "user",
            "user_email",
            "agency",
            "agency_name",
            "daily_sheet",
            "action",
            "model_name",
            "object_id",
            "old_values",
            "new_values",
            "description",
            "created_at",
        )
        read_only_fields = fields
