from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    ACCOUNTANT = "ACCOUNTANT", "Accountant"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.ACCOUNTANT)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.ACCOUNTANT)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["email"]
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self):
        return self.email

    @property
    def is_super_admin(self):
        return self.role == UserRole.SUPER_ADMIN


class Agency(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=40, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "name"])]

    def __str__(self):
        return self.name


class UserAgencyAssignment(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agency_assignments")
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="user_assignments")
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)
    can_view_history = models.BooleanField(default=False)
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_agency_permissions",
    )

    class Meta:
        ordering = ["agency__name", "user__email"]
        constraints = [
            models.UniqueConstraint(fields=["user", "agency"], name="unique_user_agency_assignment")
        ]
        indexes = [models.Index(fields=["user", "agency"])]

    def clean(self):
        if self.user_id and self.user.role != UserRole.ACCOUNTANT:
            raise ValidationError({"user": "Only accountants should receive agency assignments."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} -> {self.agency.name}"


class AgentType(models.TextChoices):
    MAIN_AGENT = "MAIN_AGENT", "Main Agent"
    SUBAGENT = "SUBAGENT", "Subagent"


class Person(TimeStampedModel):
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="people")
    full_name = models.CharField(max_length=255)
    agent_type = models.CharField(max_length=20, choices=AgentType.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["agency", "full_name"]),
            models.Index(fields=["agent_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.agency.name})"


class TPMCode(TimeStampedModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="tpm_codes")
    code = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code", "is_active"]),
            models.Index(fields=["person", "is_active"]),
        ]

    @property
    def agency(self):
        return self.person.agency

    def __str__(self):
        return self.code


class Game(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "name"])]

    def __str__(self):
        return self.name


class Weekday(models.IntegerChoices):
    MONDAY = 1, "Monday"
    TUESDAY = 2, "Tuesday"
    WEDNESDAY = 3, "Wednesday"
    THURSDAY = 4, "Thursday"
    FRIDAY = 5, "Friday"
    SATURDAY = 6, "Saturday"
    SUNDAY = 7, "Sunday"


