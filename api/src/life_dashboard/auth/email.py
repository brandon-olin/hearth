"""Transactional email via Mailgun.

All functions raise EmailSendError on failure so callers can surface a
meaningful message without catching httpx internals.
"""

import logging

import httpx

from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    """Raised when Mailgun returns a non-2xx response or is not configured."""


def _configured() -> bool:
    return bool(settings.mailgun_api_key and settings.mailgun_domain and settings.mailgun_from_email)


async def send_verification_email(to_email: str, code: str) -> None:
    """Send a 6-digit verification OTP to the given address.

    Raises EmailSendError if Mailgun is not configured or the send fails.
    """
    if not _configured():
        # In development without Mailgun configured, log the code so testing
        # isn't blocked. Production should always have credentials set.
        logger.warning(
            "Mailgun not configured — verification code for %s: %s", to_email, code
        )
        if settings.environment == "development":
            return  # allow dev flow to continue without email
        raise EmailSendError(
            "Email service is not configured. Set MAILGUN_API_KEY, MAILGUN_DOMAIN, "
            "and MAILGUN_FROM_EMAIL in your environment."
        )

    url = f"https://api.mailgun.net/v3/{settings.mailgun_domain}/messages"

    text_body = (
        f"Your Hearth verification code is: {code}\n\n"
        f"Enter this code on the verification page to complete your registration.\n"
        f"The code expires in 15 minutes.\n\n"
        f"If you didn't create a Hearth account, you can safely ignore this email."
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:0">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;margin:40px auto;padding:0 16px">
    <tr><td>
      <p style="font-size:22px;font-weight:600;margin:0 0 8px">Verify your email</p>
      <p style="color:#555;margin:0 0 32px">Enter this code to complete your Hearth registration:</p>
      <div style="background:#f5f5f5;border-radius:10px;padding:24px;text-align:center;letter-spacing:10px;font-size:36px;font-weight:700;font-variant-numeric:tabular-nums">
        {code}
      </div>
      <p style="color:#888;font-size:13px;margin:24px 0 0">
        This code expires in 15&nbsp;minutes. If you didn&rsquo;t create a Hearth account, you can safely ignore this email.
      </p>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                auth=("api", settings.mailgun_api_key),
                data={
                    "from": settings.mailgun_from_email,
                    "to": to_email,
                    "subject": f"Your Hearth verification code: {code}",
                    "text": text_body,
                    "html": html_body,
                },
                timeout=10.0,
            )
        response.raise_for_status()
        logger.info("Verification email sent to %s (Mailgun id: %s)", to_email, response.json().get("id"))
    except httpx.HTTPStatusError as exc:
        logger.error("Mailgun send failed: %s — %s", exc.response.status_code, exc.response.text)
        raise EmailSendError(f"Failed to send verification email (status {exc.response.status_code})") from exc
    except httpx.RequestError as exc:
        logger.error("Mailgun request error: %s", exc)
        raise EmailSendError("Failed to reach email service. Please try again.") from exc


