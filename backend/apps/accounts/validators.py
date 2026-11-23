from django.core.exceptions import ValidationError


class CharacterClassValidator:
    """Requires characters from at least ``min_classes`` of: lower, upper, digit, symbol."""

    def __init__(self, min_classes: int = 3):
        self.min_classes = min_classes

    def validate(self, password, user=None):
        classes = sum(
            [
                any(c.islower() for c in password),
                any(c.isupper() for c in password),
                any(c.isdigit() for c in password),
                any(not c.isalnum() for c in password),
            ]
        )
        if classes < self.min_classes:
            raise ValidationError(
                f"Use at least {self.min_classes} of: lowercase letters, uppercase letters, digits, symbols.",
                code="password_too_simple",
            )

    def get_help_text(self):
        return f"Your password must use at least {self.min_classes} of: lowercase, uppercase, digits, symbols."
