import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import Config, load_config, save_config
from .pipeline import run_pipeline
from .supabase_queue import poll_queue


def create_root() -> tk.Tk:
    # Relocated Windows Python installs can lose their Tcl library search path.
    if sys.platform == "win32":
        libraries = Path(sys.base_prefix) / "tcl"
        for variable, pattern, marker in (
            ("TCL_LIBRARY", "tcl8.*", "init.tcl"),
            ("TK_LIBRARY", "tk8.*", "tk.tcl"),
        ):
            if variable not in os.environ:
                for path in sorted(libraries.glob(pattern), reverse=True):
                    if (path / marker).is_file():
                        os.environ[variable] = str(path)
                        break
    return tk.Tk()


class PaperWorkerApp:
    def __init__(self, root: tk.Tk, config_path: Path):
        self.root = root
        self.config_path = config_path
        self.config = load_config(config_path)
        self.messages = queue.Queue()
        self.busy = False
        root.title("paper-worker")
        root.geometry("680x520")
        root.minsize(620, 500)
        root.protocol("WM_DELETE_WINDOW", self.close)
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        run_tab = ttk.Frame(notebook, padding=12)
        settings_tab = ttk.Frame(notebook, padding=12)
        notebook.add(run_tab, text="Run")
        notebook.add(settings_tab, text="Settings")
        ttk.Label(run_tab, text="arXiv URL / ID").pack(anchor="w")
        self.paper_input = tk.StringVar()
        ttk.Entry(run_tab, textvariable=self.paper_input).pack(fill="x", pady=(4, 10))
        options = ttk.Frame(run_tab)
        options.pack(fill="x")
        self.obsidian = tk.BooleanVar(value=True)
        self.zotero = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Save to Obsidian", variable=self.obsidian).pack(side="left")
        ttk.Checkbutton(options, text="Sync to Zotero", variable=self.zotero).pack(
            side="left", padx=16
        )
        actions = ttk.Frame(run_tab)
        actions.pack(fill="x", pady=12)
        self.run_button = ttk.Button(actions, text="Run Paper", command=lambda: self.start(False))
        self.run_button.pack(side="left")
        self.poll_button = ttk.Button(
            actions, text="Poll Supabase Queue", command=lambda: self.start(True)
        )
        self.poll_button.pack(side="left", padx=10)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(run_tab, textvariable=self.status).pack(anchor="w")
        self.log_widget = ScrolledText(run_tab, wrap="word", state="disabled", height=16)
        self.log_widget.pack(fill="both", expand=True, pady=(6, 0))

        self.fields = {}
        values = {
            "obsidian_vault_dir": str(self.config.obsidian_vault_dir),
            "codex_command": self.config.codex_command,
            "github_token": self.config.github_token.get_secret_value(),
            "library_id": self.config.zotero.library_id,
            "library_type": self.config.zotero.library_type,
            "api_key": self.config.zotero.api_key.get_secret_value(),
            "collection_key": self.config.zotero.collection_key,
            "supabase_url": self.config.supabase.url,
            "supabase_key": self.config.supabase.key.get_secret_value(),
        }
        labels = [
            "Obsidian Output Directory",
            "Codex CLI Command",
            "GitHub Token",
            "Zotero Library ID",
            "Zotero Library Type",
            "Zotero API Key",
            "Zotero Collection (optional)",
            "Supabase URL (optional)",
            "Supabase Key (optional)",
        ]
        settings_tab.columnconfigure(1, weight=1)
        for row, ((key, value), label) in enumerate(zip(values.items(), labels)):
            ttk.Label(settings_tab, text=label).grid(row=row, column=0, sticky="w", pady=6)
            variable = tk.StringVar(value=value)
            self.fields[key] = variable
            if key == "library_type":
                widget = ttk.Combobox(
                    settings_tab, textvariable=variable, values=["user", "group"], state="readonly"
                )
            else:
                widget = ttk.Entry(
                    settings_tab,
                    textvariable=variable,
                    show="*" if key in {"github_token", "api_key", "supabase_key"} else "",
                )
            widget.grid(row=row, column=1, sticky="ew", padx=8)
            if key == "obsidian_vault_dir":
                ttk.Button(settings_tab, text="Browse…", command=self.browse).grid(
                    row=row, column=2
                )
        self.save_button = ttk.Button(settings_tab, text="Save Settings", command=self.save)
        self.save_button.grid(row=10, column=1, sticky="w", padx=8, pady=12)
        ttk.Label(
            settings_tab,
            text="Zotero sync uses Web API credentials, even when the desktop app is open.",
            wraplength=580,
        ).grid(row=11, column=0, columnspan=3, sticky="w")
        self.refresh_buttons()
        self.after_id = root.after(100, self.drain_messages)

    def browse(self):
        selected = filedialog.askdirectory(parent=self.root)
        if selected:
            self.fields["obsidian_vault_dir"].set(selected)

    def save(self):
        try:
            data = self.config.model_dump()
            for key in ("obsidian_vault_dir", "codex_command", "github_token"):
                data[key] = self.fields[key].get().strip()
            for key in ("library_id", "library_type", "api_key", "collection_key"):
                data["zotero"][key] = self.fields[key].get().strip()
            data["supabase"] = {
                "url": self.fields["supabase_url"].get().strip(),
                "key": self.fields["supabase_key"].get().strip(),
            }
            validated = Config.model_validate(data)
            save_config(validated, self.config_path)
            self.config = load_config(self.config_path)
            self.refresh_buttons()
            self.status.set("Settings saved")
        except Exception:
            # Pydantic input repr can include secrets; do not display it.
            messagebox.showerror(
                "Settings",
                "Settings are invalid or could not be saved. Check paths, command and complete credential pairs.",
                parent=self.root,
            )

    def refresh_buttons(self):
        self.run_button.configure(state="disabled" if self.busy else "normal")
        self.poll_button.configure(
            state="normal" if self.config.supabase.enabled and not self.busy else "disabled"
        )
        self.save_button.configure(state="disabled" if self.busy else "normal")

    def start(self, polling: bool):
        if self.busy:
            return
        value = self.paper_input.get().strip()
        if not polling and not value:
            self.status.set("Enter an arXiv URL or ID")
            return
        # Snapshot all Tk values on the UI thread before launching worker.
        config = self.config.model_copy(deep=True)
        options = {"obsidian": self.obsidian.get(), "zotero": self.zotero.get()}
        self.busy = True
        self.status.set("Running…")
        self.refresh_buttons()

        def worker():
            try:

                def logger(text):
                    self.messages.put(("log", str(text)))

                if polling:
                    result = poll_queue(config, log=logger, **options)
                    self.messages.put(
                        (
                            "done",
                            "Completed" if not result.failed else "Completed with failed tasks",
                        )
                    )
                else:
                    run_pipeline(value, config, log=logger, **options)
                    self.messages.put(("done", "Completed"))
            except Exception as exc:
                text = str(exc)
                for secret in (
                    config.github_token.get_secret_value(),
                    config.zotero.api_key.get_secret_value(),
                    config.supabase.key.get_secret_value(),
                ):
                    if secret:
                        text = text.replace(secret, "[REDACTED]")
                self.messages.put(("log", f"Error: {text}"))
                self.messages.put(("done", "Failed — see log"))

        threading.Thread(target=worker, name="paper-worker", daemon=False).start()

    def drain_messages(self):
        try:
            while True:
                kind, text = self.messages.get_nowait()
                if kind == "done":
                    self.busy = False
                    self.status.set(text)
                    self.refresh_buttons()
                else:
                    self.log_widget.configure(state="normal")
                    self.log_widget.insert("end", text + "\n")
                    self.log_widget.see("end")
                    self.log_widget.configure(state="disabled")
        except queue.Empty:
            pass
        self.after_id = self.root.after(100, self.drain_messages)

    def close(self):
        if self.busy:
            messagebox.showinfo(
                "Task running",
                "Wait for the current task to finish before closing.",
                parent=self.root,
            )
            return
        self.root.after_cancel(self.after_id)
        self.root.destroy()


def launch_gui(config_path: Path):
    root = create_root()
    try:
        PaperWorkerApp(root, config_path)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