class WeeklyGameSchedule(TimeStampedModel):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="weekly_schedules")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    closing_time = models.TimeField()
    draw_time = models.TimeField()
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["weekday", "display_order", "closing_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "weekday"],
                condition=Q(is_active=True),
                name="unique_active_game_weekday_schedule",
            )
        ]
        indexes = [
            models.Index(fields=["weekday", "is_active"]),
            models.Index(fields=["game", "weekday"]),
        ]

    def clean(self):
        if self.draw_time <= self.closing_time:
            raise ValidationError({"draw_time": "Draw time must be later than closing time."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.game.name} - {self.get_weekday_display()}"


MONEY_PLACES = Decimal("0.01")
COMMISSION_RATE = Decimal("0.05")
TO_PAY_RATE = Decimal("0.95")
SUBAGENT_RATE = Decimal("0.02")
ORGANISATION_SUBAGENT_RATE = Decimal("0.03")


def money(value):
    if value is None:
        value = Decimal("0")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def json_safe_value(value):
    if isinstance(value, Decimal):
        return str(money(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class DailySheetStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    RETURNED = "RETURNED", "Returned"
    REOPENED = "REOPENED", "Reopened"


class VarianceStatus(models.TextChoices):
    BALANCED = "BALANCED", "Balanced"
    SHORTFALL = "SHORTFALL", "Shortfall"
    EXCESS = "EXCESS", "Excess"


class AuditAction(models.TextChoices):
    SHEET_CREATED = "SHEET_CREATED", "Sheet created"
    TRANSACTION_CREATED = "TRANSACTION_CREATED", "Transaction created"
    TRANSACTION_UPDATED = "TRANSACTION_UPDATED", "Transaction updated"
    TRANSACTION_DELETED = "TRANSACTION_DELETED", "Transaction deleted"
    OMITTED_TERMINAL_RECORDED = "OMITTED_TERMINAL_RECORDED", "Omitted terminal recorded"
    OMITTED_TERMINAL_REMOVED = "OMITTED_TERMINAL_REMOVED", "Omitted terminal removed"
    SHEET_SUBMITTED = "SHEET_SUBMITTED", "Sheet submitted"
    SHEET_RETURNED = "SHEET_RETURNED", "Sheet returned"
    SHEET_APPROVED = "SHEET_APPROVED", "Sheet approved"
    SHEET_REOPENED = "SHEET_REOPENED", "Sheet reopened"
    INCOMING_FUNDS_CHANGED = "INCOMING_FUNDS_CHANGED", "Incoming funds changed"
    TAX_CHANGED = "TAX_CHANGED", "Tax changed"


class DailySheet(TimeStampedModel):
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="daily_sheets")
    transaction_date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=DailySheetStatus.choices, default=DailySheetStatus.DRAFT)
    incoming_funds = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    tax = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    reconciliation_note = models.TextField(blank=True)
    return_comment = models.TextField(blank=True)
    reopen_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_daily_sheets")
    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="submitted_daily_sheets")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_daily_sheets")
    approved_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="returned_daily_sheets")
    returned_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="reopened_daily_sheets")
    reopened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-transaction_date", "agency__name"]
        constraints = [
            models.UniqueConstraint(fields=["agency", "transaction_date"], name="unique_daily_sheet_agency_date"),
            models.CheckConstraint(condition=Q(incoming_funds__gte=0) | Q(incoming_funds__isnull=True), name="daily_sheet_incoming_funds_non_negative"),
            models.CheckConstraint(condition=Q(tax__gte=0) | Q(tax__isnull=True), name="daily_sheet_tax_non_negative"),
        ]
        indexes = [
            models.Index(fields=["agency", "transaction_date"]),
            models.Index(fields=["status", "transaction_date"]),
            models.Index(fields=["created_by", "transaction_date"]),
        ]

    def clean(self):
        if self.agency_id and not self.agency.is_active:
            raise ValidationError({"agency": "Daily sheet must belong to an active agency."})
        if self.incoming_funds is not None and self.incoming_funds < 0:
            raise ValidationError({"incoming_funds": "Incoming funds cannot be negative."})
        if self.tax is not None and self.tax < 0:
            raise ValidationError({"tax": "Tax cannot be negative."})

    def save(self, *args, **kwargs):
        if self.incoming_funds is not None:
            self.incoming_funds = money(self.incoming_funds)
        if self.tax is not None:
            self.tax = money(self.tax)
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_accountant_editable(self):
        return self.status in {DailySheetStatus.DRAFT, DailySheetStatus.RETURNED, DailySheetStatus.REOPENED}

    def copy_weekday_games(self):
        schedules = WeeklyGameSchedule.objects.select_related("game").filter(
            weekday=self.transaction_date.isoweekday(),
            is_active=True,
            game__is_active=True,
        ).order_by("display_order", "closing_time", "id")
        DailySheetGame.objects.bulk_create(
            [
                DailySheetGame(
                    daily_sheet=self,
                    game=schedule.game,
                    game_name_snapshot=schedule.game.name,
                    closing_time_snapshot=schedule.closing_time,
                    draw_time_snapshot=schedule.draw_time,
                    display_order=schedule.display_order,
                )
                for schedule in schedules
            ],
            ignore_conflicts=True,
        )

    def totals(self):
        sales = (
            TransactionGameSale.objects.filter(transaction__daily_sheet=self)
            .values("transaction_id", "transaction__tpm_code__person_id", "transaction__agent_type_snapshot")
            .annotate(net=Sum("amount"))
        )
        gross_sales = money(sum((row["net"] or Decimal("0")) for row in sales))
        total_to_pay = money(gross_sales * TO_PAY_RATE)
        commission = money(gross_sales * COMMISSION_RATE)
        subagent_sales = money(
            sum((row["net"] or Decimal("0")) for row in sales if row["transaction__agent_type_snapshot"] == AgentType.SUBAGENT)
        )
        incoming = money(self.incoming_funds)
        tax = money(self.tax)
        commission_minus_tax = money(commission - tax)
        variance = money(incoming - total_to_pay)
        if variance == 0:
            variance_status = VarianceStatus.BALANCED
        elif variance < 0:
            variance_status = VarianceStatus.SHORTFALL
        else:
            variance_status = VarianceStatus.EXCESS
        return {
            "gross_sales": gross_sales,
            "total_to_pay": total_to_pay,
            "commission": commission,
            "subagent_sales": subagent_sales,
            "subagent_share": money(subagent_sales * SUBAGENT_RATE),
            "organisation_share_on_subagent_sales": money(subagent_sales * ORGANISATION_SUBAGENT_RATE),
            "commission_minus_tax": commission_minus_tax,
            "premier_office_payment": money(incoming - commission_minus_tax),
            "variance": variance,
            "variance_status": variance_status,
        }

    def __str__(self):
        return f"{self.agency.name} - {self.transaction_date}"


class DailySheetGame(models.Model):
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.CASCADE, related_name="sheet_games")
    game = models.ForeignKey(Game, on_delete=models.PROTECT, related_name="daily_sheet_games")
    game_name_snapshot = models.CharField(max_length=120)
    closing_time_snapshot = models.TimeField()
    draw_time_snapshot = models.TimeField()
    display_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["daily_sheet", "display_order", "closing_time_snapshot", "id"]
        constraints = [
            models.UniqueConstraint(fields=["daily_sheet", "game"], name="unique_daily_sheet_game"),
        ]
        indexes = [
            models.Index(fields=["daily_sheet", "display_order"]),
        ]

    def __str__(self):
        return f"{self.daily_sheet} - {self.game_name_snapshot}"


