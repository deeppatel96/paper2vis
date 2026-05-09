-- paper2vis Supabase schema
-- Run this in the Supabase SQL editor to create the required tables.

-- Users table (synced from Clerk via webhook)
CREATE TABLE IF NOT EXISTS users (
  clerk_id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  tier TEXT NOT NULL DEFAULT 'mini' CHECK (tier IN ('mini', 'pro')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Usage log (one row per job created)
CREATE TABLE IF NOT EXISTS usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
  job_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast monthly usage queries
CREATE INDEX IF NOT EXISTS usage_clerk_month
  ON usage (clerk_id, date_trunc('month', created_at AT TIME ZONE 'UTC'));

-- Jobs (persisted across redeployments, per-user)
CREATE TABLE IF NOT EXISTS jobs (
  job_id       TEXT PRIMARY KEY,
  clerk_id     TEXT NOT NULL,
  pdf_name     TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'queued',
  state        JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_clerk_created ON jobs (clerk_id, created_at DESC);

-- Invite codes (unique per person, single-use)
CREATE TABLE IF NOT EXISTS invite_codes (
  code        TEXT PRIMARY KEY,
  note        TEXT,                                      -- optional label, e.g. recipient name
  used_by     TEXT REFERENCES users(clerk_id),
  used_at     TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
