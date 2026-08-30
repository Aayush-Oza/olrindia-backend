# OLR India - Email Utilities
# Handles all transactional emails via Resend
# 1. Magic link for email verification (registration)
# 2. Password reset link (forgot password)

import resend
from flask import current_app


def send_verification_email(to_email: str, name: str, token: str, role: str = "user") -> bool:
    """
    Send magic link email for account verification after registration.

    Args:
        to_email: Recipient email address
        name: Recipient's name (for personalization)
        token: Secure verification token
        role: "user" or "vendor" - determines which frontend folder the link points to

    Returns:
        True if sent successfully, False if failed
    """
    try:
        # Set Resend API key
        resend.api_key = current_app.config["RESEND_API_KEY"]

        # Build verification link - matches frontend/user/verify-email.html or frontend/vendor/verify-email.html
        frontend_url = current_app.config["FRONTEND_URL"]
        verify_link = f"{frontend_url}/{role}/verify-email.html?token={token}"

        # Send email
        resend.Emails.send({
            "from": f"OLR India <{current_app.config['RESEND_FROM_EMAIL']}>",
            "to": to_email,
            "subject": "Verify your OLR India account",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">

                <h2 style="color: #1a1a1a;">Welcome to OLR India, {name}! 👋</h2>

                <p style="color: #333; font-size: 16px;">
                    Thank you for registering. Please verify your email address
                    by clicking the button below.
                </p>

                <a href="{verify_link}"
                   style="display: inline-block;
                          background-color: #000;
                          color: #fff;
                          padding: 12px 30px;
                          text-decoration: none;
                          border-radius: 5px;
                          font-size: 16px;
                          margin: 20px 0;">
                    Verify Email Address
                </a>

                <p style="color: #666; font-size: 14px;">
                    This link expires in <strong>15 minutes</strong>.
                    If you did not create an account, ignore this email.
                </p>

                <p style="color: #666; font-size: 14px;">
    If the button above doesn't work, click the button below.
</p>

<a href="{verify_link}"
   style="
      display:inline-block;
      background:#f3f4f6;
      color:#000;
      padding:10px 24px;
      text-decoration:none;
      border-radius:5px;
      border:1px solid #ccc;
      font-size:15px;
      margin-bottom:20px;">
    Open Verification Link
</a>

                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">
                    OLR India - India's Rental Marketplace
                </p>

            </body>
            </html>
            """
        })

        return True

    except Exception as e:
        # Log error but don't crash the app
        print(f"[Email Error] Failed to send verification email to {to_email}: {str(e)}")
        return False


def send_password_reset_email(to_email: str, name: str, token: str, role: str = "user") -> bool:
    """
    Send password reset link email.

    Args:
        to_email: Recipient email address
        name: Recipient's name
        token: Secure password reset token
        role: "user" or "vendor" - determines which frontend folder the link points to

    Returns:
        True if sent successfully, False if failed
    """
    try:
        resend.api_key = current_app.config["RESEND_API_KEY"]

        # Build reset link - matches frontend/user/reset-password.html or frontend/vendor/reset-password.html
        frontend_url = current_app.config["FRONTEND_URL"]
        reset_link = f"{frontend_url}/{role}/reset-password.html?token={token}"

        resend.Emails.send({
            "from": f"OLR India <{current_app.config['RESEND_FROM_EMAIL']}>",
            "to": to_email,
            "subject": "Reset your OLR India password",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">

                <h2 style="color: #1a1a1a;">Reset your password</h2>

                <p style="color: #333; font-size: 16px;">
                    Hi {name}, we received a request to reset your OLR India password.
                    Click the button below to set a new password.
                </p>

                <a href="{reset_link}"
                   style="display: inline-block;
                          background-color: #000;
                          color: #fff;
                          padding: 12px 30px;
                          text-decoration: none;
                          border-radius: 5px;
                          font-size: 16px;
                          margin: 20px 0;">
                    Reset Password
                </a>

                <p style="color: #666; font-size: 14px;">
                    This link expires in <strong>15 minutes</strong> and can only be used once.
                    If you did not request a password reset, ignore this email -
                    your password will not be changed.
                </p>

                <p style="color: #666; font-size: 14px;">
    If the button above doesn't work, click the button below.
</p>

<a href="{reset_link}"
   style="
      display:inline-block;
      background:#f3f4f6;
      color:#000;
      padding:10px 24px;
      text-decoration:none;
      border-radius:5px;
      border:1px solid #ccc;
      font-size:15px;
      margin-bottom:20px;">
    Open Reset Link
</a>

                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">
                    OLR India - India's Rental Marketplace
                </p>

            </body>
            </html>
            """
        })

        return True

    except Exception as e:
        print(f"[Email Error] Failed to send reset email to {to_email}: {str(e)}")
        return False
    
