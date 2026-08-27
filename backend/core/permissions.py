from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import UserRole


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == UserRole.SUPER_ADMIN)


class SuperAdminOrReadOnlyAccountant(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        return request.user.role == UserRole.ACCOUNTANT and request.method in SAFE_METHODS


class SuperAdminOnlyWrites(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return request.user.role in {UserRole.SUPER_ADMIN, UserRole.ACCOUNTANT}
        return request.user.role == UserRole.SUPER_ADMIN
