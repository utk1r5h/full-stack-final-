from pathlib import Path

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Claim, Item


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "public_type", "name", "report_type", "category", "description", "colour",
            "date_lost_found", "location", "identifying_features", "image",
        ]
        labels = {
            "public_type": "General item type (visible to everyone)",
            "name": "Private item name / exact identity",
            "location": "Exact location (private)",
            "identifying_features": "Private identifying features",
        }
        help_texts = {
            "public_type": "Choose only a broad type such as Laptop, Book or Bag. This is the only item identity shown publicly.",
            "name": "Enter the actual brand/model or item name. Only you and authorised staff can see it.",
            "description": "Keep detailed information private. It will be visible only to you and authorised staff.",
            "location": "Enter the precise location. It will not be shown to other users.",
            "identifying_features": "Add scratches, stickers, serial/asset identifiers or other proof. Never include passwords.",
            "image": "Optional. Uploaded images are private and are not exposed through a public media URL. Maximum 5 MB.",
        }
        widgets = {
            "date_lost_found": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "identifying_features": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            if image.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Image must be 5 MB or smaller.")
            extension = Path(image.name).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                raise forms.ValidationError("Upload a JPG, PNG, WEBP or GIF image.")
        return image


class ClaimForm(forms.ModelForm):
    proof_description = forms.CharField(
        min_length=30,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
        label="Ownership verification answers",
        help_text=(
            "Describe details only the genuine owner is likely to know: exact model, distinctive marks, "
            "accessories or other identifying evidence. Your answers are private and visible only to authorised staff. "
            "Do not include passwords, OTPs or account recovery information."
        ),
    )

    class Meta:
        model = Claim
        fields = ["matched_lost_item", "proof_description"]
        widgets = {"proof_description": forms.Textarea(attrs={"rows": 5})}
        labels = {
            "matched_lost_item": "Link your own lost-item report (optional)",
            "proof_description": "Ownership verification answers",
        }
        help_texts = {
            "proof_description": (
                "Describe the exact brand/model, distinctive marks or scratches, accessories, "
                "contents, or other details that only the genuine owner is likely to know. "
                "Do not include passwords, OTPs or account recovery information."
            )
        }

    def __init__(self, *args, user=None, found_item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = getattr(user, "pk", None)
        self.fields["matched_lost_item"].required = False
        self.fields["matched_lost_item"].queryset = Item.objects.none()
        self.fields["matched_lost_item"].empty_label = "-- Select one of my open lost reports --"
        if user and found_item:
            self.fields["matched_lost_item"].queryset = Item.objects.filter(
                reported_by=user, report_type=Item.ReportType.LOST, status=Item.Status.OPEN,
            ).order_by("-created_at")

    def clean(self):
        cleaned = super().clean()
        lost_item = cleaned.get("matched_lost_item")
        if lost_item and (lost_item.report_type != Item.ReportType.LOST or lost_item.reported_by_id != getattr(self, "user_id", lost_item.reported_by_id)):
            self.add_error("matched_lost_item", "Select one of your own lost-item reports.")
        return cleaned


class ClaimReviewForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_status = self.instance.status
        allowed = Claim.ALLOWED_TRANSITIONS.get(current_status, {current_status})
        self.fields["status"].choices = [choice for choice in Claim.Status.choices if choice[0] in allowed]

    class Meta:
        model = Claim
        fields = ["status", "admin_note"]
        widgets = {"admin_note": forms.Textarea(attrs={"rows": 3})}
        labels = {"admin_note": "Internal administrator note (not visible to claimant)"}
