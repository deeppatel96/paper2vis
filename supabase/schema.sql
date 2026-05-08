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
