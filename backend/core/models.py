from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Lower
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
        validate_password(password, user)
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
        constraints = [
            models.UniqueConstraint(Lower("name"), name="agency_name_ci_unique"),
            models.UniqueConstraint(Lower("code"), name="agency_code_ci_unique"),
        ]
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

    def clean(self):
        if self.pk and Person.objects.filter(pk=self.pk).exclude(agency_id=self.agency_id).exists() and self.terminal_numbers.exists():
            raise ValidationError({"agency": "Reassign this person's terminal records before changing agency."})


class TPMCode(TimeStampedModel):
    """Compatibility name: this table stores Sub-Agent Numbers, not terminals."""
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="tpm_codes")
    code = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Sub-Agent Number"
        verbose_name_plural = "Sub-Agent Numbers"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(Lower("code"), name="unique_tpm_code_case_insensitive"),
        ]
        indexes = [
            models.Index(fields=["code", "is_active"]),
            models.Index(fields=["person", "is_active"]),
        ]

    @property
    def agency(self):
        return self.person.agency

    def __str__(self):
        return self.code

    def clean(self):
        if self.pk and TPMCode.objects.filter(pk=self.pk).exclude(person_id=self.person_id).exists() and self.terminal_numbers.exists():
            raise ValidationError({"person": "Reassign this Sub-Agent Number's terminal records before changing owner."})


class TerminalNumber(TimeStampedModel):
    terminal_number = models.CharField(max_length=80)
    sub_agent_number = models.ForeignKey(TPMCode, on_delete=models.PROTECT, related_name="terminal_numbers")
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="terminal_numbers")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="terminal_numbers")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_terminal_numbers")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="updated_terminal_numbers")
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="deactivated_terminal_numbers")

    class Meta:
        ordering = ["terminal_number", "id"]
        constraints = [
            models.UniqueConstraint(Lower("terminal_number"), name="terminal_number_ci_unique"),
            models.UniqueConstraint(fields=["sub_agent_number"], condition=Q(is_active=True), name="one_active_terminal_per_sub_agent"),
            models.CheckConstraint(condition=~Q(terminal_number=""), name="terminal_number_not_empty"),
        ]
        indexes = [models.Index(fields=["agency", "is_active"]), models.Index(fields=["person", "is_active"])]

    def clean(self):
        if not isinstance(self.terminal_number, str):
            raise ValidationError({"terminal_number": "Terminal Number must be text."})
        self.terminal_number = self.terminal_number.strip()
        if TerminalNumber.objects.filter(terminal_number__iexact=self.terminal_number).exclude(pk=self.pk).exists():
            raise ValidationError({"terminal_number": "This Terminal Number already exists. Use its existing record and Reassign when necessary."})
        if self.sub_agent_number_id:
            owner = self.sub_agent_number.person
            if self.person_id != owner.id or self.agency_id != owner.agency_id:
                raise ValidationError("Person and agency must match the selected Sub-Agent Number.")
            if self.is_active and (not self.sub_agent_number.is_active or not owner.is_active or not owner.agency.is_active):
                raise ValidationError("An active terminal requires an active Sub-Agent Number, person and agency.")
            if self.is_active and TerminalNumber.objects.filter(sub_agent_number_id=self.sub_agent_number_id, is_active=True).exclude(pk=self.pk).exists():
                raise ValidationError({"sub_agent_number": "This Sub-Agent Number already has an active terminal. Explicitly deactivate it before replacement."})

    def save(self, *args, **kwargs):
        self.clean()
        self.full_clean()
        super().save(*args, **kwargs)


