"""Cohort labels + summary."""
from typing import Optional

from fastapi import APIRouter, Depends

import cohort as cohort_mod

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["cohorts"])


@router.get("/cohorts/labels")
async def cohort_labels(user: dict = Depends(require_board("cohort"))):
    """Returns the list of cohort labels from Monday's 'Cohort Joined' dropdown."""
    return await cohort_mod.fetch_cohort_labels()


@router.get("/cohorts/summary")
async def cohort_summary_endpoint(
    cohort: str = "April 26",
    circle_tag: Optional[str] = None,
    new_tag_id: Optional[int] = None,
    legacy_tag_id: Optional[int] = None,
    intros_space_id: Optional[int] = None,
    user: dict = Depends(require_board("cohort")),
):
    """Aggregated cohort stats. New / Legacy counts come from ConvertKit tags
    (authoritative). Circle cross-reference uses the cached members list."""
    return await cohort_mod.cohort_summary(
        db, cohort,
        circle_tag=circle_tag,
        new_tag_id=new_tag_id,
        legacy_tag_id=legacy_tag_id,
        intros_space_id=intros_space_id,
    )
