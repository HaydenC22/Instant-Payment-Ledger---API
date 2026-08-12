from decimal import Decimal

import pytest

from app.infra.qr.sgqr import SgqrError, build_sgqr, parse_tlv, verify_crc

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_build_sgqr_produces_a_valid_png() -> None:
    result = build_sgqr(
        account_number="SG-0001",
        merchant_name="Alice Tan",
        merchant_city="Singapore",
        currency="SGD",
        amount=Decimal("20.00"),
    )
    assert result.png_bytes.startswith(_PNG_MAGIC)


def test_payload_crc_is_valid() -> None:
    result = build_sgqr(
        account_number="SG-0001",
        merchant_name="Alice Tan",
        merchant_city="Singapore",
        currency="SGD",
        amount=Decimal("20.00"),
    )
    assert verify_crc(result.payload)


def test_tampered_payload_fails_crc_verification() -> None:
    result = build_sgqr(
        account_number="SG-0001",
        merchant_name="Alice Tan",
        merchant_city="Singapore",
        currency="SGD",
        amount=Decimal("20.00"),
    )
    tampered = result.payload[:-1] + ("0" if result.payload[-1] != "0" else "1")
    assert not verify_crc(tampered)


def test_round_trips_account_number_and_amount_through_tlv_parsing() -> None:
    result = build_sgqr(
        account_number="SG-0001",
        merchant_name="Alice Tan",
        merchant_city="Singapore",
        currency="SGD",
        amount=Decimal("42.50"),
    )
    fields = parse_tlv(result.payload)

    assert fields["00"] == "01"  # payload format indicator
    assert fields["53"] == "702"  # SGD ISO 4217 numeric
    assert fields["54"] == "42.50"
    merchant_account_fields = parse_tlv(fields["26"])
    assert merchant_account_fields["01"] == "SG-0001"


def test_dynamic_qr_when_amount_given_static_when_not() -> None:
    with_amount = build_sgqr(
        account_number="SG-0001",
        merchant_name="A",
        merchant_city="SG",
        currency="SGD",
        amount=Decimal("1.00"),
    )
    without_amount = build_sgqr(
        account_number="SG-0001", merchant_name="A", merchant_city="SG", currency="SGD"
    )
    assert parse_tlv(with_amount.payload)["01"] == "12"
    assert parse_tlv(without_amount.payload)["01"] == "11"
    assert "54" not in parse_tlv(without_amount.payload)


def test_unsupported_currency_raises() -> None:
    with pytest.raises(SgqrError, match="unsupported currency"):
        build_sgqr(account_number="SG-0001", merchant_name="A", merchant_city="SG", currency="JPY")


def test_non_positive_amount_raises() -> None:
    with pytest.raises(SgqrError, match="positive"):
        build_sgqr(
            account_number="SG-0001",
            merchant_name="A",
            merchant_city="SG",
            currency="SGD",
            amount=Decimal("0"),
        )


def test_long_merchant_name_and_city_are_truncated_not_rejected() -> None:
    result = build_sgqr(
        account_number="SG-0001",
        merchant_name="A" * 100,
        merchant_city="B" * 100,
        currency="SGD",
    )
    fields = parse_tlv(result.payload)
    assert len(fields["59"]) <= 25
    assert len(fields["60"]) <= 15
