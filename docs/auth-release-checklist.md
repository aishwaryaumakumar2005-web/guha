# Authentication release checklist

Before deploying authentication changes:

- Confirm `SECRET_KEY` is set to a unique production value.
- Confirm `SESSION_COOKIE_SECURE=true` behavior is active behind HTTPS.
- Confirm SMTP settings are configured and reset emails are delivered.
- Confirm reset links expire and cannot be reused.
- Confirm login throttling is observable in audit logs.
- Confirm inactive accounts cannot authenticate.
- Confirm a production database contains the `user.is_active` and `password_reset_token` tables/columns.
- Run `pytest -q tests/test_auth.py tests/test_auth_security.py`.
- Verify `/login`, `/forgot-password`, `/change-password`, and `/logout` manually over HTTPS.
