# Migration Plan

## Goal
Consolidate the two DingTalk bots into one monorepo while keeping behavior stable.

## Phase 1
- Preserve both existing apps as-is under `apps/`.
- Add a shared layer only for infrastructure that is clearly duplicated.

## Phase 2
- Extract common DingTalk stream client bootstrapping.
- Extract configuration loading and logging.
- Extract dedup / workspace / cleanup helpers.

## Phase 3
- Normalize packaging and CI.
- Remove any temporary compatibility shims.

## Phase 4
- Make `apps/logistics_bot` the default department-level DingTalk entrypoint.
- Keep `apps/cp_bot` and `apps/split_bot` as independently testable business branches.
