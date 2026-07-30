import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils.db import execute

SCORE_VERSION = "v1.0-hcad"


def run_batch_score() -> dict:
    """
    Score all parcels in SQL and populate leads + deal_scores.
    Safe to re-run — deletes hcad_auto leads and recomputes from scratch.
    Returns counts.
    """
    # Clean previous auto-scored run (cascades to deal_scores)
    execute("DELETE FROM leads WHERE source = 'hcad_auto'", commit=True)

    # Create leads for every parcel with at least one distress signal
    execute("""
        INSERT INTO leads (parcel_id, source, date_added, status, priority)
        SELECT DISTINCT ON (p.parcel_id)
            p.parcel_id,
            'hcad_auto',
            NOW(),
            'new',
            CASE
                WHEN b.condition = 'Very Low' THEN 'high'
                WHEN b.condition = 'Low'      THEN 'medium'
                WHEN o.is_absentee            THEN 'low'
                ELSE 'low'
            END
        FROM parcels p
        LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        LEFT JOIN owners    o ON o.parcel_id  = p.parcel_id
        WHERE
            o.is_absentee = TRUE
            OR b.condition IN ('Low', 'Very Low')
            OR (b.id IS NULL AND COALESCE(p.improvement_val, 0) < 5000)
    """, commit=True)

    # Compute scores and insert into deal_scores
    execute("""
        INSERT INTO deal_scores (
            lead_id,
            absentee_score, vacancy_score, portfolio_score,
            tax_score, violation_score, foreclosure_score, probate_score,
            total_motivated, score_version, calc_date
        )
        SELECT
            l.id,
            -- Absentee owner (3 pts)
            CASE WHEN o.is_absentee THEN 3 ELSE 0 END,
            -- Condition / vacancy (max 15 pts)
            CASE
                WHEN b.condition = 'Very Low'                              THEN 15
                WHEN b.condition = 'Low'                                   THEN 10
                WHEN b.id IS NULL AND COALESCE(p.improvement_val,0) < 1000 THEN 8
                WHEN b.year_built < 1960 AND b.condition = 'Average'       THEN 3
                ELSE 0
            END,
            -- Portfolio owner (max 2 pts): owner_name appears on many parcels
            CASE WHEN pc.parcel_count >= 5 THEN 2
                 WHEN pc.parcel_count >= 3 THEN 1
                 ELSE 0
            END,
            0, 0, 0, 0,
            -- total_motivated
            CASE WHEN o.is_absentee THEN 3 ELSE 0 END
            + CASE
                WHEN b.condition = 'Very Low'                              THEN 15
                WHEN b.condition = 'Low'                                   THEN 10
                WHEN b.id IS NULL AND COALESCE(p.improvement_val,0) < 1000 THEN 8
                WHEN b.year_built < 1960 AND b.condition = 'Average'       THEN 3
                ELSE 0
              END
            + CASE WHEN pc.parcel_count >= 5 THEN 2
                   WHEN pc.parcel_count >= 3 THEN 1
                   ELSE 0
              END,
            %s,
            NOW()
        FROM leads l
        JOIN parcels p ON p.parcel_id = l.parcel_id
        LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        LEFT JOIN owners    o ON o.parcel_id  = p.parcel_id
        LEFT JOIN (
            SELECT o2.owner_name, COUNT(*) AS parcel_count
            FROM owners o2
            WHERE o2.owner_name IS NOT NULL
            GROUP BY o2.owner_name
        ) pc ON pc.owner_name = o.owner_name
        WHERE l.source = 'hcad_auto'
    """, (SCORE_VERSION,), commit=True)

    # Push scores back to leads.motivated_score + priority
    execute("""
        UPDATE leads l
        SET
            motivated_score = ds.total_motivated,
            priority = CASE
                WHEN ds.total_motivated >= 15 THEN 'high'
                WHEN ds.total_motivated >= 8  THEN 'medium'
                ELSE 'low'
            END
        FROM deal_scores ds
        WHERE ds.lead_id = l.id AND l.source = 'hcad_auto'
    """, commit=True)

    counts = execute("""
        SELECT
            COUNT(*)                                 AS total_leads,
            COUNT(*) FILTER (WHERE motivated_score >= 15) AS high,
            COUNT(*) FILTER (WHERE motivated_score >= 8
                              AND  motivated_score < 15)  AS medium,
            COUNT(*) FILTER (WHERE motivated_score > 0
                              AND  motivated_score < 8)   AS low_score
        FROM leads
        WHERE source = 'hcad_auto'
    """)[0]
    return dict(counts)
