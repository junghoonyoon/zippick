"""운영 결제 연동 전에도 안전하게 켜고 끌 수 있는 유료 접근 제어."""

import hmac
import os


def status():
    required = os.environ.get("REPORT_PAYMENT_REQUIRED", "0") == "1"
    configured_token = os.environ.get("REPORT_ACCESS_TOKEN", "").strip()
    return {
        "paymentRequired": required,
        "accessConfigured": bool(configured_token),
        "checkoutUrl": os.environ.get("REPORT_CHECKOUT_URL", "").strip(),
        "localPreview": not required,
    }


def authorize(supplied_token):
    current = status()
    if not current["paymentRequired"]:
        return True, current
    configured_token = os.environ.get("REPORT_ACCESS_TOKEN", "").strip()
    if configured_token and hmac.compare_digest(
        configured_token,
        str(supplied_token or "").strip(),
    ):
        return True, current
    return False, {
        "error": "유료 리포트 이용권이 필요해요.",
        "code": "payment_required",
        "checkoutUrl": current["checkoutUrl"],
    }