class TerminalImportBatch(TimeStampedModel):
    uploader = models.ForeignKey(User, on_delete=models.PROTECT, related_name="terminal_import_batches")
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="terminal_import_batches")
    original_filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default="PREVIEWED", choices=[(s, s.title()) for s in ("PREVIEWED", "CONFIRMED", "CANCELLED")])
    preview_payload = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    errors = models.JSONField(default=list)
    expires_at = models.DateTimeField(db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    result_counts = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["uploader", "status"]), models.Index(fields=["agency", "created_at"])]


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
    is_whole_day = models.BooleanField(default=False)
    closing_time = models.TimeField(null=True, blank=True)
    draw_time = models.TimeField(null=True, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["weekday", "display_order", "id"]
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
        if self.is_whole_day:
            if self.closing_time is not None or self.draw_time is not None:
                raise ValidationError({"is_whole_day": "Whole Day schedules must not have closing or draw times."})
            return
        if self.closing_time is None or self.draw_time is None:
            raise ValidationError({"closing_time": "Timed schedules must include both closing and draw times."})
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
    AGENCY_CREATED = "AGENCY_CREATED", "Agency created"
    AGENCY_UPDATED = "AGENCY_UPDATED", "Agency updated"
    AGENCY_DEACTIVATED = "AGENCY_DEACTIVATED", "Agency deactivated"
    AGENCY_REACTIVATED = "AGENCY_REACTIVATED", "Agency reactivated"
    TERMINAL_CREATED = "TERMINAL_CREATED", "Terminal created"
    TERMINAL_EDITED = "TERMINAL_EDITED", "Terminal edited"
    TERMINAL_DEACTIVATED = "TERMINAL_DEACTIVATED", "Terminal deactivated"
    TERMINAL_REACTIVATED = "TERMINAL_REACTIVATED", "Terminal reactivated"
    TERMINAL_REASSIGNED = "TERMINAL_REASSIGNED", "Terminal reassigned"
    TERMINAL_IMPORT_PREVIEWED = "TERMINAL_IMPORT_PREVIEWED", "Terminal import previewed"
    TERMINAL_IMPORT_CONFIRMED = "TERMINAL_IMPORT_CONFIRMED", "Terminal import confirmed"
    TERMINAL_IMPORT_CANCELLED = "TERMINAL_IMPORT_CANCELLED", "Terminal import cancelled"
    DAILY_SHEET_RESET = "DAILY_SHEET_RESET", "Daily sheet reset"
    DAILY_SHEET_DELETED = "DAILY_SHEET_DELETED", "Daily sheet deleted"
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
    REPORT_PREVIEWED = "REPORT_PREVIEWED", "Report previewed"
    REPORT_EXPORTED = "REPORT_EXPORTED", "Report exported"
    SCHEDULE_CREATED = "SCHEDULE_CREATED", "Schedule created"
    SCHEDULE_UPDATED = "SCHEDULE_UPDATED", "Schedule updated"
    SCHEDULE_ACTIVATED = "SCHEDULE_ACTIVATED", "Schedule activated"
    SCHEDULE_DEACTIVATED = "SCHEDULE_DEACTIVATED", "Schedule deactivated"
    IMPORT_PREVIEWED = "IMPORT_PREVIEWED", "Import previewed"
    IMPORT_CONFIRMED = "IMPORT_CONFIRMED", "Import confirmed"
    IMPORT_CANCELLED = "IMPORT_CANCELLED", "Import cancelled"
    IMPORT_FAILED = "IMPORT_FAILED", "Import failed"
    PAYMENT_PAYER_CREATED = "PAYMENT_PAYER_CREATED", "Payment payer created"
    PAYMENT_PAYER_UPDATED = "PAYMENT_PAYER_UPDATED", "Payment payer updated"
    PAYMENT_PAYER_DEACTIVATED = "PAYMENT_PAYER_DEACTIVATED", "Payment payer deactivated"
    PAYMENT_PAYER_REACTIVATED = "PAYMENT_PAYER_REACTIVATED", "Payment payer reactivated"
    PAYER_SUBAGENT_ASSIGNED = "PAYER_SUBAGENT_ASSIGNED", "Sub-agent assigned"
    PAYER_SUBAGENT_UNASSIGNED = "PAYER_SUBAGENT_UNASSIGNED", "Sub-agent unassigned"
    PAYER_SUBAGENT_REASSIGNED = "PAYER_SUBAGENT_REASSIGNED", "Sub-agent reassigned"
    PAYMENT_OBLIGATION_CREATED = "PAYMENT_OBLIGATION_CREATED", "Payment obligation created"
    PAYMENT_OBLIGATION_UPDATED = "PAYMENT_OBLIGATION_UPDATED", "Payment obligation updated"
    PAYMENT_OBLIGATION_CANCELLED = "PAYMENT_OBLIGATION_CANCELLED", "Payment obligation cancelled"
    PAYMENT_RECORDED = "PAYMENT_RECORDED", "Payment recorded"
    PAYMENT_REVERSED = "PAYMENT_REVERSED", "Payment reversed"


class PaymentPayer(TimeStampedModel):
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="payment_payers")
    payer_name = models.CharField(max_length=200)
    telephone = models.CharField(max_length=80, blank=True, default="")
    email = models.EmailField(max_length=255, blank=True, default="")
    address = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_payment_payers")

    class Meta:
        ordering = ["payer_name", "id"]
        constraints = [
            models.UniqueConstraint(Lower("payer_name"), "agency", name="unique_payment_payer_name_per_agency"),
            models.CheckConstraint(condition=~Q(payer_name=""), name="payment_payer_name_not_empty"),
        ]
        indexes = [models.Index(fields=["agency", "is_active", "payer_name"])]

    def clean(self):
        if not self.payer_name or not self.payer_name.strip():
            raise ValidationError({"payer_name": "Payer name is required."})
        self.payer_name = " ".join(self.payer_name.split())
        if self.agency_id and not self.agency.is_active:
            raise ValidationError({"agency": "Inactive agencies reject new Payers."})
        if self.pk:
            matches = PaymentPayer.objects.filter(agency_id=self.agency_id, payer_name__iexact=self.payer_name).exclude(pk=self.pk)
            if matches.exists():
                raise ValidationError({"payer_name": "A payer with this name already exists in this agency."})
        elif PaymentPayer.objects.filter(agency_id=self.agency_id, payer_name__iexact=self.payer_name).exists():
            raise ValidationError({"payer_name": "A payer with this name already exists in this agency."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.payer_name} ({self.agency.name})"


class PayerSubAgentAssignment(TimeStampedModel):
    payer = models.ForeignKey(PaymentPayer, on_delete=models.CASCADE, related_name="sub_agent_assignments")
    sub_agent_number = models.ForeignKey(TPMCode, on_delete=models.PROTECT, related_name="payment_payer_assignments")
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="assigned_payment_sub_agents")
    assigned_at = models.DateTimeField(default=timezone.now)
    unassigned_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="unassigned_payment_sub_agents")
    unassigned_at = models.DateTimeField(null=True, blank=True)
    reassignment_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["payer__payer_name", "sub_agent_number__code"]
        constraints = [
            models.UniqueConstraint(fields=["payer", "sub_agent_number"], name="unique_payer_sub_agent_assignment"),
            models.UniqueConstraint(fields=["sub_agent_number"], condition=Q(is_active=True), name="unique_active_payer_sub_agent_assignment"),
        ]
        indexes = [models.Index(fields=["payer", "is_active"]), models.Index(fields=["sub_agent_number", "is_active"])]

    def clean(self):
        if self.payer_id and self.sub_agent_number_id and self.payer.agency_id != self.sub_agent_number.person.agency_id:
            raise ValidationError({"sub_agent_number": "Sub-Agent Number must belong to the same agency as the payer."})
        if not self.payer.is_active:
            raise ValidationError({"payer": "Inactive payers cannot receive new assignments."})
        if not self.sub_agent_number.is_active:
            raise ValidationError({"sub_agent_number": "Inactive Sub-Agent Numbers cannot receive new assignments."})
        if not self.sub_agent_number.person.is_active:
            raise ValidationError({"sub_agent_number": "The Sub-Agent Number owner must be active."})
        if self.is_active and self.payer.agency_id and not self.payer.agency.is_active:
            raise ValidationError({"payer": "Assignments require an active agency."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.payer.payer_name} -> {self.sub_agent_number.code}"


class PaymentNumberSequence(models.Model):
    sequence_type = models.CharField(max_length=20)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sequence_type", "year"], name="unique_payment_number_sequence")
        ]


