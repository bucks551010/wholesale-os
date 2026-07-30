"""Run lead scoring. Safe to re-run at any time."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger()

from app.utils.scoring import run_batch_score

log.info("Starting batch score...")
counts = run_batch_score()
log.info(f"Done — {counts['total_leads']:,} leads scored")
log.info(f"  High priority  (score >= 15): {counts['high']:,}")
log.info(f"  Medium priority (score 8-14): {counts['medium']:,}")
log.info(f"  Low priority    (score 1-7):  {counts['low_score']:,}")
