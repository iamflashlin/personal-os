"""Mail that must never be sent to a model: one-time codes and password resets (ADR 0027).

It deliberately over-filters. A false positive costs one summary, and the mail is labelled
so the user knows why. A false negative would send a live code to a third party.

`reason` returns a fixed label per rule, never the matched text: the match can contain the
code itself, and the reason is stored and shown.
"""

import re

_TERMS = [
    # Chinese
    "验证码",
    "校验码",
    "动态码",
    "动态密码",
    "安全码",
    "确认码",
    "登录码",
    "授权码",
    "激活码",
    "一次性密码",
    "临时密码",
    "重置密码",
    "找回密码",
    "修改密码",
    "密码重置",
    "两步验证",
    "二次验证",
    "身份验证",
    "登录验证",
    "安全验证",
    # English
    "verification code",
    "verification link",
    "verify code",
    "security code",
    "confirmation code",
    "access code",
    "login code",
    "log-in code",
    "sign-in code",
    "sign in code",
    "signin code",
    "one-time password",
    "one-time code",
    "one-time passcode",
    "one time password",
    "one time code",
    "temporary password",
    "passcode",
    "password reset",
    "reset your password",
    "reset password",
    "magic link",
    "authentication code",
    "two-factor",
    "two-step",
]
_PHRASES = re.compile("|".join(re.escape(t) for t in _TERMS), re.IGNORECASE)
_WORDS = re.compile(r"\b(?:otp|2fa|mfa)\b", re.IGNORECASE)
# "Your Apple ID Code is: 123456", "您的码是482913请勿泄露", "Your PIN is 4821": a code word
# shortly before 4-8 digits. Digit boundaries are explicit because Python's \b treats CJK
# characters as word characters, so "是482913请" has no \b around the digits.
_CODE_NEAR_DIGITS = re.compile(
    r"(?:\bcode\b|\bpin\b|码)\D{0,20}?(?<!\d)\d{4,8}(?!\d)", re.IGNORECASE
)

_RULES = (
    (_PHRASES, "one-time code or password reset wording"),
    (_WORDS, "OTP/2FA/MFA"),
    (_CODE_NEAR_DIGITS, "a code word next to 4-8 digits"),
)


def reason(subject: str, body: str) -> str | None:
    """Why this mail must not be sent (a fixed label), or None when it may be."""
    text = f"{subject}\n{body}"
    for pattern, label in _RULES:
        if pattern.search(text):
            return label
    return None
