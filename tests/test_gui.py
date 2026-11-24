import time
import tkinter as tk
from unittest.mock import patch

import pytest

from paper_worker.gui import PaperWorkerApp, create_root


def test_gui_background_and_settings(tmp_path):
    try:
        root = create_root()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    app = PaperWorkerApp(root, tmp_path / "config.yaml")
    try:
        assert str(app.poll_button["state"]) == "disabled"
        app.fields["obsidian_vault_dir"].set(str(tmp_path / "notes"))
        app.save()
        assert (tmp_path / "config.yaml").exists()
        app.paper_input.set("1706.03762")

        def fake_run(*args, **kwargs):
            kwargs["log"]("Background progress")

        with patch("paper_worker.gui.run_pipeline", side_effect=fake_run) as runner:
            app.start(False)
            assert app.busy
            deadline = time.monotonic() + 3
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            runner.assert_called_once()
        assert not app.busy
        assert app.status.get() == "Completed"
        assert "Background progress" in app.log_widget.get("1.0", "end")
        assert str(app.log_widget["state"]) == "disabled"
    finally:
        app.close()
