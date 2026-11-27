import django_filters
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.accounts import serializers as account_s
from apps.accounts.services import platform as platform_accounts
from apps.common.exceptions import NotFound
from apps.common.pagination import PageNumberPagination
from apps.common.views import LIST_FILTERS, PlatformAPIView, TenantAPIView, schema_generation

from . import serializers as s
from . import services
from .models import Company, Plan

COMPANY_PERM = "platform.company.manage"


class CompanyFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=Company.Status.choices)
    plan = django_filters.UUIDFilter(field_name="plan_id")

    class Meta:
        model = Company
        fields = ["status", "plan"]


def _companies():
    return Company.objects.select_related("plan").annotate(
        user_count=Count("users", filter=~Q(users__status="DEACTIVATED"))
    )


def _company(company_id) -> Company:
    company = _companies().filter(pk=company_id).first()
    if company is None:
        raise NotFound()
    return company


class CompanyListView(PlatformAPIView):
    pagination_class = PageNumberPagination
    filter_backends = LIST_FILTERS
    permission_map = {"GET": COMPANY_PERM, "POST": COMPANY_PERM}
    filterset_class = CompanyFilter
    search_fields = ["name", "slug"]
    ordering_fields = ["name", "created_at", "status"]
    ordering = ["name"]

    def get_queryset(self):
        if schema_generation(self):
            return Company._base_manager.none()
        return _companies()

    @extend_schema(responses=s.CompanyOutput(many=True), tags=["platform"], summary="List companies")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.CompanyOutput(page, many=True).data)

    @extend_schema(
        request=s.CompanyWriteInput,
        responses={201: s.CompanyOutput},
        tags=["platform"],
        summary="Create a company (roles are provisioned automatically)",
    )
    def post(self, request):
        data = s.CompanyWriteInput(data=request.data)
        data.is_valid(raise_exception=True)
        company = services.create_company(actor=request.user, data=data.validated_data)
        return Response(s.CompanyOutput(_company(company.pk)).data, status=status.HTTP_201_CREATED)


class CompanyDetailView(PlatformAPIView):
    queryset = Company._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"GET": COMPANY_PERM, "PATCH": COMPANY_PERM, "DELETE": COMPANY_PERM}

    @extend_schema(responses=s.CompanyOutput, tags=["platform"], summary="Company details")
    def get(self, request, company_id):
        return Response(s.CompanyOutput(_company(company_id)).data)

    @extend_schema(
        request=s.CompanyWriteInput,
        responses=s.CompanyOutput,
        tags=["platform"],
        summary="Edit a company, its plan and limits",
    )
    def patch(self, request, company_id):
        company = _company(company_id)
        data = s.CompanyWriteInput(company, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_company(actor=request.user, company=company, data=data.validated_data)
        return Response(s.CompanyOutput(_company(company_id)).data)

    @extend_schema(responses=s.CompanyOutput, tags=["platform"], summary="Soft-delete a company (signs out all users)")
    def delete(self, request, company_id):
        services.soft_delete(actor=request.user, company=_company(company_id))
        return Response(s.CompanyOutput(_company(company_id)).data)


class CompanySuspendView(PlatformAPIView):
    queryset = Company._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"POST": COMPANY_PERM}

    @extend_schema(
        request=s.SuspendInput,
        responses=s.CompanyOutput,
        tags=["platform"],
        summary="Suspend a company (signs out all users)",
    )
    def post(self, request, company_id):
        company = _company(company_id)
        data = s.SuspendInput(data=request.data)
        data.is_valid(raise_exception=True)
        services.suspend(actor=request.user, company=company, reason=data.validated_data["reason"])
        return Response(s.CompanyOutput(_company(company_id)).data)


class CompanyActivateView(PlatformAPIView):
    queryset = Company._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"POST": COMPANY_PERM}

    @extend_schema(request=None, responses=s.CompanyOutput, tags=["platform"], summary="Re-activate a company")
    def post(self, request, company_id):
        services.activate(actor=request.user, company=_company(company_id))
        return Response(s.CompanyOutput(_company(company_id)).data)


class CompanyUsageView(PlatformAPIView):
    queryset = Company._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"GET": COMPANY_PERM}

    @extend_schema(responses=s.UsageOutput, tags=["platform"], summary="Users and storage used")
    def get(self, request, company_id):
        return Response(services.usage(_company(company_id)))


