from datetime import date, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings

from .matching import score_pair
from .models import Claim, Item
from .services import save_claim_decision


class MatchingEngineTests(TestCase):
    def setUp(self):
        self.lost = Item(
            public_type=Item.PublicType.PHONE,
            name="Apple iPhone 15 Pro",
            report_type=Item.ReportType.LOST,
            category="Electronics",
            description="Black Apple smartphone with triple rear camera and cracked screen protector",
            colour="Black",
            date_lost_found=date.today(),
            location="Library first floor",
            identifying_features="Small scratch near the volume button",
        )

    def test_unrelated_found_product_still_gets_visible_score_but_is_not_recommended(self):
        unrelated = Item(
            public_type=Item.PublicType.ACCESSORY,
            name="Wireless Bluetooth Earphones",
            report_type=Item.ReportType.FOUND,
            category="Electronics",
            description="White earbuds in a charging case",
            colour="White",
            date_lost_found=date.today(),
            location="Sports complex",
            identifying_features="Brand logo on charging case",
        )
        result = score_pair(self.lost, unrelated)
        self.assertIsNotNone(result)
        self.assertIn("score", result)
        self.assertFalse(result["recommendation_eligible"])

    def test_matching_phone_scores_above_unrelated_phone_accessory(self):
        likely = Item(
            public_type=Item.PublicType.PHONE,
            name="Apple iPhone 15 Pro mobile phone",
            report_type=Item.ReportType.FOUND,
            category="Electronics",
            description="Black Apple smartphone, triple camera, cracked screen protector",
            colour="Black",
            date_lost_found=date.today() + timedelta(days=1),
            location="Library floor one",
            identifying_features="Scratch beside volume button",
        )
        unrelated = Item(
            public_type=Item.PublicType.ACCESSORY,
            name="Bluetooth earphones",
            report_type=Item.ReportType.FOUND,
            category="Electronics",
            description="White wireless earbuds with a charging case",
            colour="White",
            date_lost_found=date.today(),
            location="Sports complex",
            identifying_features="Logo on charging case",
        )
        likely_result = score_pair(self.lost, likely)
        unrelated_result = score_pair(self.lost, unrelated)
        self.assertIsNotNone(likely_result)
        self.assertIsNotNone(unrelated_result)
        self.assertGreater(likely_result["score"], unrelated_result["score"])
        self.assertTrue(likely_result["recommendation_eligible"])
        self.assertFalse(unrelated_result["recommendation_eligible"])

    def test_incompatible_categories_do_not_hide_comparison_score(self):
        found = Item(
            public_type=Item.PublicType.BOOK,
            name="Steve Jobs biography",
            report_type=Item.ReportType.FOUND,
            category="Book",
            description="Black and white biography book",
            colour="Black and white",
            date_lost_found=date.today(),
            location="Cafe",
            identifying_features="Large biography book",
        )
        self.lost.category = "Stationery"
        result = score_pair(self.lost, found)
        self.assertIsNotNone(result)
        self.assertFalse(result["category_compatible"])
        self.assertFalse(result["recommendation_eligible"])


class ClaimWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="finder", password="test-password-123")
        self.claimant = User.objects.create_user(username="student", password="test-password-123")
        self.lost = Item.objects.create(
            public_type=Item.PublicType.LAPTOP,
            name="Private laptop identity", report_type=Item.ReportType.LOST, category="Electronics",
            description="Private lost report", date_lost_found=date.today(), location="Private lost location",
            reported_by=self.claimant,
        )
        self.found = Item.objects.create(
            public_type=Item.PublicType.LAPTOP,
            name="Secret MacBook Pro 14", report_type=Item.ReportType.FOUND, category="Electronics",
            description="Secret identifying description", colour="Space Grey", date_lost_found=date.today(),
            location="Room B-401", identifying_features="Tiny star sticker next to charging port",
            reported_by=self.owner,
        )
        self.claim = Claim.objects.create(
            item=self.found, claimant=self.claimant, matched_lost_item=self.lost,
            proof_description="I know the private sticker and charger details.",
        )

    def test_approval_claims_both_linked_records(self):
        save_claim_decision(self.claim, status=Claim.Status.APPROVED, admin_note="Verified")
        self.found.refresh_from_db()
        self.lost.refresh_from_db()
        self.assertEqual(self.found.status, Item.Status.CLAIMED)
        self.assertEqual(self.lost.status, Item.Status.CLAIMED)

    def test_return_marks_both_records_returned(self):
        save_claim_decision(self.claim, status=Claim.Status.APPROVED)
        save_claim_decision(self.claim, status=Claim.Status.RETURNED)
        self.found.refresh_from_db()
        self.lost.refresh_from_db()
        self.assertEqual(self.found.status, Item.Status.RETURNED)
        self.assertEqual(self.lost.status, Item.Status.RETURNED)

    def test_only_one_claim_for_an_item_can_be_approved(self):
        another_user = User.objects.create_user(username="another", password="test-password-123")
        second_claim = Claim.objects.create(
            item=self.found,
            claimant=another_user,
            proof_description="Another person's claim details.",
        )
        save_claim_decision(self.claim, status=Claim.Status.APPROVED)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            save_claim_decision(second_claim, status=Claim.Status.APPROVED)

    def test_rejected_claim_cannot_be_approved_again(self):
        from django.core.exceptions import ValidationError
        save_claim_decision(self.claim, status=Claim.Status.REJECTED)
        with self.assertRaises(ValidationError):
            save_claim_decision(self.claim, status=Claim.Status.APPROVED)


class PrivacyAndAccessControlTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="reporter", password="test-password-123")
        self.claimant = User.objects.create_user(username="claimant", password="test-password-123")
        self.staff = User.objects.create_superuser(username="moderator", email="moderator@example.com", password="test-password-123")
        self.item = Item.objects.create(
            public_type=Item.PublicType.LAPTOP,
            name="Secret Apple MacBook Pro 14",
            report_type=Item.ReportType.FOUND,
            category="Private category",
            description="Private description phrase not for public",
            colour="Private silver colour",
            date_lost_found=date.today(),
            location="Private Lab Room 401",
            identifying_features="Hidden star sticker and asset tag 88421",
            reported_by=self.owner,
        )
        self.client = Client()

    def test_public_browse_shows_only_broad_item_type(self):
        response = self.client.get("/items/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Laptop")
        for secret in ["Secret Apple MacBook Pro 14", "Private description phrase", "Private Lab Room 401", "88421"]:
            self.assertNotContains(response, secret)

    def test_public_detail_hides_private_fields_from_claimant(self):
        self.client.login(username="claimant", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Laptop")
        for secret in ["Secret Apple MacBook Pro 14", "Private description phrase", "Private Lab Room 401", "Hidden star sticker", "Private silver colour"]:
            self.assertNotContains(response, secret)

    def test_closed_item_is_not_publicly_enumerable(self):
        self.item.status = Item.Status.CLAIMED
        self.item.save(update_fields=["status"])
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_reporter_can_view_their_own_private_report(self):
        self.client.login(username="reporter", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertContains(response, "Secret Apple MacBook Pro 14")
        self.assertContains(response, "Private Lab Room 401")

    def test_authorised_staff_sees_all_opposite_type_scores_including_low_scores(self):
        lost = Item.objects.create(
            public_type=Item.PublicType.BOOK,
            name="Steve Jobs biography",
            report_type=Item.ReportType.LOST,
            category="Books",
            description="Biography of Steve Jobs",
            date_lost_found=date.today(),
            location="Library",
            reported_by=self.owner,
        )
        self.client.login(username="moderator", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lost / Found similarity comparisons")
        self.assertContains(response, f"Reference #{lost.pk}")
        self.assertContains(response, "/100")
        self.assertContains(response, "Comparison only")

    def test_non_authorised_user_does_not_see_match_comparisons(self):
        self.client.login(username="claimant", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertNotContains(response, "Lost / Found similarity comparisons")

    def test_staff_can_view_private_report(self):
        self.client.login(username="moderator", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertContains(response, "Secret Apple MacBook Pro 14")
        self.assertContains(response, "Hidden star sticker")

    def test_staff_without_item_permission_does_not_see_private_report(self):
        limited_staff = User.objects.create_user(
            username="limited-staff", password="test-password-123", is_staff=True
        )
        self.client.login(username="limited-staff", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertContains(response, "Laptop")
        self.assertNotContains(response, "Secret Apple MacBook Pro 14")

    def test_authorised_reporter_can_open_uploaded_private_image(self):
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="red").save(image_buffer, format="PNG")
        with TemporaryDirectory() as media_dir:
            with override_settings(MEDIA_ROOT=media_dir):
                self.item.image.save("private-evidence.png", ContentFile(image_buffer.getvalue()), save=True)
                private_url = f"/private/items/{self.item.pk}/image/"
                # Guessing the conventional MEDIA_URL must not bypass the private view.
                self.assertEqual(self.client.get(self.item.image.url).status_code, 404)
                self.client.login(username="claimant", password="test-password-123")
                self.assertEqual(self.client.get(private_url).status_code, 404)
                self.client.logout()
                self.client.login(username="reporter", password="test-password-123")
                response = self.client.get(private_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_search_does_not_search_or_return_private_fields(self):
        response = self.client.get("/api/search/", {"q": "MacBook"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        response = self.client.get("/api/search/", {"q": "Laptop"})
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["item_type"], "Laptop")
        for key in ["name", "location", "description", "colour", "image"]:
            self.assertNotIn(key, result)

    def test_unrelated_user_cannot_open_private_image_endpoint(self):
        self.client.login(username="claimant", password="test-password-123")
        response = self.client.get(f"/private/items/{self.item.pk}/image/")
        self.assertEqual(response.status_code, 404)

    def test_reporter_can_access_own_private_image_endpoint_only_when_image_exists(self):
        self.client.login(username="reporter", password="test-password-123")
        response = self.client.get(f"/private/items/{self.item.pk}/image/")
        self.assertEqual(response.status_code, 404)

    def test_uploaded_media_path_is_not_publicly_served(self):
        response = self.client.get("/media/items/guessed-private-image.jpg")
        self.assertEqual(response.status_code, 404)

    def test_found_reporter_cannot_claim_own_report(self):
        self.client.login(username="reporter", password="test-password-123")
        response = self.client.post(f"/items/{self.item.pk}/", {"proof_description": "I own it"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Claim.objects.filter(item=self.item, claimant=self.owner).exists())

    def test_admin_can_see_full_private_item_record(self):
        self.client.login(username="moderator", password="test-password-123")
        response = self.client.get(f"/admin/core/item/{self.item.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secret Apple MacBook Pro 14")
        self.assertContains(response, "Private Lab Room 401")

    def test_non_staff_user_cannot_open_admin_item_records(self):
        self.client.login(username="claimant", password="test-password-123")
        response = self.client.get(f"/admin/core/item/{self.item.pk}/change/")
        self.assertIn(response.status_code, (302, 403))

    def test_claim_review_requires_item_and_claim_permissions(self):
        claim = Claim.objects.create(
            item=self.item,
            claimant=self.claimant,
            proof_description="I can describe the hidden identifying mark.",
        )
        limited_staff = User.objects.create_user(
            username="review-limited", password="test-password-123", is_staff=True
        )
        self.client.login(username="review-limited", password="test-password-123")
        response = self.client.get(f"/claims/{claim.pk}/review/")
        self.assertEqual(response.status_code, 403)

    def test_ajax_search_and_public_home_do_not_leak_private_item_data(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for secret in ["Secret Apple MacBook Pro 14", "Private Lab Room 401", "88421"]:
            self.assertNotContains(response, secret)

    def test_item_detail_is_not_cached(self):
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertIn("no-store", response.get("Cache-Control", ""))

    def test_staff_with_item_view_permission_can_view_private_report(self):
        moderator = User.objects.create_user(
            username="item-moderator", password="test-password-123", is_staff=True
        )
        moderator.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_item"))
        self.client.login(username="item-moderator", password="test-password-123")
        response = self.client.get(f"/items/{self.item.pk}/")
        self.assertContains(response, "Secret Apple MacBook Pro 14")
        self.assertContains(response, "Private Lab Room 401")

    def test_staff_with_review_permissions_can_open_claim_review(self):
        claim = Claim.objects.create(
            item=self.item,
            claimant=self.claimant,
            proof_description="I can describe the hidden identifying mark on the laptop.",
        )
        moderator = User.objects.create_user(
            username="claim-moderator", password="test-password-123", is_staff=True
        )
        moderator.user_permissions.add(
            Permission.objects.get(content_type__app_label="core", codename="view_item"),
            Permission.objects.get(content_type__app_label="core", codename="change_claim"),
        )
        self.client.login(username="claim-moderator", password="test-password-123")
        response = self.client.get(f"/claims/{claim.pk}/review/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secret Apple MacBook Pro 14")
        self.assertContains(response, "hidden identifying mark")

    def test_admin_claim_record_is_read_only_and_routes_decisions_to_review(self):
        claim = Claim.objects.create(
            item=self.item,
            claimant=self.claimant,
            proof_description="I can describe the exact hidden mark and supplied adapter.",
        )
        self.client.login(username="moderator", password="test-password-123")
        response = self.client.get(f"/admin/core/claim/{claim.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "I can describe the exact hidden mark")
        self.assertContains(response, f"/claims/{claim.pk}/review/")
        # The status is displayed as read-only text, not an editable select/input.
        self.assertNotContains(response, 'name="status"')

    def test_private_exports_require_authorised_staff(self):
        self.client.login(username="claimant", password="test-password-123")
        self.assertEqual(self.client.get("/reports/items.csv").status_code, 403)
        self.assertEqual(self.client.get("/reports/items.pdf").status_code, 403)

