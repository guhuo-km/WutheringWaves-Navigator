from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ABOUT_INTERFACE = PROJECT_ROOT / "src" / "ui" / "interfaces" / "about_interface.py"


def source_text() -> str:
    return ABOUT_INTERFACE.read_text(encoding="utf-8")


def test_update_status_is_not_pushed_to_header_right_edge():
    text = source_text()

    assert "header_layout.addWidget(self.update_status_label)" not in text
    assert "self.update_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)" not in text


def test_update_info_grid_uses_compact_two_row_layout():
    text = source_text()

    assert "card_layout.setContentsMargins(20, 12, 20, 12)" in text
    assert "card_layout.setSpacing(6)" in text
    assert "info_grid.setVerticalSpacing(4)" in text
    assert "info_grid.addWidget(self.update_version_label, 0, 0)" in text
    assert "info_grid.addWidget(self.update_status_label, 0, 1)" in text
    assert "info_grid.addWidget(self.update_checked_label, 1, 0)" in text
    assert "info_grid.addWidget(self.update_mode_label, 1, 1)" in text
    assert "info_grid.addWidget(self.update_reason_label, 2, 0, 1, 2)" in text


def test_update_available_labels_release_notes_as_changelog():
    text = source_text()

    assert "release_notes: str = \"\"" in text
    assert "about_update_release_notes" in text
    assert "更新日志:" in text
    assert "notes=release_notes.strip()" in text
