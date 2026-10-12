"""Design tokens for the Plotly layer.

Chart libraries cannot parse CSS colour functions, so every colour handed to
Plotly is a hex literal — the same values as the committed palette in
``static/theme.css``.
"""

from __future__ import annotations

from plotly import graph_objects as go

# Committed palette (hex twins of the CSS token set).
BACKGROUND = "#0c0c11"
CARD = "#16161d"
FOREGROUND = "#efeff5"
MUTED = "#212127"
MUTED_FOREGROUND = "#9d9da6"
BORDER = "#2d2d34"
ACCENT = "#9884f3"
INFO = "#38bdf8"
OK = "#34d399"
WARN = "#f0b429"
DESTRUCTIVE = "#c9302d"

STATUS_COLORS = {
    "new": WARN,
    "assigned": ACCENT,
    "collected": INFO,
    "rehomed": OK,
    "lost": DESTRUCTIVE,
    "not_found": MUTED_FOREGROUND,
}

FONT_FAMILY = "Chakra Petch, Rajdhani, system-ui, sans-serif"
FONT_HEADING = "Rajdhani, Chakra Petch, system-ui, sans-serif"

GRAPH_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
}


def base_layout(**overrides) -> dict:
    """Shared figure layout: transparent, grid-on-border, compact margins."""
    layout = {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": FONT_FAMILY, "size": 12, "color": FOREGROUND},
        "margin": {"l": 48, "r": 18, "t": 12, "b": 34},
        "hoverlabel": {
            "bgcolor": CARD,
            "bordercolor": BORDER,
            "font": {"family": FONT_FAMILY, "color": FOREGROUND, "size": 12},
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "font": {"size": 11, "color": MUTED_FOREGROUND},
            "bgcolor": "rgba(0,0,0,0)",
        },
        "showlegend": True,
    }
    layout.update(overrides)
    return layout


def axis_style(**overrides) -> dict:
    style = {
        "gridcolor": "rgba(45,45,52,0.85)",
        "zerolinecolor": BORDER,
        "linecolor": BORDER,
        "tickfont": {"size": 11, "color": MUTED_FOREGROUND},
        "color": MUTED_FOREGROUND,
    }
    style.update(overrides)
    return style


def empty_figure(message: str, height: int = 340) -> go.Figure:
    """A figure that explains the zero-row branch instead of drawing nothing."""
    figure = go.Figure()
    figure.update_layout(**base_layout(showlegend=False, height=height))
    figure.add_annotation(
        text=message,
        showarrow=False,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        font={"color": MUTED_FOREGROUND, "size": 13, "family": FONT_FAMILY},
        align="center",
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure
