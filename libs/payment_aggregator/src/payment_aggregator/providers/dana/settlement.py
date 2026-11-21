"""
DANA Payment Services settlement file (Gapura): CSV, ``;`` delimited, one
line per transaction, amounts in cents, dates YYYY-MM-DDTHH:mm:ss+07:00.
Spec: dashboard.dana.id/api-docs-v2/guide/settlement-file/payment-services
(v1.2.0); file name MERCHANT_SETTLEMENT_<MID>_<UNIT>_<UNIT NAME>_<YYYYMMDD>.csv.

Matching keys: ACQUIRING_ORDER lines carry the billing's acquirementId
(our provider_trx_id, DANA's referenceNo) in TXN_ID (ACQUIREMENT_ID can be
empty, see DANA's sample); REFUND / CANCEL carry it in ORIGINAL_TXN_ID.
MERCHANT_TRANS_ID is kept as our reference (assumed partnerReferenceNo).
"""

import csv
import datetime
import io
from decimal import Decimal

from payment_aggregator.base import SettlementLine, SettlementLineType
from payment_aggregator.exceptions import InvalidSettlementFile

REQUIRED_COLUMNS = ("TXN_ID", "TXN_TYPE", "TXN_AMOUNT", "SETTLE_DATE")
# Charged to the merchant (cents); withholding taxes are not deducted by DANA.
FEE_COLUMNS = ("MERCHANT_COMMISSION_EDIK", "SERVICE_TAX_EDIK", "MERCHANT_COMMISSION_ASR", "SERVICE_TAX_ASR")

TYPES = {
    "ACQUIRING_ORDER": SettlementLineType.PAYMENT,
    "REFUND": SettlementLineType.REFUND,
    "CANCEL": SettlementLineType.CANCEL,
}
PAY_METHOD_ADJUSTMENT = "ADJUSTMENT"
CENT = Decimal("0.01")


def _cents(value, column, line_no, required=True):
    value = (value or "").strip()
    if not value:
        if required:
            raise InvalidSettlementFile("Line {}: {} is empty".format(line_no, column))
        return None
    try:
        return (Decimal(int(value)) / 100).quantize(CENT)
    except ValueError:
        raise InvalidSettlementFile("Line {}: {} is not a whole number of cents ({!r})".format(line_no, column, value))


def _datetime(value, column, line_no):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise InvalidSettlementFile("Line {}: {} is not a date ({!r})".format(line_no, column, value))
    if parsed.tzinfo is None:
        raise InvalidSettlementFile("Line {}: {} has no time zone ({!r})".format(line_no, column, value))
    return parsed


def _type(provider_type, pay_method):
    if provider_type == "ACQUIRING_ORDER" and pay_method == PAY_METHOD_ADJUSTMENT:
        return SettlementLineType.ADJUSTMENT
    return TYPES.get(provider_type, SettlementLineType.OTHER)


def parse(content):
    """Settlement file text -> [SettlementLine]."""
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise InvalidSettlementFile("The file is not UTF-8 text")
    content = content.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(content), delimiter=";")
    columns = [name.strip() for name in (reader.fieldnames or [])]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise InvalidSettlementFile(
            "Not a DANA settlement file (';' delimited); missing column(s): " + ", ".join(missing)
        )

    lines = []
    for line_no, row in enumerate(reader, start=1):
        row = {(key or "").strip(): (value or "").strip() for key, value in row.items() if key}
        if not any(row.values()):
            continue  # blank line
        provider_type = row.get("TXN_TYPE", "")
        pay_method = row.get("PAY_METHOD", "")
        fee = sum(
            (_cents(row.get(column), column, line_no, required=False) or Decimal("0") for column in FEE_COLUMNS),
            Decimal("0"),
        )
        lines.append(SettlementLine(
            line_no=line_no,
            type=_type(provider_type, pay_method),
            provider_type=provider_type,
            provider_trx_id=row.get("TXN_ID", ""),
            original_trx_id=row.get("ORIGINAL_TXN_ID", ""),
            reference_no=row.get("MERCHANT_TRANS_ID", ""),
            amount=_cents(row.get("TXN_AMOUNT"), "TXN_AMOUNT", line_no),
            fee=fee,
            settle_amount=_cents(row.get("SETTLE_AMOUNT"), "SETTLE_AMOUNT", line_no, required=False),
            settled_at=_datetime(row.get("SETTLE_DATE"), "SETTLE_DATE", line_no),
            transaction_at=_datetime(row.get("TXN_DATE"), "TXN_DATE", line_no),
            pay_method=pay_method,
            batch_no=row.get("SETTLEMENT_TXN_ID", ""),
            raw=row,
        ))
    return lines