class TPMDailyTransaction(TimeStampedModel):
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.CASCADE, related_name="transactions")
    tpm_code = models.ForeignKey(TPMCode, on_delete=models.PROTECT, related_name="daily_transactions")
    person_name_snapshot = models.CharField(max_length=255)
    agent_type_snapshot = models.CharField(max_length=20, choices=AgentType.choices)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_tpm_transactions")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="updated_tpm_transactions")

    class Meta:
        ordering = ["person_name_snapshot", "tpm_code__code"]
        constraints = [
            models.UniqueConstraint(fields=["daily_sheet", "tpm_code"], name="unique_tpm_transaction_per_sheet"),
        ]
        indexes = [
            models.Index(fields=["daily_sheet", "tpm_code"]),
            models.Index(fields=["daily_sheet", "agent_type_snapshot"]),
        ]

    def clean(self):
        errors = {}
        if self.tpm_code_id:
            if not self.tpm_code.is_active:
                errors["tpm_code"] = "TPM code must be active."
            if not self.tpm_code.person.is_active:
                errors["tpm_code"] = "TPM code person must be active."
        if self.daily_sheet_id and self.tpm_code_id and self.tpm_code.person.agency_id != self.daily_sheet.agency_id:
            errors["tpm_code"] = "TPM code must belong to the DailySheet agency."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.tpm_code_id:
            self.person_name_snapshot = self.tpm_code.person.full_name
            self.agent_type_snapshot = self.tpm_code.person.agent_type
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def net_sales(self):
        aggregate = self.sales.aggregate(total=Sum("amount"))
        return money(aggregate["total"])

    @property
    def commission(self):
        return money(self.net_sales * COMMISSION_RATE)

    @property
    def to_pay(self):
        return money(self.net_sales * TO_PAY_RATE)

    def __str__(self):
        return f"{self.tpm_code.code} - {self.daily_sheet}"


class TransactionGameSale(TimeStampedModel):
    transaction = models.ForeignKey(TPMDailyTransaction, on_delete=models.CASCADE, related_name="sales")
    daily_sheet_game = models.ForeignKey(DailySheetGame, on_delete=models.PROTECT, related_name="transaction_sales")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["daily_sheet_game__display_order", "daily_sheet_game__id"]
        constraints = [
            models.UniqueConstraint(fields=["transaction", "daily_sheet_game"], name="unique_transaction_game_sale"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="transaction_game_sale_amount_non_negative"),
        ]
        indexes = [
            models.Index(fields=["transaction", "daily_sheet_game"]),
        ]

    def clean(self):
        if self.amount is not None and self.amount < 0:
            raise ValidationError({"amount": "Sale amount cannot be negative."})
        if self.transaction_id and self.daily_sheet_game_id and self.daily_sheet_game.daily_sheet_id != self.transaction.daily_sheet_id:
            raise ValidationError({"daily_sheet_game": "DailySheetGame must belong to the same DailySheet as the transaction."})

    def save(self, *args, **kwargs):
        self.amount = money(self.amount)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction} - {self.daily_sheet_game.game_name_snapshot}: {self.amount}"


class OmittedTerminal(TimeStampedModel):
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.CASCADE, related_name="omitted_terminals")
    tpm_code = models.ForeignKey(TPMCode, on_delete=models.PROTECT, related_name="omissions")
    reason = models.TextField()
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recorded_terminal_omissions")

    class Meta:
        ordering = ["tpm_code__code"]
        constraints = [
            models.UniqueConstraint(fields=["daily_sheet", "tpm_code"], name="unique_omitted_terminal_per_sheet"),
        ]
        indexes = [
            models.Index(fields=["daily_sheet", "tpm_code"]),
        ]

    def clean(self):
        errors = {}
        if self.tpm_code_id:
            if not self.tpm_code.is_active or not self.tpm_code.person.is_active:
                errors["tpm_code"] = "Only active TPM codes for active people may be omitted."
        if self.daily_sheet_id and self.tpm_code_id:
            if self.tpm_code.person.agency_id != self.daily_sheet.agency_id:
                errors["tpm_code"] = "TPM code must belong to the DailySheet agency."
            if TPMDailyTransaction.objects.filter(daily_sheet=self.daily_sheet, tpm_code=self.tpm_code).exists():
                errors["tpm_code"] = "TPM code cannot be both entered and omitted on the same sheet."
        if not self.reason.strip():
            errors["reason"] = "Reason is required."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tpm_code.code} omitted from {self.daily_sheet}"


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="audit_logs")
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="audit_logs", null=True, blank=True)
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.CASCADE, related_name="audit_logs", null=True, blank=True)
    action = models.CharField(max_length=40, choices=AuditAction.choices)
    model_name = models.CharField(max_length=120)
    object_id = models.CharField(max_length=80)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["agency", "created_at"]),
            models.Index(fields=["daily_sheet", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Audit logs are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit logs are immutable.")

    def __str__(self):
        return f"{self.action} by {self.user} at {self.created_at}"
