from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public user data returned after login (never the password)."""

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "role", "is_staff"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        max_length=254,
        error_messages={
            "required": "Email is required.",
            "blank": "Email is required.",
            "invalid": "Enter a valid email address.",
        },
    )
    password = serializers.CharField(
        max_length=128,
        write_only=True,
        trim_whitespace=False,  # spaces can be part of a password
        style={"input_type": "password"},
        error_messages={
            "required": "Password is required.",
            "blank": "Password is required.",
        },
    )

    role = serializers.ChoiceField(
    choices=[
        ("admin", "admin"),
        ("user", "user"),
    ],
    required=False,
    default="user",
    write_only=True,
    error_messages={
        "invalid_choice": "Role must be either 'admin' or 'user'.",
        "required": "Role is required.",
    },
    )
    # Same message for "no such email" and "wrong password",
    # so the API doesn't reveal which emails are registered.
    INVALID_CREDENTIALS = "Invalid email or password."

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        email = attrs["email"]
        password = attrs["password"]

        # ORM lookup: SELECT ... FROM accounts_user WHERE UPPER(email) = UPPER(%s) LIMIT 1
        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            # Hash the password anyway so a missing user takes as long as a wrong password
            # (stops attackers from discovering emails by timing the response).
            User().set_password(password)
            raise serializers.ValidationError(self.INVALID_CREDENTIALS, code="authorization")

        if not user.check_password(password):  # compares against the stored hash
            raise serializers.ValidationError(self.INVALID_CREDENTIALS, code="authorization")

        if not user.is_active:
            raise serializers.ValidationError("This account is disabled.", code="authorization")

        attrs["user"] = user
        return attrs
