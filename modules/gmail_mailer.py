"""Gmail SMTP/API sender. Credentials are read only from environment settings."""
import base64
import json
from email.message import EmailMessage
import smtplib
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MailDeliveryError(RuntimeError):
    pass


def _post(url, payload, headers=None):
    request = Request(url, data=payload, headers=headers or {}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MailDeliveryError("電子郵件服務暫時無法使用。") from exc


def _build_message(settings, recipient, subject, body):
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = settings["GMAIL_SENDER_EMAIL"]
    message["Subject"] = subject
    message.set_content(body)
    return message


def _send_smtp(settings, recipient, subject, body):
    required = ("GMAIL_SENDER_EMAIL", "GMAIL_SMTP_APP_PASSWORD")
    if any(not settings.get(name) for name in required):
        raise MailDeliveryError("電子郵件寄送尚未設定。")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(settings["GMAIL_SENDER_EMAIL"], settings["GMAIL_SMTP_APP_PASSWORD"])
            server.send_message(_build_message(settings, recipient, subject, body))
    except Exception as exc:
        raise MailDeliveryError("電子郵件服務暫時無法使用。") from exc


def _send_gmail_api(settings, recipient, subject, body):
    required = ("GMAIL_SENDER_EMAIL", "GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_SECRET", "GMAIL_OAUTH_REFRESH_TOKEN")
    if not settings.get("GMAIL_API_ENABLED") or any(not settings.get(name) for name in required):
        raise MailDeliveryError("電子郵件寄送尚未設定。")

    token = _post(
        "https://oauth2.googleapis.com/token",
        urlencode({
            "client_id": settings["GMAIL_OAUTH_CLIENT_ID"],
            "client_secret": settings["GMAIL_OAUTH_CLIENT_SECRET"],
            "refresh_token": settings["GMAIL_OAUTH_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }).encode("utf-8"),
        {"Content-Type": "application/x-www-form-urlencoded"},
    ).get("access_token")
    if not token:
        raise MailDeliveryError("電子郵件服務授權失敗。")

    message = _build_message(settings, recipient, subject, body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    _post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        json.dumps({"raw": raw}).encode("utf-8"),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def send_email(settings, recipient, subject, body):
    """Send through SMTP when configured; Gmail API remains an optional fallback."""
    if settings.get("GMAIL_SMTP_ENABLED"):
        return _send_smtp(settings, recipient, subject, body)
    return _send_gmail_api(settings, recipient, subject, body)
