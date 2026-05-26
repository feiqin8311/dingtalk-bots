# Maintainability Refactor Design

## Goal

Reduce `handler.py` redundancy and improve maintainability without changing DingTalk, LingXing, OCR, SMB address book, or usage logging behavior.

## Scope

- Extract address parsing and matching into `address_matching.py`.
- Extract LingXing shipment detail fallback into `shipment_service.py`.
- Deduplicate selected-file queueing in `ShipmentQueryHandler.process()`.
- Keep database scope unchanged: MySQL records received usage only.

## Architecture

`handler.py` remains the orchestration layer for DingTalk callbacks, queueing, replies, and OCR workflow. `address_matching.py` owns pure country/address parsing, formatting, and candidate scoring. `shipment_service.py` owns the LingXing detail query fallback from normal request shape to `shipment_sn_arr`.

The split keeps runtime side effects in `handler.py` and makes the largest pure logic block independently testable.

## Compatibility

`handler.py` imports address-matching helpers with the old private names so existing diagnostics and tests that import `_AddressRecord` or `_score_address_candidate` continue to work. New tests import the public names from `address_matching.py`.

## Testing

Validation should include:

- Unit tests for address matching module exports and UK city matching.
- Unit tests for LingXing detail fallback behavior.
- Existing address book, config, local API import, and runtime state tests.
- `py_compile` for the main modules.