def next_payment_number(sequence_type, year, prefix):
    with transaction.atomic():
        sequence, _ = PaymentNumberSequence.objects.select_for_update().get_or_create(
            sequence_type=sequence_type,
            year=year,
            defaults={"last_value": 0},
        )
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        return f"{prefix}-{year}-{sequence.last_value:06d}"


class PaymentObligation(TimeStampedModel):
    class ObligationStatus(models.TextChoices):
        OPEN = "OPEN", "Open"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="payment_obligations")
    payer = models.ForeignKey(PaymentPayer, on_delete=models.PROTECT, related_name="obligations")
    obligation_number = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=255)
    obligation_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    total_expected = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=ObligationStatus.choices, default=ObligationStatus.OPEN)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_payment_obligations")
    cancelled_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="cancelled_payment_obligations")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-obligation_date", "-id"]
        indexes = [models.Index(fields=["agency", "status", "obligation_date"]), models.Index(fields=["payer", "obligation_date"])]
        constraints = [
            models.CheckConstraint(condition=Q(total_expected__gt=0), name="payment_obligation_total_expected_positive"),
        ]

    def clean(self):
        if self.total_expected is not None and self.total_expected <= 0:
            raise ValidationError({"total_expected": "Total expected must be greater than zero."})
        if self.agency_id and self.payer_id and self.payer.agency_id != self.agency_id:
            raise ValidationError({"payer": "Obligation agency must match the payer's agency."})
        if not (self.description or "").strip():
            raise ValidationError({"description": "Description is required."})
        if self.agency_id and not self.agency.is_active:
            raise ValidationError({"agency": "Active agencies only."})
        if self.payer_id and not self.payer.is_active:
            raise ValidationError({"payer": "Inactive payers cannot carry obligations."})
        if self.pk:
            original = PaymentObligation.objects.filter(pk=self.pk).first()
            has_posted_payments = self.payments.filter(status=PayerPayment.PaymentStatus.POSTED).exists() if original else False
            if has_posted_payments:
                if self.agency_id and original.agency_id != self.agency_id:
                    raise ValidationError({"agency": "Agency cannot change after the first posted payment."})
                if self.payer_id and original.payer_id != self.payer_id:
                    raise ValidationError({"payer": "Payer cannot change after the first posted payment."})
                if self.total_expected != original.total_expected:
                    raise ValidationError({"total_expected": "Expected amount cannot be changed after the first posted payment."})

    @property
    def total_paid(self):
        if not self.pk:
            return Decimal("0.00")
        total = self.payments.filter(status=PayerPayment.PaymentStatus.POSTED).aggregate(total=models.Sum("amount_received"))["total"]
        return money(total or Decimal("0.00"))

    @property
    def balance(self):
        return money(self.total_expected - self.total_paid)

    def refresh_status(self):
        if not self.pk:
            return self.status
        if self.status == self.ObligationStatus.CANCELLED:
            return self.status
        if self.total_paid == 0:
            self.status = self.ObligationStatus.OPEN
        elif self.total_paid >= self.total_expected:
            self.status = self.ObligationStatus.PAID
        else:
            self.status = self.ObligationStatus.PARTIALLY_PAID
        return self.status

    def save(self, *args, **kwargs):
        self.total_expected = money(self.total_expected)
        self.description = " ".join(self.description.split()) if self.description else ""
        if isinstance(self.obligation_date, str):
            self.obligation_date = timezone.datetime.strptime(self.obligation_date, "%Y-%m-%d").date()
        if not self.obligation_number and not self.pk:
            year = self.obligation_date.year if self.obligation_date else timezone.now().year
            self.obligation_number = next_payment_number("OBLIGATION", year, "TLI-OBL")
        self.full_clean()
        if self.status != self.ObligationStatus.CANCELLED:
            self.refresh_status()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.obligation_number} - {self.payer.payer_name}"