async def send_invite_email(
    to_email: str,
    invited_by_name: str,
    household_name: str,
    set_password_url: str,
) -> None:
    """Send a household invitation email.

    The invited user clicks set_password_url, sets their password, and is
    directed into the onboarding flow. The link embeds a one-time reset token
    so no temp password ever needs to be shared.

    Raises EmailSendError if Mailgun is not configured or the send fails.
    """
    if not _configured():
        logger.warning("Mailgun not configured — invite email not sent to %s", to_email)
        if settings.environment == "development":
            return
        raise EmailSendError(
            "Email service is not configured. Set MAILGUN_API_KEY, MAILGUN_DOMAIN, "
            "and MAILGUN_FROM_EMAIL in your environment."
        )

    text_body = (
        f"{invited_by_name} has invited you to join {household_name!r} on Hearth.\n\n"
        f"Click the link below to set your password and get started:\n{set_password_url}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you weren't expecting this invitation, you can safely ignore this email."
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:0">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;margin:40px auto;padding:0 16px">
    <tr><td>
      <p style="font-size:22px;font-weight:600;margin:0 0 8px">You&rsquo;re invited to Hearth</p>
      <p style="color:#555;margin:0 0 24px">
        <strong>{invited_by_name}</strong> has invited you to join
        <strong>{household_name}</strong>.
      </p>
      <a href="{set_password_url}" style="display:inline-block;background:#111;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600">
        Accept invitation
      </a>
      <p style="color:#888;font-size:13px;margin:24px 0 0">
        This link expires in 1&nbsp;hour. Click it to set your password and get started.
      </p>
      <p style="color:#bbb;font-size:12px;margin:8px 0 0">
        If you weren&rsquo;t expecting this invitation, you can safely ignore this email.
      </p>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.mailgun.net/v3/{settings.mailgun_domain}/messages",
                auth=("api", settings.mailgun_api_key),
                data={
                    "from": settings.mailgun_from_email,
                    "to": to_email,
                    "subject": f"You've been invited to {household_name} on Hearth",
                    "text": text_body,
                    "html": html_body,
                },
                timeout=10.0,
            )
        resp.raise_for_status()
        logger.info("Invite email sent to %s (Mailgun id: %s)", to_email, resp.json().get("id"))
    except httpx.HTTPStatusError as exc:
        logger.error("Mailgun invite send failed: %s — %s", exc.response.status_code, exc.response.text)
        raise EmailSendError(f"Failed to send invite email (status {exc.response.status_code})") from exc
    except httpx.RequestError as exc:
        logger.error("Mailgun invite request error: %s", exc)
        raise EmailSendError("Failed to reach email service. Please try again.") from exc


async def send_password_reset_email(to_email: str, reset_url: str) -> None:
    """Send a password reset link.

    Only called on the cloud tier. reset_url includes the raw token as a query param.
    Raises EmailSendError if Mailgun is not configured or the send fails.
    """
    if not _configured():
        logger.warning("Mailgun not configured — reset URL for %s: %s", to_email, reset_url)
        if settings.environment == "development":
            return
        raise EmailSendError(
            "Email service is not configured. Set MAILGUN_API_KEY, MAILGUN_DOMAIN, "
            "and MAILGUN_FROM_EMAIL in your environment."
        )

    text_body = (
        f"You requested a password reset for your Hearth account.\n\n"
        f"Click the link below to set a new password:\n{reset_url}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you didn't request a password reset, you can safely ignore this email."
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:0">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;margin:40px auto;padding:0 16px">
    <tr><td>
      <p style="font-size:22px;font-weight:600;margin:0 0 8px">Reset your password</p>
      <p style="color:#555;margin:0 0 24px">Click the button below to set a new password for your Hearth account.</p>
      <a href="{reset_url}" style="display:inline-block;background:#111;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600">
        Reset password
      </a>
      <p style="color:#888;font-size:13px;margin:24px 0 0">
        This link expires in 1&nbsp;hour. If you didn&rsquo;t request a password reset,
        you can safely ignore this email.
      </p>
    </td></tr>
  </table>
</body>
</html>"""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.mailgun.net/v3/{settings.mailgun_domain}/messages",
                auth=("api", settings.mailgun_api_key),
                data={
                    "from": settings.mailgun_from_email,
                    "to": to_email,
                    "subject": "Reset your Hearth password",
                    "text": text_body,
                    "html": html_body,
                },
                timeout=10.0,
            )
        resp.raise_for_status()
        logger.info("Password reset email sent to %s", to_email)
    except httpx.HTTPStatusError as exc:
        logger.error("Mailgun reset send failed: %s — %s", exc.response.status_code, exc.response.text)
        raise EmailSendError(f"Failed to send reset email (status {exc.response.status_code})") from exc
    except httpx.RequestError as exc:
        logger.error("Mailgun reset request error: %s", exc)
        raise EmailSendError("Failed to reach email service. Please try again.") from exc
