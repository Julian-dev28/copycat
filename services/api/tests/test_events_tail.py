from __future__ import annotations

from pathlib import Path

from api.events_tail import read_new_lines, start_offset


def test_start_offset_missing_file_is_zero(tmp_path: Path) -> None:
    assert start_offset(tmp_path / "events.jsonl") == 0


def test_start_offset_existing_file_is_end(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text('{"a": 1}\n')
    assert start_offset(p) == p.stat().st_size


def test_read_new_lines_missing_file(tmp_path: Path) -> None:
    pos, lines = read_new_lines(tmp_path / "events.jsonl", 0)
    assert pos == 0
    assert lines == []


def test_read_new_lines_returns_complete_lines_and_advances_pos(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n')
    pos, lines = read_new_lines(p, 0)
    assert lines == ['{"a": 1}', '{"a": 2}']
    assert pos == p.stat().st_size

    # nothing new since pos
    pos2, lines2 = read_new_lines(p, pos)
    assert lines2 == []
    assert pos2 == pos


def test_read_new_lines_withholds_partial_trailing_line(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text('{"a": 1}\n{"a": 2')  # second line not yet newline-terminated
    pos, lines = read_new_lines(p, 0)
    assert lines == ['{"a": 1}']
    assert pos == len('{"a": 1}\n'.encode("utf-8"))

    with p.open("a", encoding="utf-8") as f:
        f.write("}\n")
    pos2, lines2 = read_new_lines(p, pos)
    assert lines2 == ['{"a": 2}']
    assert pos2 == p.stat().st_size


def test_read_new_lines_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text('{"a": 1}\n\n{"a": 2}\n')
    _, lines = read_new_lines(p, 0)
    assert lines == ['{"a": 1}', '{"a": 2}']
