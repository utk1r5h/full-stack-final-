from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Claim, Item


admin.site.site_header = "CampusFind Administration"
admin.site.site_title = "CampusFind Admin"
admin.site.index_title = "Private item and claim management"


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("id", "public_type", "name", "report_type", "category", "location", "status", "reported_by", "created_at")
    list_filter = ("report_type", "public_type", "category", "status", "created_at")
    search_fields = ("name", "description", "location", "identifying_features", "reported_by__username")
    readonly_fields = ("created_at", "private_image_link")
    list_select_related = ("reported_by",)
    date_hierarchy = "created_at"
    fieldsets = (
        ("Public-safe label", {"fields": ("public_type", "report_type", "status")}),
        ("Private item identity and evidence", {"fields": (
            "name", "category", "description", "colour", "date_lost_found",
            "location", "identifying_features", "private_image_link",
        )}),
        ("Reporter and system metadata", {"fields": ("reported_by", "created_at")}),
    )

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm("core.view_item")

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm("core.view_item")

    def has_add_permission(self, request):
        return request.user.is_superuser or (
            request.user.has_perm("core.view_item") and request.user.has_perm("core.add_item")
        )

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or (
            request.user.has_perm("core.view_item") and request.user.has_perm("core.change_item")
        )

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or (
            request.user.has_perm("core.view_item") and request.user.has_perm("core.delete_item")
        )

    @admin.display(description="Protected image (staff only)")
    def private_image_link(self, obj):
        if not obj or not obj.pk or not obj.image:
            return "No image uploaded"
        url = reverse("private_item_image", args=[obj.pk])
        return format_html('<a href="{}" target="_blank" rel="noopener">Open private image</a>', url)


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    """Read-only claim record in Admin; decisions go through the audited review form."""
    list_display = ("id", "found_item_reference", "claimant", "matched_lost_item", "status", "review_link", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("item__name", "item__id", "claimant__username", "matched_lost_item__name")
    list_select_related = ("item", "claimant", "matched_lost_item")
    date_hierarchy = "created_at"
    readonly_fields = (
        "item", "claimant", "matched_lost_item", "proof_description",
        "status", "admin_note", "created_at", "review_link",
    )
    fieldsets = (
        ("Claimed found item", {"fields": ("item",)}),
        ("Claimant and linked lost report", {"fields": ("claimant", "matched_lost_item")}),
        ("Claimant's submitted evidence", {"fields": ("proof_description",)}),
        ("Decision", {"fields": ("status", "admin_note", "created_at", "review_link")}),
    )
    actions = None

    @admin.display(description="Found item")
    def found_item_reference(self, obj):
        return f"#{obj.item_id} · {obj.item.name}"

    @admin.display(description="Open controlled review")
    def review_link(self, obj):
        if not obj or not obj.pk:
            return "Save the claim before reviewing"
        url = reverse("claim_review", args=[obj.pk])
        return format_html('<a href="{}">Review evidence and decide</a>', url)

    def has_module_permission(self, request):
        return request.user.is_superuser or (
            request.user.has_perm("core.view_item") and (
                request.user.has_perm("core.change_claim")
            )
        )

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        # Claims must originate from an authenticated claimant, not be fabricated in Admin.
        return False

    def has_change_permission(self, request, obj=None):
        # The record is displayed read-only. Status changes use claim_review + save_claim_decision.
        return request.user.is_superuser or (
            request.user.has_perm("core.view_item") and request.user.has_perm("core.change_claim")
        )

    def has_delete_permission(self, request, obj=None):
        return False
