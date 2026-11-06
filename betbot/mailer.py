"""Αποστολή email μέσω SMTP (π.χ. Gmail με App Password).

Μεταβλητές περιβάλλοντος (GitHub → Settings → Secrets):
  SMTP_HOST (προεπιλογή smtp.gmail.com), SMTP_PORT (587), SMTP_USER, SMTP_PASS, MAIL_TO

Το email έχει: σύνοψη (Προτεινόμενο, Μονό, 10+, 30+, 100+) + συνημμένη ΟΛΗ τη σελίδα
(BetBot-ΗΗΗΗ-ΜΜ-ΗΗ.html) με όλες τις καρτέλες. Την ανοίγεις με διπλό κλικ.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send(subject: str, html_body: str, images: dict, to: str, attachments: dict | None = None):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user, pwd = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or to
    if not (user and pwd and to):
        raise RuntimeError("Λείπουν SMTP_USER / SMTP_PASS / παραλήπτης (MAIL_TO)")
    msg = MIMEMultipart("mixed")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    related = MIMEMultipart("related")
    related.attach(MIMEText(html_body, "html", "utf-8"))
    for cid, png in images.items():
        img = MIMEImage(png, "png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        related.attach(img)
    msg.attach(related)
    for name, data in (attachments or {}).items():
        part = MIMEApplication(data, Name=name)
        part.add_header("Content-Disposition", "attachment", filename=name)
        msg.attach(part)
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
