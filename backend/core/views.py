from rest_framework import filters, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import Agency, Game, Person, TPMCode, UserAgencyAssignment, UserRole, WeeklyGameSchedule
from .permissions import IsSuperAdmin, SuperAdminOnlyWrites, SuperAdminOrReadOnlyAccountant
from .serializers import (
    AgencySerializer,
    EmailTokenObtainPairSerializer,
    GameSerializer,
    PersonSerializer,
    TPMCodeSerializer,
    UserAgencyAssignmentSerializer,
    UserProfileSerializer,
    WeeklyGameScheduleSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    pass


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    refresh_token = request.data.get("refresh")
    if not refresh_token:
        return Response({"detail": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        RefreshToken(refresh_token).blacklist()
    except TokenError:
        return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user_view(request):
    return Response(UserProfileSerializer(request.user).data)


class BaseSearchViewSet(viewsets.ModelViewSet):
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]


class AgencyViewSet(BaseSearchViewSet):
    serializer_class = AgencySerializer
    permission_classes = [SuperAdminOrReadOnlyAccountant]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]

    def get_queryset(self):
        queryset = Agency.objects.all()
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(user_assignments__user=self.request.user).distinct()


class UserAgencyAssignmentViewSet(BaseSearchViewSet):
    serializer_class = UserAgencyAssignmentSerializer
    permission_classes = [SuperAdminOnlyWrites]
    search_fields = ["user__email", "user__full_name", "agency__name", "agency__code"]
    ordering_fields = ["created_at", "agency__name", "user__email"]

    def get_queryset(self):
        queryset = UserAgencyAssignment.objects.select_related("user", "agency", "assigned_by")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


class PersonViewSet(BaseSearchViewSet):
    serializer_class = PersonSerializer
    permission_classes = [SuperAdminOnlyWrites]
    search_fields = ["full_name", "agency__name", "tpm_codes__code"]
    ordering_fields = ["full_name", "created_at"]

    def get_queryset(self):
        queryset = Person.objects.select_related("agency").prefetch_related("tpm_codes")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(agency__user_assignments__user=self.request.user).distinct()


class TPMCodeViewSet(BaseSearchViewSet):
    serializer_class = TPMCodeSerializer
    permission_classes = [SuperAdminOnlyWrites]
    search_fields = ["code", "person__full_name", "person__agency__name"]
    ordering_fields = ["code", "created_at"]

    def get_queryset(self):
        queryset = TPMCode.objects.select_related("person", "person__agency")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(person__agency__user_assignments__user=self.request.user).distinct()


class GameViewSet(BaseSearchViewSet):
    serializer_class = GameSerializer
    permission_classes = [SuperAdminOnlyWrites]
    queryset = Game.objects.all()
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]


class WeeklyGameScheduleViewSet(BaseSearchViewSet):
    serializer_class = WeeklyGameScheduleSerializer
    permission_classes = [SuperAdminOnlyWrites]
    queryset = WeeklyGameSchedule.objects.select_related("game")
    search_fields = ["game__name"]
    ordering_fields = ["weekday", "display_order", "closing_time"]
