"""Send email over SMTP (Gmail/Yahoo) with the app password stored in the vault."""

import mimetypes
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from loguru import logger

from linkit_all.apply.email_verify import credentials
from linkit_all.apply.vault import Vault
from linkit_all.core.search import EmailSection

_ADDRESS = re.compile(
    r"^[^@\s<>,;\"()\[\]\\]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$"
)


class SmtpError(Exception):
    """Sending failed; the message is safe to show the user."""


class SmtpAuthError(SmtpError):
    """The server rejected the login."""


class NoCredentials(SmtpError):
    """No email credentials in the vault."""


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    body: str
    attachments: list[Path] = field(default_factory=list)
    reply_to: str | None = None


def _clean_header(name: str, value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{name} must not contain line breaks")
    return value.strip()


def _address(name: str, value: str) -> str:
    value = _clean_header(name, value)
    if not _ADDRESS.match(value):
        raise ValueError(f"{name} is not a single valid email address")
    return value


def build_message(sender_name: str, sender: str, mail: OutgoingEmail) -> EmailMessage:
    sender = _address("sender", sender)
    to = _address("to", mail.to)
    reply_to = _address("reply_to", mail.reply_to) if mail.reply_to else None
    msg = EmailMessage()
    msg["From"] = formataddr((_clean_header("sender name", sender_name), sender))
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = _clean_header("subject", mail.subject)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[1])
    msg.set_content(mail.body)
    for path in mail.attachments:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    return msg


def save_eml(msg: EmailMessage, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(msg))
    return path


def send(cfg: EmailSection, vault: Vault, profile_email: str, msg: EmailMessage) -> str:
    """Send msg as the vault's mailbox user; returns the Message-ID."""
    creds = credentials(cfg, vault, profile_email)
    if creds is None:
        raise NoCredentials("No email connected yet")
    user, password = creds
    host = cfg.effective_smtp_host()
    message_id = str(msg["Message-ID"])
    domain = str(msg["To"]).rsplit("@", 1)[-1]
    try:
        with smtplib.SMTP_SSL(
            host, cfg.smtp_port, timeout=30, context=ssl.create_default_context()
        ) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise SmtpAuthError(
            f"{host} rejected the login: check the app password and email address"
        ) from None
    except (OSError, smtplib.SMTPException) as e:
        logger.warning("SMTP send failed ({})", type(e).__name__)
        raise SmtpError(f"Could not send through {host} ({type(e).__name__})") from None
    logger.info("Email sent to *@{} ({})", domain, message_id)
    return message_id
