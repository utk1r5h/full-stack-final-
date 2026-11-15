import csv
import mimetypes
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .forms import RegisterForm, ItemForm, ClaimForm, ClaimReviewForm
from .matching import possible_matches
from .models import Item, Claim
from .services import save_claim_decision


PRIVATE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _can_manage_items(user):
    """Superusers and staff explicitly granted the Item view permission."""
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or (user.is_staff and user.has_perm("core.view_item"))
    ))


def _can_review_claims(user):
    """Claim reviewers must be staff and hold both item-view and claim-change permission."""
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or (
            user.is_staff and user.has_perm("core.view_item") and user.has_perm("core.change_claim")
        )
    ))


def _is_private_viewer(user, item):
    """Private item details belong only to the reporter and authorised staff."""
    return bool(user.is_authenticated and user.is_active and (item.reported_by_id == user.pk or _can_manage_items(user) or _can_review_claims(user)))


def home(request):
    latest_items = Item.objects.filter(status=Item.Status.OPEN).only(
        "id", "public_type", "report_type", "status", "created_at"
    )[:6]
    return render(request, "core/home.html", {"latest_items": latest_items})


def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your account has been created.")
            return redirect("dashboard")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
@never_cache
def dashboard(request):
    my_items = Item.objects.filter(reported_by=request.user)
    my_claims = Claim.objects.filter(claimant=request.user).select_related("item")
    context = {
        "my_items": my_items[:5],
        "my_claims": my_claims[:5],
        "lost_count": my_items.filter(report_type=Item.ReportType.LOST).count(),
        "found_count": my_items.filter(report_type=Item.ReportType.FOUND).count(),
        "claim_count": my_claims.count(),
        "can_manage_items": _can_manage_items(request.user),
        "can_review_claims": _can_review_claims(request.user),
    }
    if context["can_manage_items"]:
        context["total_items"] = Item.objects.count()
        context["returned_count"] = Item.objects.filter(status=Item.Status.RETURNED).count()
    if context["can_review_claims"]:
        context["pending_claims"] = Claim.objects.filter(
            status__in=[Claim.Status.PENDING, Claim.Status.VERIFYING]
        ).select_related("item", "claimant", "matched_lost_item")
    return render(request, "core/dashboard.html", context)


@login_required
def item_create(request):
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.reported_by = request.user
            item.save()
            messages.success(request, "Your report has been submitted. Its identifying details are private.")
            return redirect("item_detail", pk=item.pk)
    else:
        form = ItemForm()
    return render(request, "core/item_form.html", {"form": form})


def item_list(request):
    """Public browse: intentionally filter/display only broad, public-safe fields."""
    items = Item.objects.filter(status=Item.Status.OPEN).only(
        "id", "public_type", "report_type", "status", "created_at"
    )
    report_type = request.GET.get("type", "")
    query = request.GET.get("q", "").strip()[:80]
    if report_type in (Item.ReportType.LOST, Item.ReportType.FOUND):
        items = items.filter(report_type=report_type)
    if query:
        # Search only the intentionally public label. Do not search private fields,
        # because search-result existence can itself disclose private information.
        items = items.filter(public_type__icontains=query)
    public_types = Item.PublicType.choices
    return render(request, "core/item_list.html", {
        "items": items,
        "public_types": public_types,
        "query": query,
        "selected_type": report_type,
    })


@require_GET
def live_search(request):
    """AJAX search returns only the same minimal public fields as the browse page."""
    query = request.GET.get("q", "").strip()[:80]
    items = Item.objects.filter(status=Item.Status.OPEN)
    if query:
        items = items.filter(public_type__icontains=query)
    data = [{
        "id": item.pk,
        "item_type": item.get_public_type_display(),
        "report_type": item.get_report_type_display(),
        "url": f"/items/{item.pk}/",
    } for item in items.only("id", "public_type", "report_type")[:12]]
    response = JsonResponse({"results": data})
    response["Cache-Control"] = "no-store"
    return response


