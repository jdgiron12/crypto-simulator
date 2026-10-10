"""A row of figures that wraps instead of truncating (Phase 24, Step 6).

Display only. Fixed ``st.columns`` give every figure the same share of the
width, so on a medium page — about 860px with the sidebar open — a long
label such as "Share of participant volume" is cut short. Here the figures
sit in a row that wraps (``st.container(horizontal=True)``, available since
the 1.53 floor), each as wide as its own label and value: a narrow page
moves a figure to the next line, and a phone still fits two short figures
side by side.
"""

from __future__ import annotations

from typing import Sequence

import streamlit as st

__all__ = ["render_metric_row"]


def render_metric_row(metrics: Sequence[tuple[str, str]]) -> None:
    """Draw ``(label, value)`` pairs, in order, as one wrapping row."""
    with st.container(horizontal=True, horizontal_alignment="distribute", gap="medium"):
        for label, value in metrics:
            st.metric(label, value, width="content")