def send_vendor_strike_email(to_email: str, name: str, reason: str, strike_number: int) -> bool:
    """
    Sent when admin removes one of the vendor's products for a policy
    violation. Tells them the reason and their current strike count.
    """
    try:
        resend.api_key = current_app.config["RESEND_API_KEY"]

        resend.Emails.send({
            "from": f"OLR India <{current_app.config['RESEND_FROM_EMAIL']}>",
            "to": to_email,
            "subject": "A listing was removed from your OLR India account",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">

                <h2 style="color: #1a1a1a;">Hi {name},</h2>

                <p style="color: #333; font-size: 16px;">
                    One of your listings has been removed from OLR India by our
                    moderation team for the following reason:
                </p>

                <div style="background:#FDEDEA; border-left:4px solid #D8351F;
                            padding:14px 16px; margin:16px 0; color:#333; font-size:14px;">
                    {reason}
                </div>

                <p style="color: #333; font-size: 15px;">
                    This is strike <strong>{strike_number} of 3</strong> on your account.
                    Accounts reaching 3 strikes are automatically suspended.
                </p>

                <p style="color: #333; font-size: 15px;">
                    You have <strong>7 days</strong> to edit the listing and bring it back live.
                    After 7 days the listing will be <strong>permanently deleted</strong>.
                </p>

                <p style="color: #666; font-size: 14px;">
                    If you believe this was a mistake, please contact our support team.
                </p>

                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">
                    OLR India - India's Rental Marketplace
                </p>

            </body>
            </html>
            """
        })
        return True

    except Exception as e:
        print(f"[Email Error] Failed to send strike email to {to_email}: {str(e)}")
        return False


def send_vendor_suspended_email(to_email: str, name: str, reason: str = None) -> bool:
    """
    Sent when a vendor account is suspended, either automatically
    (3 strikes) or manually by an admin.
    """
    try:
        resend.api_key = current_app.config["RESEND_API_KEY"]

        reason_block = f"""
            <div style="background:#FDEDEA; border-left:4px solid #D8351F;
                        padding:14px 16px; margin:16px 0; color:#333; font-size:14px;">
                {reason}
            </div>
        """ if reason else ""

        resend.Emails.send({
            "from": f"OLR India <{current_app.config['RESEND_FROM_EMAIL']}>",
            "to": to_email,
            "subject": "Your OLR India vendor account has been suspended",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">

                <h2 style="color: #1a1a1a;">Hi {name},</h2>

                <p style="color: #333; font-size: 16px;">
                    Your OLR India vendor account has been suspended and your
                    listings are no longer visible to the public.
                </p>

                {reason_block}

                <p style="color: #666; font-size: 14px;">
                    If you believe this was a mistake, please contact our support team
                    to request a review.
                </p>

                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">
                    OLR India - India's Rental Marketplace
                </p>

            </body>
            </html>
            """
        })
        return True

    except Exception as e:
        print(f"[Email Error] Failed to send suspension email to {to_email}: {str(e)}")
        return False
    
def send_vendor_reactivated_email(to_email: str, name: str) -> bool:
    """
    Sent when admin unflag/reactivates a suspended vendor account.
    """
    try:
        resend.api_key = current_app.config["RESEND_API_KEY"]

        resend.Emails.send({
            "from": f"OLR India <{current_app.config['RESEND_FROM_EMAIL']}>",
            "to": to_email,
            "subject": "Your OLR India vendor account has been reactivated",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">

                <h2 style="color: #1a1a1a;">Hi {name},</h2>

                <p style="color: #333; font-size: 16px;">
                    Good news! Your OLR India vendor account has been reviewed
                    and reactivated. Your listings are now visible to the public again.
                </p>

                <p style="color: #666; font-size: 14px;">
                    Please ensure your listings comply with our platform policies
                    to avoid future violations.
                </p>

                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">
                    OLR India - India's Rental Marketplace
                </p>

            </body>
            </html>
            """
        })
        return True

    except Exception as e:
        print(f"[Email Error] Failed to send reactivation email to {to_email}: {str(e)}")
        return False