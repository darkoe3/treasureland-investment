from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Agency, Game, Person, TPMCode, User, UserAgencyAssignment, UserRole, WeeklyGameSchedule


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "is_active", "is_staff", "created_at", "updated_at")
        read_only_fields = fields


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
            "user": UserProfileSerializer(user).data,
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


class PersonSerializer(serializers.ModelSerializer):
    agency_name = serializers.CharField(source="agency.name", read_only=True)
    tpm_codes = serializers.StringRelatedField(many=True, read_only=True)

    class Meta:
        model = Person
        fields = ("id", "agency", "agency_name", "full_name", "agent_type", "is_active", "tpm_codes", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")


class TPMCodeSerializer(serializers.ModelSerializer):
    person_name = serializers.CharField(source="person.full_name", read_only=True)
    agency = serializers.IntegerField(source="person.agency_id", read_only=True)
    agency_name = serializers.CharField(source="person.agency.name", read_only=True)

    class Meta:
        model = TPMCode
        fields = ("id", "person", "person_name", "agency", "agency_name", "code", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")


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
