-- ==============================================================================
-- 🛡️ SentinelDispute - Production Supabase PostgreSQL Schema
-- ==============================================================================
-- Run this script in the Supabase SQL Editor:
-- Dashboard -> Your Project -> SQL Editor -> New Query -> Paste & Run (Ctrl+Enter)
-- ==============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------------------------
-- 1. Dossiers Table
-- Stores generated dispute defense dossiers, evidence packages, and decisions
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dossiers (
    dispute_id VARCHAR PRIMARY KEY,
    payment_id VARCHAR,
    amount_inr NUMERIC,
    card_network VARCHAR,
    reason_code VARCHAR,
    confidence_score NUMERIC,
    decision VARCHAR,
    timestamp VARCHAR,
    sealed_hash VARCHAR,
    dossier_json JSONB NOT NULL,
    raw_payload_json JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dossiers_payment_id ON public.dossiers (payment_id);
CREATE INDEX IF NOT EXISTS idx_dossiers_updated_at ON public.dossiers (updated_at DESC);

-- ------------------------------------------------------------------------------
-- 2. Ledger Blocks Table
-- Tamper-evident cryptographic audit trail for multi-agent decisions
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ledger_blocks (
    block_index INTEGER PRIMARY KEY,
    previous_hash VARCHAR NOT NULL,
    timestamp VARCHAR NOT NULL,
    agent_id VARCHAR NOT NULL,
    state_transition VARCHAR NOT NULL,
    payload_hash VARCHAR NOT NULL,
    block_hash VARCHAR NOT NULL,
    payload_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON public.ledger_blocks (timestamp);

-- ------------------------------------------------------------------------------
-- 3. Processed Events Table (Replay Attack Guard & Webhook Idempotency)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.processed_events (
    event_id VARCHAR PRIMARY KEY,
    signature VARCHAR,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------------
-- 4. Customer Telemetry Table
-- Cold-tier historical transactions for Visa CE 3.0 & Mastercard FPT matching
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.customer_telemetry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_fingerprint VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    ip_address VARCHAR(64) NOT NULL,
    device_fingerprint VARCHAR(128) NOT NULL,
    shipping_address_hash VARCHAR(64) NOT NULL,
    transaction_time TIMESTAMP WITH TIME ZONE NOT NULL,
    dispute_status VARCHAR(16) DEFAULT 'undisputed',
    amount_inr NUMERIC DEFAULT 0.0,
    payload_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_telemetry_lookup 
    ON public.customer_telemetry (card_fingerprint, transaction_time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_customer 
    ON public.customer_telemetry (customer_id);

-- ------------------------------------------------------------------------------
-- 5. Pre-Dispute Interception Logs Table
-- Tracks real-time inquiries from Visa Verifi / Mastercard Ethoca
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.pre_dispute_logs (
    inquiry_id VARCHAR PRIMARY KEY,
    network VARCHAR NOT NULL,
    card_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    evidence_type VARCHAR(32),
    response_time_ms NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    payload_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_pre_dispute_network 
    ON public.pre_dispute_logs (network, status);

-- ------------------------------------------------------------------------------
-- 6. Dispute Resolution Outcomes Table
-- Closed-loop learning dataset tracking bank win rates and evidence efficacy
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dispute_outcomes (
    dispute_id VARCHAR PRIMARY KEY,
    card_bin VARCHAR(8),
    issuing_bank VARCHAR(64),
    network VARCHAR(16),
    reason_code VARCHAR(16),
    outcome VARCHAR(16) NOT NULL,
    amount_inr NUMERIC,
    confidence_score NUMERIC,
    evidence_types_used JSONB,
    resolved_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dispute_outcomes_card_bin 
    ON public.dispute_outcomes (card_bin);
CREATE INDEX IF NOT EXISTS idx_dispute_outcomes_resolved_at 
    ON public.dispute_outcomes (resolved_at DESC);
