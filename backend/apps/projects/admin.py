from django.contrib import admin

from .models import Project, ProjectMembership


class ProjectMembershipInline(admin.TabularInline):
    model = ProjectMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "team", "manager", "status", "visibility", "is_archived")
    list_filter = ("status", "visibility", "is_archived")
    search_fields = ("code", "name")
    inlines = [ProjectMembershipInline]
