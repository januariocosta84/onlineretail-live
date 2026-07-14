# TimorMart

A Django marketplace for Timor-Leste: sellers register, list products (pending
admin approval), and buyers browse, search, and comment. English and Tetum UI.

## Requirements

- Python 3.11+ (tested on 3.13)
- Dependencies in `requirements.txt` (Django 5.2 LTS)

## Run locally

```powershell
python -m venv .venv               # put the venv OUTSIDE OneDrive if possible
.venv\Scripts\pip install -r requirements.txt
$env:DJANGO_DEBUG = "true"
python manage.py migrate
python manage.py runserver
```

Admin: `/admin/` (superuser: `jcosta`; create one with `manage.py createsuperuser`).

## Environment variables (production)

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | **Required** in production |
| `DJANGO_DEBUG` | `true` only for local development |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated `https://...` origins |
| `DJANGO_SSL_REDIRECT` | `true` when behind HTTPS (enables HSTS + secure cookies) |
| `EMAIL_HOST` etc. | SMTP for password-reset email (console backend otherwise) |

## Notes

- Product listings require admin approval (`approved` flag) before they appear
  in the catalog. Approve via the Products admin bulk action.
- Static files are served by WhiteNoise (`manage.py collectstatic` on deploy).
- Uploaded media lives in `media/`; move to object storage (e.g. S3) before
  scaling beyond a single server.
- Tetum uses language code `tet` (`locale/tet/`). The legacy `tt` code was
  renamed because `tt` is Tatar in Django.
