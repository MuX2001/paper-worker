from unittest.mock import patch

from typer.testing import CliRunner

from paper_worker.cli import app


def test_cli_options():
    with patch("paper_worker.cli.run_pipeline") as pipeline:
        result = CliRunner().invoke(app, ["run", "1706.03762", "--no-zotero", "--no-obsidian"])
    assert result.exit_code == 0, result.output
    assert pipeline.call_args.kwargs["zotero"] is False
    assert pipeline.call_args.kwargs["obsidian"] is False


def test_cli_error():
    with patch("paper_worker.cli.run_pipeline", side_effect=ValueError("invalid paper")):
        result = CliRunner().invoke(app, ["run", "bad"])
    assert result.exit_code == 1
    assert "invalid paper" in result.output
