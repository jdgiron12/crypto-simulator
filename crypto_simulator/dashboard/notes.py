"""Collapsed notes beneath a dashboard view (Phase 24, Step 5).

Display only. A view's first caption says what it shows; the notes that
follow it — how a figure is derived, what an ``n/a`` means, an edge case —
are kept, word for word, in one collapsed expander beneath it, so the
results read first and the detail stays one click away.
"""

from __future__ import annotations

import streamlit as st

__all__ = ["NOTES_LABEL", "render_notes"]

NOTES_LABEL = "Notes on these figures"


def render_notes(*notes: str) -> None:
    """Draw ``notes`` as captions inside one collapsed expander."""
    with st.expander(NOTES_LABEL):
        for note in notes:
            st.caption(note)
