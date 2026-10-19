"""Qt style sheet generated from design tokens. No color literals here (MOD-08)."""

from __future__ import annotations

from dfr.ui.tokens import SPACING, TYPE, Palette


def build_qss(p: Palette) -> str:
    s, t = SPACING, TYPE
    return f"""
    QWidget {{
        background: {p.panel}; color: {p.text};
        font-family: "{t.family}"; font-size: {t.body}pt;
        selection-background-color: {p.selection}; selection-color: {p.text};
    }}
    QMainWindow::separator {{ background: {p.border}; width: 2px; height: 2px; }}
    QMenuBar {{ background: {p.panel}; border-bottom: 1px solid {p.border}; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {p.hover}; }}
    QMenu {{ background: {p.surface}; border: 1px solid {p.border}; }}
    QToolBar {{ background: {p.panel}; border-bottom: 1px solid {p.border}; spacing: {s.xs}px; padding: {s.xs}px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 3px; padding: {s.xs}px {s.sm}px; }}
    QToolButton:hover {{ background: {p.hover}; border-color: {p.border}; }}
    QToolButton:checked {{ background: {p.selection}; }}
    QStatusBar {{ background: {p.panel}; border-top: 1px solid {p.border}; color: {p.text_muted}; }}

    QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; }}
    QDockWidget::title {{
        background: {p.panel_alt}; padding: {s.xs}px {s.md}px; border-bottom: 1px solid {p.border};
        text-transform: uppercase; font-size: {t.small}pt; color: {p.text_muted};
    }}

    QTabWidget::pane {{ border: 1px solid {p.border}; background: {p.canvas}; }}
    QTabBar::tab {{
        background: {p.panel_alt}; color: {p.text_muted}; padding: {s.sm}px {s.lg}px;
        border: 1px solid {p.border}; border-bottom: none; margin-right: 1px;
    }}
    QTabBar::tab:selected {{ background: {p.canvas}; color: {p.text}; border-top: 2px solid {p.accent}; }}
    QTabBar::tab:hover:!selected {{ background: {p.hover}; }}

    QTreeView, QTableView, QListView, QTextEdit, QPlainTextEdit {{
        background: {p.canvas}; alternate-background-color: {p.panel_alt};
        border: 1px solid {p.border}; gridline-color: {p.border};
    }}
    QHeaderView::section {{
        background: {p.panel_alt}; color: {p.text_muted}; padding: {s.xs}px {s.sm}px;
        border: none; border-right: 1px solid {p.border}; border-bottom: 1px solid {p.border};
    }}
    QTreeView::item:selected, QTableView::item:selected, QListView::item:selected {{ background: {p.selection}; }}
    QTreeView::item:hover, QListView::item:hover {{ background: {p.hover}; }}

    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 2px; padding: {s.xs}px {s.sm}px;
    }}
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {p.accent}; }}
    QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; }}
    QPushButton {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 3px; padding: {s.xs}px {s.lg}px;
    }}
    QPushButton:hover {{ background: {p.hover}; }}
    QPushButton:default, QPushButton[accent="true"] {{ background: {p.accent}; color: {p.accent_text}; border-color: {p.accent}; }}
    QPushButton:disabled {{ color: {p.text_disabled}; }}
    QGroupBox {{ border: 1px solid {p.border}; border-radius: 3px; margin-top: {s.lg}px; padding-top: {s.sm}px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: {s.md}px; padding: 0 {s.xs}px; color: {p.text_muted}; }}
    QLabel[role="heading"] {{ font-size: {t.heading}pt; font-weight: 600; }}
    QLabel[role="title"] {{ font-size: {t.title}pt; font-weight: 600; }}
    QLabel[role="muted"] {{ color: {p.text_muted}; }}
    QScrollBar:vertical {{ background: {p.panel_alt}; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; min-height: 24px; border-radius: 4px; }}
    QScrollBar:horizontal {{ background: {p.panel_alt}; height: 10px; }}
    QScrollBar::handle:horizontal {{ background: {p.border}; min-width: 24px; border-radius: 4px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QSplitter::handle {{ background: {p.border}; }}
    QProgressBar {{ background: {p.surface}; border: 1px solid {p.border}; text-align: center; }}
    QProgressBar::chunk {{ background: {p.accent}; }}
    QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; }}
    """
