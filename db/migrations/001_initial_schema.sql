-- WholesaleOS Full Schema
-- Run via: python scripts/setup_db.py

-- ─────────────────────────────────────────────
-- CORE PROPERTY DATA
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS parcels (
    parcel_id        TEXT PRIMARY KEY,         -- HCAD account number
    situs_num        TEXT,
    situs_street     TEXT,
    situs_city       TEXT,
    situs_state      TEXT DEFAULT 'TX',
    situs_zip        TEXT,
    full_address     TEXT GENERATED ALWAYS AS (
                         TRIM(COALESCE(situs_num,'') || ' ' || COALESCE(situs_street,''))
                     ) STORED,
    acct_type        TEXT,                     -- land use / property type
    land_val         NUMERIC,
    improvement_val  NUMERIC,
    total_appr_val   NUMERIC,
    total_mkt_val    NUMERIC,
    assessed_val     NUMERIC,
    land_sqft        NUMERIC,
    flood_zone       TEXT,                     -- populated from FEMA NFHL
    geometry         TEXT,                     -- GeoJSON polygon (populated monthly)
    hcad_year        INTEGER,
    last_updated     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parcels_zip ON parcels(situs_zip);
CREATE INDEX IF NOT EXISTS idx_parcels_address ON parcels(full_address);
CREATE INDEX IF NOT EXISTS idx_parcels_appr_val ON parcels(total_appr_val);

CREATE TABLE IF NOT EXISTS buildings (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    building_num     INTEGER DEFAULT 1,
    living_area      NUMERIC,                  -- sqft
    year_built       INTEGER,
    bedrooms         INTEGER,
    full_baths       INTEGER,
    half_baths       INTEGER,
    building_class   TEXT,
    condition        TEXT,
    stories          NUMERIC,
    garage_sqft      NUMERIC,
    pool_flag        BOOLEAN DEFAULT FALSE,
    last_updated     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_buildings_parcel ON buildings(parcel_id);

CREATE TABLE IF NOT EXISTS owners (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    owner_name       TEXT,
    owner_name_2     TEXT,
    owner_type       TEXT,                     -- individual / llc / trust / estate / bank / other
    mail_addr_1      TEXT,
    mail_addr_2      TEXT,
    mail_city        TEXT,
    mail_state       TEXT,
    mail_zip         TEXT,
    mail_country     TEXT DEFAULT 'US',
    is_absentee      BOOLEAN GENERATED ALWAYS AS (
                         mail_state IS NOT NULL AND mail_state <> 'TX'
                         OR (mail_zip IS NOT NULL AND mail_zip <> situs_zip_cache)
                     ) STORED,
    situs_zip_cache  TEXT,                     -- denormalized for the generated column
    owner_confidence TEXT DEFAULT 'MEDIUM',    -- HIGH / MEDIUM / LOW / UNKNOWN
    tx_sos_entity_id TEXT,                     -- populated by LLC piercing job
    real_person_name TEXT,                     -- populated by LLC piercing job
    registered_agent TEXT,
    last_updated     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(parcel_id)
);

CREATE INDEX IF NOT EXISTS idx_owners_parcel ON owners(parcel_id);
CREATE INDEX IF NOT EXISTS idx_owners_name ON owners(owner_name);
CREATE INDEX IF NOT EXISTS idx_owners_mail_state ON owners(mail_state);

CREATE TABLE IF NOT EXISTS owner_history (
    id           SERIAL PRIMARY KEY,
    parcel_id    TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    owner_name   TEXT,
    from_date    DATE,
    to_date      DATE,
    source       TEXT DEFAULT 'deed'
);

CREATE INDEX IF NOT EXISTS idx_owner_history_parcel ON owner_history(parcel_id);

-- ─────────────────────────────────────────────
-- FINANCIAL HISTORY
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS deeds (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    instrument_type  TEXT,                     -- WD, SWD, DT, REL, ML, FTL, AJ, HOA
    grantor          TEXT,
    grantee          TEXT,
    consideration    NUMERIC,                  -- sale price (from deed)
    recording_date   DATE,
    doc_number       TEXT UNIQUE,
    book_page        TEXT,
    notes            TEXT,
    raw_data         JSONB
);

CREATE INDEX IF NOT EXISTS idx_deeds_parcel ON deeds(parcel_id);
CREATE INDEX IF NOT EXISTS idx_deeds_type ON deeds(instrument_type);
CREATE INDEX IF NOT EXISTS idx_deeds_date ON deeds(recording_date);
CREATE INDEX IF NOT EXISTS idx_deeds_grantee ON deeds(grantee);

CREATE TABLE IF NOT EXISTS deeds_of_trust (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    original_amount  NUMERIC,
    lender           TEXT,
    recording_date   DATE,
    doc_number       TEXT UNIQUE,
    is_active        BOOLEAN DEFAULT TRUE,     -- set FALSE when release found
    release_doc      TEXT,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_dot_parcel ON deeds_of_trust(parcel_id);
CREATE INDEX IF NOT EXISTS idx_dot_active ON deeds_of_trust(is_active);

CREATE TABLE IF NOT EXISTS liens (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    lien_type        TEXT,                     -- tax / mechanic / federal / judgment / hoa
    amount           NUMERIC,
    lienholder       TEXT,
    recording_date   DATE,
    doc_number       TEXT,
    is_released      BOOLEAN DEFAULT FALSE,
    release_date     DATE,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_liens_parcel ON liens(parcel_id);
CREATE INDEX IF NOT EXISTS idx_liens_type ON liens(lien_type);
CREATE INDEX IF NOT EXISTS idx_liens_released ON liens(is_released);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id                      SERIAL PRIMARY KEY,
    parcel_id               TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    calc_date               DATE DEFAULT CURRENT_DATE,
    arv_estimate            NUMERIC,
    est_primary_balance     NUMERIC,
    est_tax_liens           NUMERIC DEFAULT 0,
    est_other_liens         NUMERIC DEFAULT 0,
    est_total_encumbrances  NUMERIC GENERATED ALWAYS AS (
                                COALESCE(est_primary_balance,0)
                                + COALESCE(est_tax_liens,0)
                                + COALESCE(est_other_liens,0)
                            ) STORED,
    est_equity              NUMERIC,
    upside_down             BOOLEAN DEFAULT FALSE,
    feasible_65             BOOLEAN,
    feasible_70             BOOLEAN,
    feasible_75             BOOLEAN,
    net_to_seller_65        NUMERIC,
    net_to_seller_70        NUMERIC,
    net_to_seller_75        NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_equity_parcel ON equity_snapshots(parcel_id);

-- ─────────────────────────────────────────────
-- DISTRESS SIGNALS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tax_status (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    tax_year         INTEGER,
    amount_due       NUMERIC,
    amount_paid      NUMERIC,
    is_delinquent    BOOLEAN DEFAULT FALSE,
    penalty_interest NUMERIC DEFAULT 0,
    last_updated     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(parcel_id, tax_year)
);

CREATE INDEX IF NOT EXISTS idx_tax_parcel ON tax_status(parcel_id);
CREATE INDEX IF NOT EXISTS idx_tax_delinquent ON tax_status(is_delinquent);

CREATE TABLE IF NOT EXISTS violations (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    violation_type   TEXT,
    description      TEXT,
    open_date        DATE,
    close_date       DATE,
    status           TEXT,
    fine_amount      NUMERIC DEFAULT 0,
    source_id        TEXT UNIQUE,
    raw_data         JSONB
);

CREATE INDEX IF NOT EXISTS idx_violations_parcel ON violations(parcel_id);
CREATE INDEX IF NOT EXISTS idx_violations_status ON violations(status);

CREATE TABLE IF NOT EXISTS complaints_311 (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT,                     -- may be null if geocode fails
    address_raw      TEXT,
    complaint_type   TEXT,
    description      TEXT,
    complaint_date   DATE,
    status           TEXT,
    lat              NUMERIC,
    lng              NUMERIC,
    source_id        TEXT UNIQUE,
    raw_data         JSONB
);

CREATE INDEX IF NOT EXISTS idx_311_parcel ON complaints_311(parcel_id);
CREATE INDEX IF NOT EXISTS idx_311_type ON complaints_311(complaint_type);

CREATE TABLE IF NOT EXISTS permits (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT,
    address_raw      TEXT,
    permit_type      TEXT,
    description      TEXT,
    issue_date       DATE,
    expiry_date      DATE,
    status           TEXT,
    is_stalled       BOOLEAN DEFAULT FALSE,    -- open > 18 months, no activity
    source_id        TEXT UNIQUE,
    raw_data         JSONB
);

CREATE INDEX IF NOT EXISTS idx_permits_parcel ON permits(parcel_id);
CREATE INDEX IF NOT EXISTS idx_permits_stalled ON permits(is_stalled);

CREATE TABLE IF NOT EXISTS foreclosures (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    filing_date      DATE,
    trustee_sale_date DATE,
    status           TEXT,                     -- filed / scheduled / postponed / sold / cancelled
    filing_amount    NUMERIC,
    trustee_name     TEXT,
    source_id        TEXT UNIQUE,
    raw_data         JSONB
);

CREATE INDEX IF NOT EXISTS idx_foreclosures_parcel ON foreclosures(parcel_id);
CREATE INDEX IF NOT EXISTS idx_foreclosures_status ON foreclosures(status);

-- ─────────────────────────────────────────────
-- CASH BUYERS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cash_buyers (
    id               SERIAL PRIMARY KEY,
    buyer_key        TEXT UNIQUE,              -- normalized name/entity key
    display_name     TEXT,
    entity_name      TEXT,
    entity_type      TEXT,                     -- individual / llc / trust / corp
    mailing_address  TEXT,
    mailing_city     TEXT,
    mailing_state    TEXT,
    mailing_zip      TEXT,
    phone            TEXT,
    email            TEXT,
    pof_doc_path     TEXT,
    pof_expiry       DATE,
    deals_assigned   INTEGER DEFAULT 0,
    deals_closed     INTEGER DEFAULT 0,
    reliability_pct  NUMERIC GENERATED ALWAYS AS (
                         CASE WHEN deals_assigned > 0
                         THEN ROUND((deals_closed::NUMERIC / deals_assigned) * 100, 1)
                         ELSE NULL END
                     ) STORED,
    is_verified      BOOLEAN DEFAULT FALSE,
    notes            TEXT,
    last_updated     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS buyer_purchases (
    id               SERIAL PRIMARY KEY,
    buyer_id         INTEGER REFERENCES cash_buyers(id),
    parcel_id        TEXT,
    purchase_date    DATE,
    purchase_price   NUMERIC,
    property_type    TEXT,
    situs_zip        TEXT,
    doc_number       TEXT,
    source           TEXT DEFAULT 'deed_record'
);

CREATE INDEX IF NOT EXISTS idx_buyer_purchases_buyer ON buyer_purchases(buyer_id);
CREATE INDEX IF NOT EXISTS idx_buyer_purchases_zip ON buyer_purchases(situs_zip);

CREATE TABLE IF NOT EXISTS buyer_buyboxes (
    id               SERIAL PRIMARY KEY,
    buyer_id         INTEGER REFERENCES cash_buyers(id) ON DELETE CASCADE,
    min_price        NUMERIC,
    max_price        NUMERIC,
    zip_codes        TEXT[],
    property_types   TEXT[],
    strategies       TEXT[],                   -- flip / rental / brrrr
    min_beds         INTEGER,
    max_repairs      NUMERIC,
    inferred         BOOLEAN DEFAULT TRUE,     -- auto-inferred vs manually set
    last_updated     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(buyer_id)
);

-- ─────────────────────────────────────────────
-- VALUATION
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS valuations (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    arv_estimate     NUMERIC,
    price_per_sqft   NUMERIC,
    comp_count       INTEGER,
    radius_miles     NUMERIC,
    months_back      INTEGER,
    confidence       TEXT,                     -- HIGH / MEDIUM / LOW
    method           TEXT DEFAULT 'deed_comps',
    calc_date        DATE DEFAULT CURRENT_DATE,
    est_monthly_rent NUMERIC,
    cap_rate_arv     NUMERIC,
    gross_rent_mult  NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_valuations_parcel ON valuations(parcel_id);

CREATE TABLE IF NOT EXISTS comps (
    id               SERIAL PRIMARY KEY,
    subject_parcel   TEXT,
    comp_parcel      TEXT,
    sale_price       NUMERIC,
    sale_date        DATE,
    sqft             NUMERIC,
    price_per_sqft   NUMERIC,
    distance_miles   NUMERIC,
    similarity_score NUMERIC,
    included         BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_comps_subject ON comps(subject_parcel);

CREATE TABLE IF NOT EXISTS repair_estimates (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    condition_tier   TEXT,                     -- light / medium / full
    line_items       JSONB,                    -- array of {category, item, low, high, qty, notes}
    total_low        NUMERIC,
    total_high       NUMERIC,
    contingency_pct  NUMERIC DEFAULT 12,
    created_date     TIMESTAMPTZ DEFAULT NOW(),
    notes            TEXT,
    text_input       TEXT                      -- the raw text the user typed
);

CREATE INDEX IF NOT EXISTS idx_repairs_parcel ON repair_estimates(parcel_id);

-- ─────────────────────────────────────────────
-- LEADS & PIPELINE
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS leads (
    id               SERIAL PRIMARY KEY,
    parcel_id        TEXT REFERENCES parcels(parcel_id) ON DELETE CASCADE,
    source           TEXT,                     -- driving / hcad_list / foreclosure / referral / 311 / probate / other
    date_added       TIMESTAMPTZ DEFAULT NOW(),
    motivated_score  INTEGER,                  -- 0–100
    deal_score       INTEGER,                  -- 0–100
    status           TEXT DEFAULT 'lead',      -- lead/contacted/negotiating/under_contract/buyer_found/closing/closed/dead
    priority         TEXT DEFAULT 'normal',    -- hot / warm / normal / cold
    notes            TEXT,
    assigned_to      TEXT,
    last_status_change TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_parcel ON leads(parcel_id);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(motivated_score DESC);

CREATE TABLE IF NOT EXISTS lead_photos (
    id           SERIAL PRIMARY KEY,
    lead_id      INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    file_path    TEXT,
    caption      TEXT,
    condition_tag TEXT,                        -- roof / exterior / interior / damage / other
    taken_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS deal_scores (
    id                 SERIAL PRIMARY KEY,
    lead_id            INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    tax_score          INTEGER DEFAULT 0,
    violation_score    INTEGER DEFAULT 0,
    vacancy_score      INTEGER DEFAULT 0,
    foreclosure_score  INTEGER DEFAULT 0,
    probate_score      INTEGER DEFAULT 0,
    absentee_score     INTEGER DEFAULT 0,
    portfolio_score    INTEGER DEFAULT 0,
    total_motivated    INTEGER DEFAULT 0,
    deal_score         INTEGER DEFAULT 0,
    score_version      TEXT DEFAULT '1.0',
    calc_date          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scores_lead ON deal_scores(lead_id);

CREATE TABLE IF NOT EXISTS lead_contact_log (
    id             SERIAL PRIMARY KEY,
    lead_id        INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    contact_date   TIMESTAMPTZ DEFAULT NOW(),
    method         TEXT,                       -- mail / phone / door / text / email
    outcome        TEXT,                       -- no_answer / left_vm / spoke / interested / not_interested / callback / hostile
    notes          TEXT,
    next_followup  DATE,
    script_used    TEXT
);

CREATE INDEX IF NOT EXISTS idx_contact_lead ON lead_contact_log(lead_id);
CREATE INDEX IF NOT EXISTS idx_contact_followup ON lead_contact_log(next_followup);

-- ─────────────────────────────────────────────
-- DEALS & OFFERS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS offer_options (
    id               SERIAL PRIMARY KEY,
    lead_id          INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    scenario         TEXT,                     -- conservative / standard / aggressive
    arv              NUMERIC,
    arv_pct          NUMERIC,
    repair_tier      TEXT,
    repair_cost      NUMERIC,
    closing_costs    NUMERIC DEFAULT 3000,
    target_fee       NUMERIC DEFAULT 10000,
    offer_price      NUMERIC,
    net_to_seller    NUMERIC,
    buyer_profit     NUMERIC,
    feasible         BOOLEAN,
    calc_date        DATE DEFAULT CURRENT_DATE
);

CREATE INDEX IF NOT EXISTS idx_offers_lead ON offer_options(lead_id);

CREATE TABLE IF NOT EXISTS active_deals (
    id                    SERIAL PRIMARY KEY,
    lead_id               INTEGER REFERENCES leads(id),
    seller_name           TEXT,
    seller_phone          TEXT,
    seller_email          TEXT,
    contract_date         DATE,
    purchase_price        NUMERIC,
    option_period_days    INTEGER DEFAULT 10,
    option_expiry         DATE,
    closing_date          DATE,
    title_company         TEXT,
    title_company_contact TEXT,
    earnest_money_amount  NUMERIC,
    em_status             TEXT DEFAULT 'pending', -- pending / deposited / released / refunded
    assignment_fee_target NUMERIC,
    status                TEXT DEFAULT 'active',  -- active / assigned / closed / terminated
    notes                 TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deals_lead ON active_deals(lead_id);
CREATE INDEX IF NOT EXISTS idx_deals_option ON active_deals(option_expiry);
CREATE INDEX IF NOT EXISTS idx_deals_status ON active_deals(status);

-- ─────────────────────────────────────────────
-- CONTRACTS & DOCUMENTS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contracts (
    id               SERIAL PRIMARY KEY,
    deal_id          INTEGER REFERENCES active_deals(id),
    contract_type    TEXT,                     -- seller_psa / assignment / double_close_ab / double_close_bc
    template_version TEXT,
    generated_date   TIMESTAMPTZ DEFAULT NOW(),
    signed_date      TIMESTAMPTZ,
    doc_path         TEXT,
    docusign_id      TEXT,
    status           TEXT DEFAULT 'draft'      -- draft / sent / signed / voided
);

CREATE TABLE IF NOT EXISTS document_vault (
    id           SERIAL PRIMARY KEY,
    deal_id      INTEGER REFERENCES active_deals(id),
    doc_type     TEXT,
    file_path    TEXT,
    upload_date  TIMESTAMPTZ DEFAULT NOW(),
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS escrow (
    id                   SERIAL PRIMARY KEY,
    deal_id              INTEGER REFERENCES active_deals(id),
    deposit_type         TEXT,                 -- earnest_money / buyer_deposit / assignment_fee
    amount               NUMERIC,
    held_by              TEXT,
    title_company_phone  TEXT,
    status               TEXT DEFAULT 'pending', -- pending / deposited / released / refunded / forfeited
    deposit_date         DATE,
    release_date         DATE,
    due_date             DATE,
    notes                TEXT
);

CREATE INDEX IF NOT EXISTS idx_escrow_deal ON escrow(deal_id);
CREATE INDEX IF NOT EXISTS idx_escrow_due ON escrow(due_date);

-- ─────────────────────────────────────────────
-- BUYER MATCHING & DEALS
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS matched_buyers (
    id             SERIAL PRIMARY KEY,
    deal_id        INTEGER REFERENCES active_deals(id),
    buyer_id       INTEGER REFERENCES cash_buyers(id),
    match_score    NUMERIC,
    notified       BOOLEAN DEFAULT FALSE,
    notified_date  TIMESTAMPTZ,
    response       TEXT                        -- interested / passed / no_response
);

CREATE TABLE IF NOT EXISTS deal_broadcasts (
    id           SERIAL PRIMARY KEY,
    deal_id      INTEGER REFERENCES active_deals(id),
    channel      TEXT,                         -- craigslist / biggerpockets / facebook / connected_investors
    posted_date  TIMESTAMPTZ,
    post_url     TEXT,
    responses    INTEGER DEFAULT 0
);

-- ─────────────────────────────────────────────
-- OUTREACH
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS outreach_log (
    id            SERIAL PRIMARY KEY,
    lead_id       INTEGER REFERENCES leads(id),
    outreach_date TIMESTAMPTZ DEFAULT NOW(),
    channel       TEXT,
    template_used TEXT,
    response_flag BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS mail_queue (
    id              SERIAL PRIMARY KEY,
    lead_id         INTEGER REFERENCES leads(id),
    piece_type      TEXT,                      -- postcard / letter / flyer
    status          TEXT DEFAULT 'queued',     -- queued / printed / sent / returned
    scheduled_date  DATE,
    sent_date       DATE
);

-- ─────────────────────────────────────────────
-- BUSINESS TRACKING
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS outcomes (
    id             SERIAL PRIMARY KEY,
    lead_id        INTEGER REFERENCES leads(id),
    outcome        TEXT,                       -- closed / dead / expired / assigned
    outcome_date   TIMESTAMPTZ DEFAULT NOW(),
    reason         TEXT,
    assignment_fee NUMERIC,
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS assignment_fees (
    id           SERIAL PRIMARY KEY,
    deal_id      INTEGER REFERENCES active_deals(id),
    buyer_id     INTEGER REFERENCES cash_buyers(id),
    fee_amount   NUMERIC,
    paid_date    DATE,
    tax_year     INTEGER GENERATED ALWAYS AS (EXTRACT(YEAR FROM paid_date)::INTEGER) STORED
);

-- ─────────────────────────────────────────────
-- SYSTEM
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cache (
    url_hash     TEXT PRIMARY KEY,
    url          TEXT,
    response_body TEXT,
    fetched_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id           SERIAL PRIMARY KEY,
    job_name     TEXT,
    started_at   TIMESTAMPTZ DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    status       TEXT DEFAULT 'running',       -- running / success / error
    records_processed INTEGER DEFAULT 0,
    records_inserted  INTEGER DEFAULT 0,
    records_updated   INTEGER DEFAULT 0,
    error_message TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           BIGSERIAL PRIMARY KEY,
    table_name   TEXT,
    record_id    TEXT,
    action       TEXT,                         -- INSERT / UPDATE / DELETE
    changed_by   TEXT DEFAULT 'system',
    changed_at   TIMESTAMPTZ DEFAULT NOW(),
    old_values   JSONB,
    new_values   JSONB
);
