from django.contrib import admin

from .models import Holiday, Organization


class HolidayInline(admin.TabularInline):
    model = Holiday
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "default_timezone", "currency")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [HolidayInline]