class PayerPayment(TimeStampedModel):
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        CHEQUE = "CHEQUE", "Cheque"
        OTHER = "OTHER", "Other"

    class PaymentStatus(models.TextChoices):
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    obligation = models.ForeignKey(PaymentObligation, on_delete=models.PROTECT, related_name="payments")
    receipt_number = models.CharField(max_length=40, unique=True)
    agency_snapshot = models.CharField(max_length=200)
    payer_name_snapshot = models.CharField(max_length=200)
    linked_sub_agent_numbers_snapshot = models.JSONField(default=list, blank=True)
    obligation_number_snapshot = models.CharField(max_length=40)
    obligation_description_snapshot = models.CharField(max_length=255)
    obligation_date_snapshot = models.DateField()
    expected_amount_snapshot = models.DecimalField(max_digits=14, decimal_places=2)
    amount_previously_paid = models.DecimalField(max_digits=14, decimal_places=2)
    amount_received = models.DecimalField(max_digits=14, decimal_places=2)
    cumulative_amount_paid = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after_payment = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    payment_reference = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    recorded_by_display_snapshot = models.CharField(max_length=255, blank=True, default="")
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recorded_payer_payments")
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.POSTED)
    idempotency_key = models.CharField(max_length=100, unique=True)
    reversed_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_payer_payments")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-payment_date", "-id"]
        indexes = [models.Index(fields=["obligation", "status", "payment_date"]), models.Index(fields=["idempotency_key"]) ]
        constraints = [
            models.CheckConstraint(condition=Q(expected_amount_snapshot__gt=0), name="payment_expected_snapshot_positive"),
            models.CheckConstraint(condition=Q(amount_previously_paid__gte=0), name="payment_previous_paid_non_negative"),
            models.CheckConstraint(condition=Q(amount_received__gt=0), name="payment_amount_received_positive"),
            models.CheckConstraint(condition=Q(cumulative_amount_paid__gte=0), name="payment_cumulative_paid_non_negative"),
            models.CheckConstraint(condition=Q(balance_after_payment__gte=0), name="payment_balance_after_non_negative"),
            models.CheckConstraint(
                condition=(
                    Q(status="POSTED", reversed_by__isnull=True, reversed_at__isnull=True, reversal_reason="")
                    | Q(status="REVERSED", reversed_by__isnull=False, reversed_at__isnull=False) & ~Q(reversal_reason="")
                ),
                name="payment_reversal_metadata_consistent",
            ),
        ]

    def clean(self):
        if self.amount_received <= 0:
            raise ValidationError({"amount_received": "Payment amount must be greater than zero."})
        if self.payment_method != self.PaymentMethod.CASH and not self.payment_reference.strip():
            raise ValidationError({"payment_reference": "A payment reference is required for non-cash payments."})
        if self.payment_method == self.PaymentMethod.CASH and self.payment_reference and len(self.payment_reference.strip()) > 120:
            raise ValidationError({"payment_reference": "Reference is too long."})
        if self.status == self.PaymentStatus.REVERSED and not self.reversal_reason.strip():
            raise ValidationError({"reversal_reason": "A reversal reason is required."})
        if self.status == self.PaymentStatus.REVERSED and (not self.reversed_by_id or not self.reversed_at):
            raise ValidationError({"status": "Reversed payments require reversal actor and timestamp."})
        if self.status == self.PaymentStatus.POSTED and (self.reversed_by_id or self.reversed_at or self.reversal_reason.strip()):
            raise ValidationError({"status": "Posted payments cannot contain reversal metadata."})

        if self.pk:
            original = PayerPayment.objects.filter(pk=self.pk).first()
            if original and original.status == self.PaymentStatus.POSTED:
                immutable_fields = (
                    "obligation_id", "receipt_number", "agency_snapshot", "payer_name_snapshot",
                    "linked_sub_agent_numbers_snapshot", "obligation_number_snapshot",
                    "obligation_description_snapshot", "obligation_date_snapshot",
                    "expected_amount_snapshot", "amount_previously_paid", "amount_received",
                    "cumulative_amount_paid", "balance_after_payment", "payment_date",
                    "payment_method", "payment_reference", "notes", "recorded_by_id",
                    "recorded_by_display_snapshot", "idempotency_key",
                )
                if any(getattr(original, field) != getattr(self, field) for field in immutable_fields):
                    raise ValidationError({"detail": "POSTED payment records are immutable."})
            elif original and original.status == self.PaymentStatus.REVERSED and self.status != original.status:
                raise ValidationError({"detail": "REVERSED payment records are immutable."})

    def save(self, *args, **kwargs):
        self.amount_received = money(self.amount_received)
        self.amount_previously_paid = money(self.amount_previously_paid)
        self.cumulative_amount_paid = money(self.cumulative_amount_paid)
        self.balance_after_payment = money(self.balance_after_payment)
        self.expected_amount_snapshot = money(self.expected_amount_snapshot)
        if not self.receipt_number and not self.pk:
            self.receipt_number = next_payment_number("PAYMENT", self.payment_date.year if self.payment_date else timezone.now().year, "TLI-PAY")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Payment records cannot be deleted.")

    def __str__(self):
        return f"{self.receipt_number} - {self.payer_name_snapshot}"


