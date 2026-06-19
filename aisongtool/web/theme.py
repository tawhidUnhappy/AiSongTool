"""Material 3 (the design language Android 15 ships) theming for the app.

NiceGUI/Quasar isn't Material 3 out of the box (Quasar follows Material 2
conventions: uppercase button text, small corner radii, underline tab
indicators). This applies the Material 3 baseline dark color tokens plus the
shape/typography overrides needed to get the M3 look: pill buttons, large
rounded "surface container" cards, pill tab indicators, no uppercase text.
"""
from __future__ import annotations

from nicegui import ui

# Material 3 baseline dark color scheme tokens — the same palette Android's
# own Material 3 design spec uses for its default dark theme.
M3_DARK = {
    "primary": "#D0BCFF",
    "secondary": "#CCC2DC",
    "accent": "#EFB8C8",       # M3 "tertiary"
    "dark": "#211F26",         # M3 "surface container high"
    "dark_page": "#141218",    # M3 "surface dim" / background
    "positive": "#9CCC65",
    "negative": "#F2B8B5",     # M3 "error" (dark scheme)
    "warning": "#FFD54F",
    "info": "#9FCAFF",
}

_CSS = """
.q-btn {
    border-radius: 100px !important;
    text-transform: none !important;
    font-weight: 500;
    letter-spacing: normal !important;
}
.q-card {
    border-radius: 28px !important;
}
.q-field__control, .q-field--outlined .q-field__control {
    border-radius: 16px !important;
}
.q-header {
    border-radius: 0 0 24px 24px;
    box-shadow: none !important;
}
.q-tabs {
    border-radius: 100px;
}
.q-tab {
    border-radius: 100px !important;
    margin: 4px 2px;
    min-height: 40px;
}
.q-tab--active {
    background: rgba(255, 255, 255, 0.12);
}
.q-tab__indicator {
    display: none;
}
.body--dark {
    background: #141218;
}
"""


def apply() -> None:
    ui.colors(**M3_DARK)
    ui.add_css(_CSS)
