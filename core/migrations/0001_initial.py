# Initial CampusFind database schema.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Item",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_type", models.CharField(choices=[("LAPTOP", "Laptop"), ("PHONE", "Phone"), ("TABLET", "Tablet"), ("BOOK", "Book"), ("BAG", "Bag"), ("WALLET", "Wallet"), ("KEYS", "Keys"), ("BOTTLE", "Bottle"), ("CLOTHING", "Clothing"), ("ACCESSORY", "Accessory"), ("OTHER", "Other item")], default="OTHER", help_text="Broad object type shown publicly (e.g. Laptop, Book or Bag). Do not include a brand/model here.", max_length=12)),
                ("name", models.CharField(max_length=120)),
                ("report_type", models.CharField(choices=[("LOST", "Lost"), ("FOUND", "Found")], max_length=5)),
                ("category", models.CharField(max_length=80)),
                ("description", models.TextField()),
                ("colour", models.CharField(blank=True, max_length=50)),
                ("date_lost_found", models.DateField()),
                ("location", models.CharField(max_length=150)),
                ("identifying_features", models.TextField(blank=True)),
                ("image", models.ImageField(blank=True, null=True, upload_to="items/")),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("CLAIMED", "Claimed"), ("RETURNED", "Returned"), ("CLOSED", "Closed")], default="OPEN", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reported_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="item_reports", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Claim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("proof_description", models.TextField(help_text="Describe details that only the genuine owner would know. Never include passwords or account recovery codes.")),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("VERIFYING", "Under Verification"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("RETURNED", "Returned")], default="PENDING", max_length=12)),
                ("admin_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("claimant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="claims", to=settings.AUTH_USER_MODEL)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="claims", to="core.item")),
                ("matched_lost_item", models.ForeignKey(blank=True, help_text="Optional link to your own lost-item report.", limit_choices_to={"report_type": "LOST"}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="linked_claims", to="core.item")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="item", index=models.Index(fields=["report_type", "status"], name="idx_item_report_status")),
        migrations.AddIndex(model_name="item", index=models.Index(fields=["category", "status"], name="idx_item_category_status")),
        migrations.AddIndex(model_name="item", index=models.Index(fields=["public_type", "status"], name="idx_item_public_status")),
        migrations.AddIndex(model_name="claim", index=models.Index(fields=["status", "created_at"], name="idx_claim_status_created")),
        migrations.AddConstraint(model_name="claim", constraint=models.UniqueConstraint(fields=("item", "claimant"), name="one_claim_per_user_per_item")),
        migrations.AddConstraint(model_name="claim", constraint=models.UniqueConstraint(condition=models.Q(status__in=["APPROVED", "RETURNED"]), fields=("item",), name="one_finalized_claim_per_item")),
    ]
