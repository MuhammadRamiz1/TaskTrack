from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role")

    def clean_password2(self):
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    ordering = ("email",)
    list_display = ("email", "full_name", "role", "department", "manager", "is_active")
    list_filter = ("role", "is_active", "department")
    search_fields = ("email", "first_name", "last_name")
    autocomplete_fields = ("manager",)
    readonly_fields = ("last_login", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "department", "designation", "manager")}),
        ("Schedule", {"fields": ("timezone", "work_start_time", "work_end_time", "working_days")}),
        ("Access", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "first_name", "last_name", "role", "password1", "password2")}),
    )
