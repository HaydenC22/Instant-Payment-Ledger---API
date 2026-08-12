from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from app.domain.ledger.entities import JournalLine


class UnbalancedEntryError(ValueError):
    def __init__(self, net_by_currency: dict[str, Decimal]):
        self.net_by_currency = net_by_currency
        super().__init__(f"journal entry does not balance per currency: {net_by_currency}")


class EmptyJournalEntryError(ValueError):
    def __init__(self) -> None:
        super().__init__("journal entry must have at least one line")


class InvalidLineAmountError(ValueError):
    def __init__(self, line: JournalLine):
        self.line = line
        super().__init__(
            f"journal line amount must be positive, got {line.amount} for {line.account_id}"
        )


def validate_journal_entry(lines: Sequence[JournalLine]) -> None:
    if not lines:
        raise EmptyJournalEntryError

    for line in lines:
        if line.amount <= 0:
            raise InvalidLineAmountError(line)

    net_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for line in lines:
        net_by_currency[line.currency] += line.signed_amount

    unbalanced = {ccy: net for ccy, net in net_by_currency.items() if net != 0}
    if unbalanced:
        raise UnbalancedEntryError(unbalanced)
