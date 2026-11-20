from django.contrib import admin

from .models import Team, TeamMembership


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "manager", "is_archived")
    list_filter = ("is_archived", "organization")
    search_fields = ("name",)
    inlines = [TeamMembershipInline]
