# Production Concurrency Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the service server-ready by supporting environment-driven Postgres and Postgres-safe multi-worker job claiming while preserving local SQLite defaults.

**Architecture:** Configuration reads `DATABASE_URL`; database engine creation handles SQLite and non-SQLite URLs correctly; repository uses simple claim for SQLite and `FOR UPDATE SKIP LOCKED` for Postgres. Documentation explains system boundaries, concurrency model, and why MQ remains a later evolution.

**Tech Stack:** Python, FastAPI, SQLAlchemy, SQLite, Postgres via psycopg, pytest.

---

## Tasks

1. Add tests for environment-driven settings and database engine options.
2. Implement `Settings.from_env()` and database engine factory helpers.
3. Add tests for Postgres claim statement semantics.
4. Refactor repository claim into dialect-aware statement construction.
5. Update requirements with `psycopg`.
6. Add `docs/system-boundary.md` and `docs/production-architecture.md`.
7. Update README and decisions with the architecture answer.
8. Run full pytest and commit.
