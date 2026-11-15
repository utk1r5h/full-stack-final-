from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Item(models.Model):
    class ReportType(models.TextChoices):
        LOST = "LOST", "Lost"
        FOUND = "FOUND", "Found"

    class PublicType(models.TextChoices):
        LAPTOP = "LAPTOP", "Laptop"
        PHONE = "PHONE", "Phone"
        TABLET = "TABLET", "Tablet"
        BOOK = "BOOK", "Book"
        BAG = "BAG", "Bag"
        WALLET = "WALLET", "Wallet"
        KEYS = "KEYS", "Keys"
        BOTTLE = "BOTTLE", "Bottle"
        CLOTHING = "CLOTHING", "Clothing"
        ACCESSORY = "ACCESSORY", "Accessory"
        OTHER = "OTHER", "Other item"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLAIMED = "CLAIMED", "Claimed"
        RETURNED = "RETURNED", "Returned"
        CLOSED = "CLOSED", "Closed"

    # This broad label is intentionally public. All other descriptive fields
    # are private and must only be rendered for the reporter or staff.
    public_type = models.CharField(
        max_length=12, choices=PublicType.choices, default=PublicType.OTHER,
        help_text="Broad object type shown publicly (e.g. Laptop, Book or Bag). Do not include a brand/model here.",
    )
    name = models.CharField(max_length=120)
    report_type = models.CharField(max_length=5, choices=ReportType.choices)
    category = models.CharField(max_length=80)
    description = models.TextField()
    colour = models.CharField(max_length=50, blank=True)
    date_lost_found = models.DateField()
    location = models.CharField(max_length=150)
    identifying_features = models.TextField(blank=True)
    image = models.ImageField(upload_to="items/", blank=True, null=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="item_reports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["report_type", "status"], name="idx_item_report_status"),
            models.Index(fields=["category", "status"], name="idx_item_category_status"),
            models.Index(fields=["public_type", "status"], name="idx_item_public_status"),
        ]

    def clean(self):
        super().clean()
        if self.image:
            from pathlib import Path
            if self.image.size > 5 * 1024 * 1024:
                raise ValidationError({"image": "Image must be 5 MB or smaller."})
            if Path(self.image.name).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                raise ValidationError({"image": "Upload a JPG, PNG, WEBP or GIF image."})

    def __str__(self):
        return f"{self.get_report_type_display()}: {self.name}"


class Claim(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        VERIFYING = "VERIFYING", "Under Verification"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        RETURNED = "RETURNED", "Returned"

    ALLOWED_TRANSITIONS = {
        Status.PENDING: {Status.PENDING, Status.VERIFYING, Status.APPROVED, Status.REJECTED},
        Status.VERIFYING: {Status.VERIFYING, Status.APPROVED, Status.REJECTED},
        Status.APPROVED: {Status.APPROVED, Status.RETURNED},
        Status.REJECTED: {Status.REJECTED},
        Status.RETURNED: {Status.RETURNED},
    }

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="claims")
    claimant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="claims")
    matched_lost_item = models.ForeignKey(
        Item, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="linked_claims", limit_choices_to={"report_type": "LOST"},
        help_text="Optional link to your own lost-item report.",
    )
    proof_description = models.TextField(
        help_text="Describe details that only the genuine owner would know. Never include passwords or account recovery codes."
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["item", "claimant"], name="one_claim_per_user_per_item"),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status__in=["APPROVED", "RETURNED"]),
                name="one_finalized_claim_per_item",
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="idx_claim_status_created")]

    def clean(self):
        super().clean()
        if self.pk:
            old_status = Claim.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if old_status and self.status not in self.ALLOWED_TRANSITIONS.get(old_status, set()):
                raise ValidationError({"status": f"A claim cannot move from {old_status} to {self.status}."})
        if self.item_id:
            if self.item.report_type != Item.ReportType.FOUND:
                raise ValidationError({"item": "A claim can only be submitted for a found item."})
            if self.claimant_id and self.item.reported_by_id == self.claimant_id:
                raise ValidationError({"item": "You cannot claim an item that you reported as found."})
            if self.item.status != Item.Status.OPEN and self.status in (self.Status.PENDING, self.Status.VERIFYING):
                raise ValidationError({"item": "This item is no longer accepting claims."})
            if self.status in (self.Status.APPROVED, self.Status.RETURNED):
                another_approved_claim = Claim.objects.filter(
                    item_id=self.item_id, status__in=(self.Status.APPROVED, self.Status.RETURNED)
                ).exclude(pk=self.pk).exists()
                if another_approved_claim:
                    raise ValidationError({"status": "Another claim for this item has already been approved."})
        if self.matched_lost_item_id:
            lost_item = self.matched_lost_item
            if lost_item.report_type != Item.ReportType.LOST:
                raise ValidationError({"matched_lost_item": "The linked report must be a lost item."})
            if self.claimant_id and lost_item.reported_by_id != self.claimant_id:
                raise ValidationError({"matched_lost_item": "You can only link your own lost-item report."})

    def __str__(self):
        return f"Claim #{self.pk or 'new'} for item #{self.item_id} by {self.claimant}"
