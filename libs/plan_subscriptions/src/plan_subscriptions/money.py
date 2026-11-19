"""Money and period arithmetic."""
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from . import conf


def quantize(amount):
    places = int(conf.get("AMOUNT_DECIMALS"))
    exponent = Decimal(1).scaleb(-places)
    return Decimal(amount).quantize(exponent, rounding=ROUND_HALF_UP)


def tax_of(subtotal):
    return quantize(Decimal(subtotal) * conf.tax_rate())


def add_interval(start, interval="month", count=1):
    if interval == "year":
        return start + relativedelta(years=count)
    return start + relativedelta(months=count)


def price_period_end(start, price):
    return add_interval(start, price.interval, price.interval_count)


def prorate(amount, start, end, period_start, period_end):
    """amount x (end - start) / (period_end - period_start), never negative."""
    total = (period_end - period_start).total_seconds()
    used = max(0.0, (end - start).total_seconds())
    if total <= 0:
        return quantize(0)
    return quantize(Decimal(amount) * Decimal(str(min(used, total))) / Decimal(str(total)))


def as_str(amount):
    return str(quantize(amount))
