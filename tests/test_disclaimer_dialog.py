from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISCLAIMER_DIALOG = PROJECT_ROOT / "src" / "ui" / "dialogs" / "disclaimer_dialog.py"


def source_text() -> str:
    return DISCLAIMER_DIALOG.read_text(encoding="utf-8")


def test_disclaimer_uses_rich_text_widget_for_bold_content():
    text = source_text()

    assert "QTextBrowser" in text
    assert "content_label = BodyLabel(content_text)" not in text


def test_disclaimer_names_author_readably():
    text = source_text()

    assert "B站UP主 古霍（UID: 1876277780）" in text
    assert "'uid:1876277780'" not in text


def test_disclaimer_styles_follow_current_theme():
    text = source_text()

    assert "isDarkTheme" in text
    assert "def _theme_colors" in text
    assert "QDialog {" in text
    assert "cancel_btn.setStyleSheet" in text
    assert "color: #34495E" not in text
    assert "background-color: #F8F9FA" not in text