class DailySheet(TimeStampedModel):
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="daily_sheets")
    transaction_date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=DailySheetStatus.choices, default=DailySheetStatus.DRAFT)
    is_archived = models.BooleanField(default=False)
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

    @property
    def can_reset(self):
        return not self.is_archived and self.is_accountant_editable

    @property
    def can_delete(self):
        history_fields = ("submitted_by_id", "submitted_at", "approved_by_id", "approved_at",
                          "returned_by_id", "returned_at", "reopened_by_id", "reopened_at",
                          "return_comment", "reopen_reason", "reconciliation_note")
        return (
            self.status == DailySheetStatus.DRAFT and not self.is_archived
            and self.incoming_funds is None and self.tax is None
            and not any(getattr(self, field) for field in history_fields)
            and not self.transactions.exists() and not self.omitted_terminals.exists()
            and not TransactionGameSale.objects.filter(daily_sheet_game__daily_sheet=self).exists()
            and not DailySheetImportBatch.objects.filter(
                Q(confirmed_sheet=self) | Q(existing_sheet=self),
                Q(status=DailySheetImportStatus.CONFIRMED) | Q(confirmed_at__isnull=False),
            ).exists()
            and not self.audit_logs.exclude(action=AuditAction.SHEET_CREATED).exists()
        )

    def copy_weekday_games(self):
        schedules = WeeklyGameSchedule.objects.select_related("game").filter(
            weekday=self.transaction_date.isoweekday(),
            is_active=True,
            game__is_active=True,
        ).order_by("display_order", "id")
        DailySheetGame.objects.bulk_create(
            [
                DailySheetGame(
                    daily_sheet=self,
                    game=schedule.game,
                    game_name_snapshot=schedule.game.name,
                    is_whole_day_snapshot=schedule.is_whole_day,
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
            .values("transaction_id", "transaction__person_id_snapshot", "transaction__agent_type_snapshot")
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
            "tax": tax,
            "variance": variance,
            "variance_status": variance_status,
        }

    def __str__(self):
        return f"{self.agency.name} - {self.transaction_date}"


class DailySheetGame(models.Model):
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.CASCADE, related_name="sheet_games")
    game = models.ForeignKey(Game, on_delete=models.PROTECT, related_name="daily_sheet_games")
    game_name_snapshot = models.CharField(max_length=120)
    is_whole_day_snapshot = models.BooleanField(default=False)
    closing_time_snapshot = models.TimeField(null=True, blank=True)
    draw_time_snapshot = models.TimeField(null=True, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["daily_sheet", "display_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["daily_sheet", "game"], name="unique_daily_sheet_game"),
        ]
        indexes = [
            models.Index(fields=["daily_sheet", "display_order"]),
        ]

    def __str__(self):
        return f"{self.daily_sheet} - {self.game_name_snapshot}"


class DailySheetImportStatus(models.TextChoices):
    PREVIEWED = "PREVIEWED", "Previewed"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    FAILED = "FAILED", "Failed"
    EXPIRED = "EXPIRED", "Expired"


class DailySheetImportBatch(TimeStampedModel):
    uploader = models.ForeignKey(User, on_delete=models.PROTECT, related_name="daily_sheet_import_batches")
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="daily_sheet_import_batches")
    transaction_date = models.DateField(db_index=True)
    original_filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=20, choices=DailySheetImportStatus.choices, default=DailySheetImportStatus.PREVIEWED)
    preview_payload = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    errors = models.JSONField(default=list)
    existing_sheet = models.ForeignKey(DailySheet, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_batches")
    existing_transaction_count = models.PositiveIntegerField(default=0)
    confirmed_sheet = models.ForeignKey(DailySheet, on_delete=models.SET_NULL, null=True, blank=True, related_name="confirmed_import_batches")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["uploader", "status"]),
            models.Index(fields=["agency", "transaction_date"]),
        ]

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    def __str__(self):
        return f"{self.original_filename} - {self.agency.name} - {self.transaction_date}"


