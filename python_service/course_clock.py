"""Current course business day, shared with Java's Asia/Shanghai policy.

Use modern UTC+08:00 without an OS timezone database dependency. This clock
defines today's validation boundary, not historical timezone conversion for
observation dates. Protocol/error timestamps continue to use UTC.
"""
from datetime import datetime, timedelta, timezone


BUSINESS_TIMEZONE = timezone(timedelta(hours=8), 'Asia/Shanghai')


def business_today():
    return datetime.now(BUSINESS_TIMEZONE).date()