class CompanyAdminCreateView(PlatformAPIView):
    queryset = Company._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"POST": "platform.company_admin.invite"}

    @extend_schema(
        request=account_s.CompanyAdminInput,
        responses={201: account_s.UserBrief},
        tags=["platform"],
        summary="Create the company's first HR or admin account and email the invite",
    )
    def post(self, request, company_id):
        company = _company(company_id)
        data = account_s.CompanyAdminInput(data=request.data)
        data.is_valid(raise_exception=True)
        user = platform_accounts.create_company_admin(actor=request.user, company=company, data=data.validated_data)
        return Response(account_s.UserBrief(user).data, status=status.HTTP_201_CREATED)


class CompanyUsersView(PlatformAPIView):
    """Identity-only user list so a super admin can pick an impersonation target.
    No task or time data; every call is audit-logged against the company."""

    queryset = Company._base_manager.none()
    permission_map = {"GET": "platform.impersonate"}
    pagination_class = PageNumberPagination
    search_fields = ["first_name", "last_name", "email"]
    filter_backends = LIST_FILTERS

    @extend_schema(
        responses=account_s.PlatformUserOutput(many=True),
        tags=["platform"],
        summary="Users of a company (identity only, audited)",
    )
    def get(self, request, company_id):
        from apps.accounts.models import User
        from apps.audit.services import record

        company = _company(company_id)
        qs = self.filter_queryset(
            User.objects.filter(company=company).prefetch_related("user_roles__role").order_by("first_name")
        )
        page = self.paginate_queryset(qs)
        record(
            actor=request.user,
            action="platform.company.users_listed",
            entity=company,
            new_value={"search": request.query_params.get("search", "")},
        )
        return self.get_paginated_response(account_s.PlatformUserOutput(page, many=True).data)


class PlanListView(PlatformAPIView):
    queryset = Plan.objects.none()
    permission_map = {"GET": "platform.plan.manage", "POST": "platform.plan.manage"}
    pagination_class = None

    @extend_schema(responses=s.PlanSerializer(many=True), tags=["platform"], summary="List plans")
    def get(self, request):
        return Response(s.PlanSerializer(Plan.objects.all(), many=True).data)

    @extend_schema(
        request=s.PlanSerializer, responses={201: s.PlanSerializer}, tags=["platform"], summary="Create a plan"
    )
    def post(self, request):
        data = s.PlanSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        plan = services.create_plan(actor=request.user, data=data.validated_data)
        return Response(s.PlanSerializer(plan).data, status=status.HTTP_201_CREATED)


class PlanDetailView(PlatformAPIView):
    queryset = Plan.objects.none()
    permission_map = {"GET": "platform.plan.manage", "PATCH": "platform.plan.manage"}

    def _plan(self, plan_id) -> Plan:
        plan = Plan.objects.filter(pk=plan_id).first()
        if plan is None:
            raise NotFound()
        return plan

    @extend_schema(responses=s.PlanSerializer, tags=["platform"], summary="Plan details")
    def get(self, request, plan_id):
        return Response(s.PlanSerializer(self._plan(plan_id)).data)

    @extend_schema(request=s.PlanSerializer, responses=s.PlanSerializer, tags=["platform"], summary="Edit a plan")
    def patch(self, request, plan_id):
        plan = self._plan(plan_id)
        data = s.PlanSerializer(plan, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_plan(actor=request.user, plan=plan, data=data.validated_data)
        return Response(s.PlanSerializer(plan).data)


class CompanySettingsView(TenantAPIView):
    queryset = Company._base_manager.none()  # schema hint only
    """Any company user may read the settings; only holders of company.settings.manage edit them."""

    permission_map = {"GET": "employee.view", "PATCH": "company.settings.manage"}

    @extend_schema(responses=s.CompanySettingsSerializer, tags=["company"], summary="Company settings")
    def get(self, request):
        return Response(s.CompanySettingsSerializer(request.user.company).data)

    @extend_schema(
        request=s.CompanySettingsSerializer,
        responses=s.CompanySettingsSerializer,
        tags=["company"],
        summary="Edit company settings",
    )
    def patch(self, request):
        company = Company.objects.get(pk=request.user.company_id)
        data = s.CompanySettingsSerializer(company, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_settings(actor=request.user, company=company, data=data.validated_data)
        return Response(s.CompanySettingsSerializer(company).data)