class TPMDailyTransaction(TimeStampedModel):
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.CASCADE, related_name="transactions")
    tpm_code = models.ForeignKey(TPMCode, on_delete=models.PROTECT, related_name="daily_transactions")
    person_id_snapshot = models.PositiveBigIntegerField(editable=False)
    tpm_code_snapshot = models.CharField(max_length=80, editable=False)
    terminal_number_snapshot = models.CharField(max_length=80, blank=True, default="", editable=False)
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
                errors["tpm_code"] = "Sub-Agent Number must be active."
            if not self.tpm_code.person.is_active:
                errors["tpm_code"] = "Sub-Agent Number person must be active."
        if self.daily_sheet_id and self.tpm_code_id and self.tpm_code.person.agency_id != self.daily_sheet.agency_id:
            errors["tpm_code"] = "Sub-Agent Number must belong to the DailySheet agency."
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, terminal_snapshot=None, **kwargs):
        if self._state.adding and self.tpm_code_id:
            list(Agency.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
            self.tpm_code = TPMCode.objects.select_for_update().select_related("person").get(pk=self.tpm_code_id)
            self.person_id_snapshot = self.tpm_code.person_id
            self.tpm_code_snapshot = self.tpm_code.code
            # Imports explicitly preserve an absent workbook terminal; manual entry
            # records the current assignment. Existing historical rows are untouched.
            self.terminal_number_snapshot = (TerminalNumber.objects.filter(sub_agent_number_id=self.tpm_code_id, is_active=True).values_list("terminal_number", flat=True).first() or "") if terminal_snapshot is None else terminal_snapshot
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
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["tpm_code__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["daily_sheet", "tpm_code"],
                condition=Q(is_active=True),
                name="unique_active_omitted_terminal_per_sheet",
            ),
        ]
        indexes = [
            models.Index(fields=["daily_sheet", "tpm_code"]),
        ]

    def clean(self):
        errors = {}
        if self.tpm_code_id:
            if not self.tpm_code.is_active or not self.tpm_code.person.is_active:
                errors["tpm_code"] = "Only active Sub-Agent Numbers for active people may be omitted."
        if self.daily_sheet_id and self.tpm_code_id:
            if self.tpm_code.person.agency_id != self.daily_sheet.agency_id:
                errors["tpm_code"] = "Sub-Agent Number must belong to the DailySheet agency."
            if self.is_active and TPMDailyTransaction.objects.filter(daily_sheet=self.daily_sheet, tpm_code=self.tpm_code).exists():
                errors["tpm_code"] = "Sub-Agent Number cannot be both entered and omitted on the same sheet."
        if not self.reason.strip():
            errors["reason"] = "Reason is required."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tpm_code.code} omitted from {self.daily_sheet}"


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Audit logs are immutable.")

    def delete(self):
        raise ValidationError("Audit logs are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Audit logs are immutable.")

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Audit logs are immutable.")
        return super().bulk_create(objs, **kwargs)


class AuditLog(models.Model):
    objects = ImmutableAuditQuerySet.as_manager()

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="audit_logs")
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="audit_logs", null=True, blank=True)
    daily_sheet = models.ForeignKey(DailySheet, on_delete=models.SET_NULL, related_name="audit_logs", null=True, blank=True)
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
