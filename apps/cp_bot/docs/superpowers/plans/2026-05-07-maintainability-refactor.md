# Maintainability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce duplicated and oversized handler logic while preserving current bot behavior.

**Architecture:** Keep `handler.py` as orchestration. Move pure address parsing/scoring to `address_matching.py`, move LingXing fallback to `shipment_service.py`, and centralize selected-file queueing in one handler helper.

**Tech Stack:** Python, unittest, dingtalk_stream, LingXing API client, Aliyun OCR client.

---

### Task 1: Address Matching Module

**Files:**
- Create: `address_matching.py`
- Modify: `handler.py`
- Modify: `tests/test_address_matching.py`
- Create: `tests/test_address_matching_module.py`

- [x] Write a failing test that imports public address matching helpers from `address_matching.py`.
- [x] Move address record dataclasses, country detection, address parsing, formatting, and scoring helpers into `address_matching.py`.
- [x] Import those helpers into `handler.py` with old private aliases for compatibility.
- [x] Update tests to use the public module API.
- [x] Run module tests.

### Task 2: LingXing Detail Fallback Helper

**Files:**
- Create: `shipment_service.py`
- Modify: `handler.py`
- Create: `tests/test_shipment_service.py`

- [x] Write failing tests for normal detail response and parameter-error fallback.
- [x] Implement `fetch_shipment_detail_with_fallback(client, shipment_sns)`.
- [x] Replace inline fallback logic in `_process_job()`.
- [x] Run shipment service tests.

### Task 3: Selected File Queueing Deduplication

**Files:**
- Modify: `handler.py`

- [x] Add `_enqueue_selected_file_job()` to handle lock acquisition, job creation, queue full release, and queue reply.
- [x] Replace both selected-file process branches with calls to the helper.
- [x] Run syntax checks and unit tests.

### Task 4: Verification

**Files:**
- No production code changes.

- [x] Run Python unit tests for new modules locally.
- [x] Run Docker full test command.
- [x] Run `git diff --check`.
- [x] Review `git diff --stat` and final changed files.
