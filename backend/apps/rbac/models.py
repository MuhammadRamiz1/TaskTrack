from django.conf import settings
from django.db import models

from apps.common import tenancy
from apps.common.models import BaseModel, TenantModel

from .catalogue import Scope

SCOPE_CHOICES = [(s.value, s.value.title()) for s in Scope]


class Permission(BaseModel):
    """Global catalogue entry, loaded from ``catalogue.py`` by migrations."""

    code = models.CharField(max_length=80, unique=True)
    module = models.CharField(max_length=40)
    description = models.CharField(max_length=200)
    allowed_scopes = models.JSONField(default=list)

    class Meta:
        ordering = ["module", "code"]

    def __str__(self):
        return self.code


class RoleManager(models.Manager):
    """Company roles in TENANT mode (plus read access to templates via ``templates()``)."""

    def get_queryset(self):
        qs = super().get_queryset()
        state = tenancy.current()
        if state.mode == tenancy.Mode.TENANT:
            return qs.filter(company_id=state.company_id)
        if state.mode == tenancy.Mode.PLATFORM:
            return qs
        raise tenancy.TenantContextMissing("Role queried without a tenant context.")


class Role(BaseModel):
    """Named permission bundle. ``company`` NULL = system template copied into companies."""

    company = models.ForeignKey(
        "companies.Company", null=True, blank=True, on_delete=models.CASCADE, related_name="roles"
    )
    key = models.CharField(max_length=40)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    rank = models.PositiveSmallIntegerField()
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, through="RolePermission", related_name="roles")

    objects = RoleManager()

    class Meta:
        ordering = ["-rank", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "key"], name="rbac_role_unique_key_per_company", nulls_distinct=False
            ),
            models.CheckConstraint(condition=models.Q(rank__lte=100), name="rbac_role_rank_max_100"),
        ]

    def __str__(self):
        return self.name


class RolePermission(BaseModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="grants")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="grants")
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="rbac_rolepermission_unique"),
            models.CheckConstraint(
                condition=models.Q(scope__in=[s.value for s in Scope]), name="rbac_rolepermission_scope_valid"
            ),
        ]


class UserRole(TenantModel):
    """A role held by a user, optionally bound to one team or one project.

    The binding narrows TEAM and PROJECT scoped grants (see rbac.adapters resolvers):
    a TEAM_LEAD bound to team X leads team X only. Unbound roles resolve to the teams
    and projects the user is a member of.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    team = models.ForeignKey("org.Team", null=True, blank=True, on_delete=models.CASCADE, related_name="role_bindings")
    project = models.ForeignKey(
        "org.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="role_bindings"
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "team", "project"], name="rbac_userrole_unique", nulls_distinct=False
            ),
            models.CheckConstraint(
                condition=~(models.Q(team__isnull=False) & models.Q(project__isnull=False)),
                name="rbac_userrole_single_binding",
            ),
        ]
        indexes = [models.Index(fields=["user"], name="rbac_userrole_user")]

    def __str__(self):
        return f"{self.user_id}:{self.role_id}"
