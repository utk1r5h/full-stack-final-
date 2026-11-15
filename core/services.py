"""Transactional claim workflow and item-state synchronization."""
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Claim, Item

ACTIVE_CLAIM_STATUSES = (Claim.Status.APPROVED, Claim.Status.RETURNED)


@transaction.atomic
def sync_claim_item_states(claim: Claim, previous_lost_item_id=None) -> None:
    """Keep found/lost report states consistent with claim decisions.

    This function is called by both the CampusFind review page and Django Admin,
    preventing one interface from bypassing the status synchronization.
    """
    found_item = Item.objects.select_for_update().get(pk=claim.item_id)
    found_claims = Claim.objects.filter(item_id=found_item.pk)
    if found_claims.filter(status=Claim.Status.RETURNED).exists():
        new_found_status = Item.Status.RETURNED
    elif found_claims.filter(status=Claim.Status.APPROVED).exists():
        new_found_status = Item.Status.CLAIMED
    else:
        new_found_status = Item.Status.OPEN if found_item.status in (Item.Status.CLAIMED, Item.Status.RETURNED) else found_item.status
    if found_item.status != new_found_status:
        found_item.status = new_found_status
        found_item.save(update_fields=["status"])

    affected_lost_ids = {claim.matched_lost_item_id}
    if previous_lost_item_id:
        affected_lost_ids.add(previous_lost_item_id)
    affected_lost_ids.discard(None)

    for lost_id in affected_lost_ids:
        lost_item = Item.objects.select_for_update().filter(pk=lost_id, report_type=Item.ReportType.LOST).first()
        if not lost_item:
            continue
        linked_claims = Claim.objects.filter(matched_lost_item_id=lost_id)
        if linked_claims.filter(status=Claim.Status.RETURNED).exists():
            new_status = Item.Status.RETURNED
        elif linked_claims.filter(status=Claim.Status.APPROVED).exists():
            new_status = Item.Status.CLAIMED
        else:
            new_status = Item.Status.OPEN if lost_item.status in (Item.Status.CLAIMED, Item.Status.RETURNED) else lost_item.status
        if lost_item.status != new_status:
            lost_item.status = new_status
            lost_item.save(update_fields=["status"])


@transaction.atomic
def save_claim_decision(claim: Claim, *, status: str, admin_note: str = "") -> Claim:
    """Persist a decision and synchronize report states atomically."""
    old_lost_item_id = claim.matched_lost_item_id
    locked_claim = Claim.objects.select_for_update().get(pk=claim.pk)
    if status not in Claim.ALLOWED_TRANSITIONS.get(locked_claim.status, set()):
        raise ValidationError(f"A claim cannot move from {locked_claim.status} to {status}.")
    if status in (Claim.Status.APPROVED, Claim.Status.RETURNED):
        competing_decision = Claim.objects.filter(
            item_id=locked_claim.item_id,
            status__in=(Claim.Status.APPROVED, Claim.Status.RETURNED),
        ).exclude(pk=locked_claim.pk).exists()
        if competing_decision:
            raise ValidationError("Another claim for this found item has already been approved/returned.")
    locked_claim.status = status
    locked_claim.admin_note = admin_note
    locked_claim.save(update_fields=["status", "admin_note"])
    sync_claim_item_states(locked_claim, previous_lost_item_id=old_lost_item_id)
    claim.refresh_from_db()
    return claim
