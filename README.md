# CampusFind – Smart Lost & Found Management System

A Django application for a college lost-and-found process. This build adds **server-side privacy controls** so a person browsing the site sees only a broad item type (for example, Laptop, Book or Bag), while the reporter and authorised staff can see the full report.

## Main features

- User registration, login and personal dashboard
- Lost and found report creation with optional private image upload
- Public browse and AJAX search that reveal only broad item type, Lost/Found status and reference number
- Private item name, category, description, colour, date, exact location, identifying features and photo
- Staff-only Django Admin management of complete item reports and claims
- Private claim submissions with a required 30–2,000 character ownership explanation and optional link to the claimant's own lost report
- Claim states: Pending, Under Verification, Approved, Rejected and Returned
- Admin review page that compares submitted ownership evidence with the original private found report
- Only one claim can be approved/returned per found item; claim states cannot move backwards from Rejected or Returned
- Claim decisions synchronise found and linked lost report statuses
- Explainable hybrid lost/found matching engine, with match details restricted to authorised item staff
- CSV/PDF exports protected by staff permission checks
- Uploaded image endpoint that checks reporter/staff access; no public `/media/` serving route

## Privacy and access rules

| Data | Public visitor / claimant | Original reporter | Authorised item staff / superuser |
|---|---:|---:|---:|
| Broad item type (Laptop, Book, Bag, etc.) | Yes | Yes | Yes |
| Lost / Found and report reference | Yes | Yes | Yes |
| Exact item name / brand / model | No | Own report only | Yes |
| Description, colour and date | No | Own report only | Yes |
| Exact location and identifying features | No | Own report only | Yes |
| Uploaded photograph | No | Own report only | Yes |
| All claims and internal admin notes | No | Own claims only (status) | Yes |
| Matching score and internal match suggestions | No | No | Yes |

Privacy is enforced in Django views and the private image endpoint, not merely by hiding HTML. Public search only queries the broad `public_type` field. Claimants cannot read the hidden fields from the item-detail page or AJAX response. A claimant's own linked lost-item report can be selected in the claim form, but other users' reports are not exposed.

**Claim matching is not ownership verification.** A high similarity score never approves a claim. Staff must manually compare evidence the claimant submits with the original private report. Do not store account passwords, OTPs or account recovery codes in item evidence.

## Run in VS Code (Windows)

1. Extract the ZIP and open the project folder (the one containing `manage.py`) in VS Code.
2. Open **Terminal → New Terminal**.
3. Create and activate a virtual environment:

   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\venv\Scripts\Activate.ps1
   ```

4. Install the required packages:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Create the database tables from the included initial migration:

   ```powershell
   python manage.py migrate
   ```

6. Create the admin account:

   ```powershell
   python manage.py createsuperuser
   ```

7. Start the local server:

   ```powershell
   python manage.py runserver
   ```

8. Open `http://127.0.0.1:8000/` for the website and `http://127.0.0.1:8000/admin/` for Django Admin.

## Admin workflow

For a simple college demo, use the superuser created with `python manage.py createsuperuser`. For a separate moderator account, create the user in Django Admin, enable **Staff status**, and assign the `core | item | Can view item` and `core | claim | Can change claim` permissions. The `Can view item` permission grants access to full private item records; both permissions are required for claim review. Give `Can change item` only to staff who should edit item records. Ordinary registered users must not be marked as staff.

1. Sign in to `/admin/` using a superuser or a staff account granted the relevant Item and Claim permissions.
2. Open **Items** to see complete private reports, including exact location, descriptions and identifying features. The uploaded image is shown through a protected image link; the raw `/media/` file link is intentionally not rendered.
3. Open **Claims** or the **Dashboard → Claims requiring attention** queue. Claim records are read-only in the list/detail page so status changes cannot bypass the controlled workflow.
4. Open **Review evidence and decide** and compare the claimant's answers with the original found report and, when linked, the claimant's own lost report.
5. Set Under Verification, Approved or Rejected. Mark Returned only after the item has physically been handed over. The application synchronises the found report and linked lost report statuses.
6. Keep internal admin notes factual. They are not shown to claimants. Claims cannot be created or deleted through Admin; they must originate from a logged-in claimant.

## Image privacy

The project deliberately does not register a public media-serving URL. The Admin item form also avoids rendering Django’s default raw file link; it offers only the permission-checked image route. Uploaded images are streamed by `/private/items/<id>/image/` only after checking that the requester is the original reporter or an authorised staff member. The Django development server must be used as documented; do not add a public `static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` route. A production web server or object-storage bucket must also **not** expose the `media/` directory publicly.

## Updating an existing local CampusFind database

If you are replacing an older copy that already has `db.sqlite3` and migration files:

- Back up `db.sqlite3` and your existing `core/migrations/` folder first.
- Copy the updated `core`, `config` and `templates` files from this project over your old source.
- **Keep your existing database and existing migration files.** Do not delete old migrations or replace the database with a fresh one.
- In the existing virtual environment, run:

  ```powershell
  python -m pip install -r requirements.txt
  python manage.py makemigrations core
  python manage.py migrate
  python manage.py runserver
  ```

The new migration adds the broad public item type to existing records with the default `Other item`. Edit old reports in Django Admin and set their correct public type (Laptop, Phone, Book, Bag, etc.). Their exact names and other details remain private.

If you are using this ZIP in a brand-new folder/database, follow all Run in VS Code steps instead. This ZIP includes `core/migrations/0001_initial.py`; do not run `makemigrations` on a fresh install unless you have changed the models.

## Tests

Run the tests from the project folder:

```powershell
python manage.py test core
```

The tests cover matching behaviour, claim-state synchronisation, public-field minimisation, permission-controlled private details, admin access, claim-review permissions, AJAX response minimisation, cache controls and non-public media paths.

## Development versus production

This ZIP is a **privacy-hardened academic project build**, not a guarantee of production-grade security. It reduces information available to a dishonest claimant, but no matching algorithm or form can prove ownership by itself: staff must check the submitted evidence and use a safe handover process. Run locally for your PBL demo. Before deploying to a public server, set a unique `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, correct `DJANGO_ALLOWED_HOSTS`, HTTPS, secure database credentials, private media storage, backups, logging and monitoring. Set environment variables rather than editing secrets into source code. Review the hosting provider's media/static configuration so private uploaded files cannot be served directly.

Example production environment variables (replace values):

```text
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=campusfind.example.edu
DJANGO_HSTS_SECONDS=31536000
```


## Authorised staff: complete Lost/Found similarity comparisons

On an individual item detail page, authorised staff (superusers or staff users
with the `core.view_item` permission) now see a similarity score for every
report of the opposite type. The list is not restricted to OPEN records and
does not suppress low scores, incompatible categories, or reports linked to
resolved claims. Each row includes a score breakdown, data coverage, warnings,
and a separate recommendation-eligibility indicator.

The original field weights, similarity functions, mismatch penalties, and
42/100 recommendation threshold are retained. The threshold and identity /
category checks now affect only `recommendation_eligible`; they no longer
remove the comparison from staff visibility. The displayed score is a
similarity ranking, not a probability or proof of ownership.

Non-authorised users do not receive comparison results in the view context,
and the template checks the same `can_manage_items` permission flag.
