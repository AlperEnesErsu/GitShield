"""`gitshield.web.review` re-exports the helpers that moved to review_* modules."""

import gitshield.web.review as review
from gitshield.web import review_diff, review_format, review_memory, review_progress, review_schemas


def test_moved_names_are_still_importable_from_review():
    assert review.map_old_line is review_diff.map_old_line
    assert review.build_diff is review_diff.build_diff
    assert review.suppressing_memory is review_memory.suppressing_memory
    assert review.Progress is review_progress.Progress
    assert review.ReviewOutput is review_schemas.ReviewOutput
    assert review.draft_issue_body is review_format.draft_issue_body