@never_cache
def item_detail(request, pk):
    item = get_object_or_404(Item.objects.select_related("reported_by"), pk=pk)
    private_view = _is_private_viewer(request.user, item)
    # Closed records are not publicly enumerable. Their reporter and authorised
    # staff retain access; claimants see their own claim status on the dashboard.
    if not private_view and item.status != Item.Status.OPEN:
        raise Http404
    can_claim = bool(
        request.user.is_authenticated
        and not request.user.is_staff
        and item.report_type == Item.ReportType.FOUND
        and item.status == Item.Status.OPEN
        and item.reported_by_id != request.user.pk
    )
    existing_claim = None
    if request.user.is_authenticated and item.report_type == Item.ReportType.FOUND:
        existing_claim = Claim.objects.filter(item=item, claimant=request.user).first()

    claim_form = ClaimForm(user=request.user if request.user.is_authenticated else None, found_item=item)
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect("login")
        if not can_claim:
            messages.error(request, "You are not permitted to claim this report, or it is no longer accepting claims.")
            return redirect("item_detail", pk=item.pk)
        if existing_claim:
            messages.info(request, "You have already submitted a claim for this item.")
            return redirect("dashboard")

        claim_form = ClaimForm(request.POST, user=request.user, found_item=item)
        if claim_form.is_valid():
            try:
                with transaction.atomic():
                    locked_item = Item.objects.select_for_update().get(pk=item.pk)
                    if locked_item.status != Item.Status.OPEN or locked_item.reported_by_id == request.user.pk:
                        raise ValidationError("This item is no longer accepting claims.")
                    claim = claim_form.save(commit=False)
                    claim.item = locked_item
                    claim.claimant = request.user
                    claim.full_clean()
                    claim.save()
                messages.success(request, "Claim submitted. Only authorised staff can compare your answers with the private report.")
                return redirect("dashboard")
            except IntegrityError:
                claim_form.add_error(None, "You have already submitted a claim for this item.")
            except ValidationError as exc:
                claim_form.add_error(None, exc)

    context = {
        "item": item,
        "private_view": private_view,
        "private_image_url": f"/private/items/{item.pk}/image/" if private_view and item.image else None,
        "claim_form": claim_form,
        "existing_claim": existing_claim,
        "can_claim": can_claim,
        "can_manage_items": _can_manage_items(request.user),
        # Complete pairwise comparisons are available only to authorised staff.
        "matches": possible_matches(item) if _can_manage_items(request.user) else [],
    }
    return render(request, "core/item_detail.html", context)


@login_required
@never_cache
def private_item_image(request, pk):
    """Serve uploaded images only to the item's reporter or authorised staff."""
    item = get_object_or_404(Item, pk=pk)
    if not _is_private_viewer(request.user, item):
        raise Http404
    if not item.image:
        raise Http404
    extension = Path(item.image.name).suffix.lower()
    if extension not in PRIVATE_IMAGE_EXTENSIONS:
        raise Http404
    try:
        image_file = item.image.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404
    content_type = mimetypes.guess_type(item.image.name)[0] or "application/octet-stream"
    if not content_type.startswith("image/"):
        image_file.close()
        raise Http404
    response = FileResponse(image_file, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="item-{item.pk}{extension}"'
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@never_cache
def claim_review(request, pk):
    if not _can_review_claims(request.user):
        return HttpResponseForbidden("Claim-review permission required.")
    claim = get_object_or_404(
        Claim.objects.select_related("item", "claimant", "matched_lost_item", "item__reported_by"), pk=pk
    )
    if request.method == "POST":
        form = ClaimReviewForm(request.POST, instance=claim)
        if form.is_valid():
            try:
                save_claim_decision(
                    claim,
                    status=form.cleaned_data["status"],
                    admin_note=form.cleaned_data["admin_note"],
                )
            except ValidationError as exc:
                form.add_error("status", exc)
            except IntegrityError:
                form.add_error("status", "Another claim has already been approved for this item. Refresh and review the latest status.")
            else:
                messages.success(request, "Claim decision saved and item statuses synchronized.")
                return redirect("dashboard")
    else:
        form = ClaimReviewForm(instance=claim)
    return render(request, "core/claim_review.html", {"form": form, "claim": claim})


@login_required
def export_csv(request):
    if not _can_manage_items(request.user):
        return HttpResponseForbidden("Item-report permission required.")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="campusfind_items.csv"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    writer = csv.writer(response)
    writer.writerow(["ID", "Public Type", "Private Name", "Type", "Category", "Location", "Date", "Status", "Reported By"])
    for item in Item.objects.select_related("reported_by"):
        writer.writerow([item.id, item.get_public_type_display(), item.name, item.get_report_type_display(),
                         item.category, item.location, item.date_lost_found, item.get_status_display(), item.reported_by.username])
    return response


@login_required
def export_pdf(request):
    if not _can_manage_items(request.user):
        return HttpResponseForbidden("Item-report permission required.")
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, "CampusFind - Private Item Report")
    y -= 30
    pdf.setFont("Helvetica", 9)
    for item in Item.objects.select_related("reported_by"):
        line = f"#{item.id} | {item.name[:24]} | {item.get_report_type_display()} | {item.category[:16]} | {item.location[:22]} | {item.get_status_display()}"
        pdf.drawString(40, y, line)
        y -= 16
        if y < 45:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 9)
    pdf.save()
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="campusfind_private_report.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
