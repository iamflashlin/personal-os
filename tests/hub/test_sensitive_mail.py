# ruff: noqa: RUF001  (real mail text uses full-width punctuation)
import re

import pytest

from apps.hub.summaries.sensitive import reason

SENSITIVE = [
    ("网易邮箱验证码", "您的验证码是 482913，10分钟内有效。"),
    ("QQ安全中心", "你正在登录QQ，动态码：551234，请勿泄露。"),
    ("Your Google verification code", "Your verification code is 381920."),
    ("G-482913 is your Google verification code", ""),
    ("Apple ID", "Your Apple ID Code is: 123456. Don't share it with anyone."),
    ("Microsoft account security code", "Please use the following security code: 7731"),
    ("Reset your password", "Click the link below to reset your password."),
    ("招商银行", "【招商银行】您的一次性密码为 889201，请勿告知他人。"),
    ("找回密码", "您正在找回密码，请点击链接完成操作。"),
    ("Canvas login", "Your one-time passcode for De Anza Canvas is 554433"),
    ("Sign in to Slack", "Here is your magic link to sign in."),
    ("Two-factor authentication", "Your 2FA code is 902211"),
    ("Your OTP", "OTP: 4421 (valid 5 minutes)"),
    ("账号安全提醒", "您正在进行两步验证，校验码 203948"),
    ("Password reset request", "We received a request for a password reset."),
    ("登录确认", "您的登录码为 1122，若非本人操作请修改密码。"),
    ("Confirm your email", "Your confirmation code: AB12CD"),
    ("账号通知", "您的码是482913请勿泄露"),
    ("Login", "Code 482913请输入"),
    ("QQ邮箱", "您的授权码已生成，请妥善保管。"),
    ("账户安全", "您的临时密码为 Ab3k9z，请登录后修改。"),
    ("Your bank card", "Your PIN is 4821"),
]

ORDINARY = [
    ("CIS 22A: Lab 5 due Friday", "Lab 5 is due Friday 11:59pm. Submit on Canvas."),
    ("Announcement: Midterm review", "The midterm review session is on Thursday in room S43."),
    ("Week 8 course update", "Please read chapters 9 and 10 before class."),
    ("The Weekly Digest", "Top stories this week: campus events, clubs and more."),
    ("Your Amazon.com order has shipped", "Your package will arrive on Saturday."),
    ("Receipt from Starbucks", "Thanks for your purchase. Total: $5.45"),
    ("作业提醒：第三章练习", "请在下周一之前提交第三章练习。"),
    ("图书馆借阅到期提醒", "您借阅的图书将于11月20日到期。"),
    ("Spring registration opens", "Registration for spring quarter opens on Monday."),
    ("Office hours moved", "My office hours this week move to Wednesday 2-3pm."),
    ("Club meeting tonight", "Join us at 6pm in the student center."),
]


@pytest.mark.parametrize(("subject", "body"), SENSITIVE)
def test_one_time_codes_and_resets_are_flagged(subject: str, body: str) -> None:
    assert reason(subject, body) is not None


@pytest.mark.parametrize(("subject", "body"), ORDINARY)
def test_ordinary_mail_is_not_flagged(subject: str, body: str) -> None:
    assert reason(subject, body) is None


@pytest.mark.parametrize(("subject", "body"), SENSITIVE)
def test_the_reason_never_contains_the_code(subject: str, body: str) -> None:
    label = reason(subject, body)
    assert label is not None
    for code in re.findall(r"\d{4,8}|[A-Za-z0-9]{6}", f"{subject} {body}"):
        if any(ch.isdigit() for ch in code):
            assert code not in label
    assert label in {
        "one-time code or password reset wording",
        "OTP/2FA/MFA",
        "a code word next to 4-8 digits",
    }


def test_samples_cover_the_card() -> None:
    assert len(SENSITIVE) >= 15
    assert len(ORDINARY) >= 10
