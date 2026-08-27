from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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
