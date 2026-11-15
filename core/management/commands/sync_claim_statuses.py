from django.core.management.base import BaseCommand

from core.models import Claim
from core.services import sync_claim_item_states


class Command(BaseCommand):
    help = "Reconcile item statuses against already-approved or returned claims."

    def handle(self, *args, **options):
        claims = Claim.objects.filter(status__in=[Claim.Status.APPROVED, Claim.Status.RETURNED]).select_related(
            "item", "matched_lost_item"
        )
        count = 0
        for claim in claims.iterator():
            sync_claim_item_states(claim)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Synchronized item states for {count} approved/returned claim(s)."))
