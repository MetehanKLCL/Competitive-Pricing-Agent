"""
SES setup script — verifies email addresses.

In SES sandbox mode both sender and recipient must be verified.
"""

import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
SENDER = os.getenv("SES_SENDER_EMAIL", "agent@heweso.com")
RECIPIENT = os.getenv("SES_RECIPIENT_EMAIL", "metehanklcl03@gmail.com")

_ses = boto3.client("ses", region_name=AWS_REGION)


def verify_email(address: str) -> None:
    try:
        _ses.verify_email_identity(EmailAddress=address)
        print(f"[OK] Verification email sent to: {address}")
        print(f"     → Open your inbox and click the link from 'Amazon Web Services'.")
    except ClientError as e:
        print(f"[ERROR] {address}: {e.response['Error']['Message']}")


def check_verified(address: str) -> bool:
    response = _ses.get_identity_verification_attributes(Identities=[address])
    attrs = response["VerificationAttributes"].get(address, {})
    status = attrs.get("VerificationStatus", "NotStarted")
    verified = status == "Success"
    print(f"  {address}: {status} {'✅' if verified else '⏳'}")
    return verified


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        print("\n=== Verification Status ===")
        sender_ok = check_verified(SENDER)
        recipient_ok = check_verified(RECIPIENT)
        if sender_ok and recipient_ok:
            print("\n[READY] Both addresses verified — email sending will work.")
        else:
            print("\n[WAITING] Some addresses are not yet verified.")
    else:
        print("\n=== Starting SES Email Verification ===")
        verify_email(SENDER)
        verify_email(RECIPIENT)
        print("\nCheck your inbox, click the links, then run:")
        print("  python infrastructure/ses_setup.py --check")
