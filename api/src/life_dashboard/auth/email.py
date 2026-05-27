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
