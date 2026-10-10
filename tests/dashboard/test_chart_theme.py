"""Rendered dashboard charts carry the shared template (Phase 24, Step 2).

Drives the real dashboard through a run and checks every chart it draws:
Streamlit's own chart theme is off, and each figure arrives with the
template's colors and with its font and backgrounds set on the figure
itself, which is what Streamlit's front end respects. The trace data is
asserted by the section tests; this only checks the styling arrived.
"""

from __future__ import annotations

import json

from streamlit.testing.v1 import AppTest

from crypto_simulator.visualization.style import CHART_TEMPLATE, COLORWAY, FONT_FAMILY


def _dashboard():
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard()


def test_every_rendered_chart_uses_the_shared_template():
    at = AppTest.from_function(_dashboard, default_timeout=90).run()
    at.checkbox(key="coin_dashboard_psychology").set_value(True)
    at.checkbox(key="coin_dashboard_events").set_value(True)
    at.button(key="coin_dashboard_run").click().run()
    rendered = at.get("plotly_chart")
    # price path, psychology, regimes, OHLC, volume by component, event state
    assert len(rendered) >= 6
    for element in rendered:
        assert element.proto.theme == ""
        layout = json.loads(element.proto.spec)["layout"]
        assert tuple(layout["template"]["layout"]["colorway"]) == COLORWAY
        # set on the figure itself, so Streamlit's front end keeps them
        assert layout["font"]["family"] == FONT_FAMILY
        assert layout["paper_bgcolor"] == CHART_TEMPLATE.layout.paper_bgcolor
        assert layout["plot_bgcolor"] == CHART_TEMPLATE.layout.plot_bgcolor
