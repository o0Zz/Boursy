"""Push (ntfy) and email (SMTP) notifications, logged in the `notifications` table."""

import logging
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.appconfig import NotifyParams
from boursy.config import Settings
from boursy.db.models import Notification

log = logging.getLogger(__name__)

# kind -> (push priority or None for no push, send email)
ROUTING: dict[str, tuple[str | None, bool]] = {
    "proposal": ("high", True),
    "stop_hit": ("urgent", True),
    "large_move": ("high", True),
    "thesis_break": ("high", True),
    "kill_switch": ("urgent", True),
    "expiring": ("default", False),
    "weekly_summary": (None, True),
    "reconciliation": ("default", True),
    "job_failure": ("default", False),
    "test": ("default", True),
}


class Notifier:
    def __init__(self, settings: Settings, params: NotifyParams):
        self.s = settings
        self.p = params

    @property
    def push_configured(self) -> bool:
        return bool(self.s.ntfy_topic)

    @property
    def email_configured(self) -> bool:
        return bool(self.s.smtp_host and self.s.mail_to)

    def send(
        self,
        session: Session,
        kind: str,
        title: str,
        body: str,
        path: str = "/",
        dedupe_key: str | None = None,
    ) -> Notification | None:
        """Send on the channels configured for `kind`. With `dedupe_key`, send at most once."""
        if dedupe_key and session.scalar(
            select(Notification.id).where(Notification.dedupe_key == dedupe_key)
        ):
            return None
        priority, email = ROUTING.get(kind, ("default", False))
        row = Notification(kind=kind, title=title[:256], body=body, dedupe_key=dedupe_key)
        errors = []
        link = f"{self.s.public_url.rstrip('/')}{path}" if self.s.public_url else None
        if priority and self.p.push and self.push_configured:
            try:
                self._push(title, body, priority, link)
                row.push_status = "sent"
            except Exception as exc:
                row.push_status = "failed"
                errors.append(f"push: {exc}")
        if email and self.p.email and self.email_configured:
            try:
                self._email(title, body + (f"\n\n{link}" if link else ""))
                row.email_status = "sent"
            except Exception as exc:
                row.email_status = "failed"
                errors.append(f"email: {exc}")
        row.error = "; ".join(errors)[:1000] or None
        if errors:
            log.warning("Notification %s: %s", kind, row.error)
        session.add(row)
        session.commit()
        return row

    def _push(self, title: str, body: str, priority: str, link: str | None) -> None:
        headers = {"Title": title.encode("utf-8"), "Priority": priority, "Tags": "chart_with_upwards_trend"}
        if link:
            headers["Click"] = link
            headers["Actions"] = f"view, Open Boursy, {link}"
        if self.s.ntfy_token:
            headers["Authorization"] = f"Bearer {self.s.ntfy_token}"
        url = f"{self.s.ntfy_url.rstrip('/')}/{self.s.ntfy_topic}"
        r = httpx.post(url, content=body.encode("utf-8"), headers=headers, timeout=15)
        r.raise_for_status()

    def _email(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[Boursy] {subject}"
        msg["From"] = self.s.smtp_from or self.s.smtp_user
        msg["To"] = self.s.mail_to
        msg.set_content(body)
        if self.s.smtp_port == 465:
            server = smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20)
            server.starttls()
        with server:
            if self.s.smtp_user:
                server.login(self.s.smtp_user, self.s.smtp_password)
            server.send_message(msg)
