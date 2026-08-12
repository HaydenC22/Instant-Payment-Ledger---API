from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

import qrcode

# ISO 4217 numeric currency codes, as required by EMVCo QR tag 53.
_CURRENCY_NUMERIC = {"SGD": "702", "USD": "840", "EUR": "978", "GBP": "826"}


class SgqrError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SgqrPayload:
    payload: str  # raw EMVCo TLV string, CRC-terminated
    png_bytes: bytes


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise SgqrError(f"TLV value for tag {tag} exceeds 99 characters: {value!r}")
    return f"{tag}{len(value):02d}{value}"


def _crc16_ccitt(data: str) -> str:
    """CRC-16/CCITT-FALSE over ASCII bytes — the checksum EMVCo QR (and so SGQR) mandates
    as the final TLV field.
    """
    crc = 0xFFFF
    for byte in data.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def build_sgqr(
    *,
    account_number: str,
    merchant_name: str,
    merchant_city: str,
    currency: str,
    amount: Decimal | None = None,
) -> SgqrPayload:
    """Builds an SGQR-style payment QR: EMVCo QR Code Specification for Payment Systems
    TLV encoding (the open standard SGQR itself is built on), with a PayNow-style
    proprietary merchant account template carrying this system's account number.

    Deliberately "SGQR-style", not a certified SGQR: it round-trips through the same
    TLV/CRC structure a real scanner expects, but doesn't chase full scheme registration
    (issuer IDs, acquirer templates, etc.) — see the README's "what's next".
    """
    if currency not in _CURRENCY_NUMERIC:
        raise SgqrError(f"unsupported currency for SGQR: {currency}")
    if amount is not None and amount <= 0:
        raise SgqrError(f"amount must be positive, got {amount}")

    merchant_account_info = _tlv("00", "SG.PAYNOW") + _tlv("01", account_number)
    point_of_initiation = "12" if amount is not None else "11"  # dynamic vs static QR

    fields = [
        _tlv("00", "01"),  # Payload Format Indicator
        _tlv("01", point_of_initiation),
        _tlv("26", merchant_account_info),  # proprietary merchant account template
        _tlv("52", "0000"),  # Merchant Category Code (generic/unknown)
        _tlv("53", _CURRENCY_NUMERIC[currency]),
    ]
    if amount is not None:
        fields.append(_tlv("54", str(amount)))
    fields += [
        _tlv("58", "SG"),
        _tlv("59", merchant_name[:25]),
        _tlv("60", merchant_city[:15]),
    ]

    payload_without_crc = "".join(fields) + "6304"
    payload = payload_without_crc + _crc16_ccitt(payload_without_crc)

    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    return SgqrPayload(payload=payload, png_bytes=buffer.getvalue())


def parse_tlv(payload: str) -> dict[str, str]:
    """Decodes a TLV payload back into {tag: value}. Used for round-trip verification."""
    fields: dict[str, str] = {}
    i = 0
    while i < len(payload):
        tag = payload[i : i + 2]
        length = int(payload[i + 2 : i + 4])
        value = payload[i + 4 : i + 4 + length]
        fields[tag] = value
        i += 4 + length
    return fields


def verify_crc(payload: str) -> bool:
    body, crc = payload[:-4], payload[-4:]
    return _crc16_ccitt(body) == crc
