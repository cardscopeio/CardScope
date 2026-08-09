"""
Transactional email for CardScope.io - password reset links, for now.

Simplest option, deliberately: reuses the cardscope.io@gmail.com account that
already exists (it's the site's own contact address, see contact.html) via
Gmail's SMTP server and an "App Password" - not a new third-party email
service, no new vendor relationship, no new API key to manage. Fine for the
current volume (password resets, low frequency). If CardScope ever needs
real marketing-email volume or better deliverability guarantees, a real
transactional provider (Resend, SendGrid, Postmark) is the upgrade path -
not needed yet.

Requires two env vars on Render:
  GMAIL_SENDER_EMAIL     - the sending address, e.g. cardscope.io@gmail.com
  GMAIL_APP_PASSWORD     - a 16-character Gmail "App Password" (NOT the
                            regular account password - Gmail requires
                            2-Step Verification enabled first, then generate
                            this at myaccount.google.com/apppasswords)

If either var is missing, send_email() logs a warning and returns False
instead of crashing the request - a misconfigured mail server shouldn't take
the whole password-reset flow down harder than it needs to (the caller
still gets a clean error to show the user).
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_SENDER_EMAIL = os.environ.get("GMAIL_SENDER_EMAIL")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(to_email: str, subject: str, body_text: str, body_html: str = None) -> bool:
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        print(
            "WARNING: GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD not set - "
            "cannot send email. Set both env vars on Render to enable "
            "password reset emails."
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_SENDER_EMAIL
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"WARNING: failed to send email to {to_email}: {e}")
        return False


def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    subject = "Reset your CardScope.io password"
    text = (
        f"Someone requested a password reset for this CardScope.io account.\n\n"
        f"Reset your password here (link expires in 1 hour):\n{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email - "
        f"your password won't change unless you click the link above and "
        f"set a new one."
    )
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
        <h2 style="color: #667eea;">Reset your CardScope.io password</h2>
        <p>Someone requested a password reset for this account.</p>
        <p style="margin: 24px 0;">
            <a href="{reset_link}" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
               color: white; padding: 14px 28px; border-radius: 10px; text-decoration: none;
               font-weight: 600; display: inline-block;">Reset Password</a>
        </p>
        <p style="color: #8899a6; font-size: 0.9em;">This link expires in 1 hour.</p>
        <p style="color: #8899a6; font-size: 0.9em;">
            If you didn't request this, you can safely ignore this email -
            your password won't change unless you click the button above.
        </p>
    </div>
    """
    return send_email(to_email, subject, text, html)
