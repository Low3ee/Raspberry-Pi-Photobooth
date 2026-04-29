from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, List, Optional

from .camera import CameraError, build_camera
from .config import PhotoboothConfig
from .layouts import create_print_layout
from .money import MockMoneyDevice, MoneyDevice, MoneyError, build_money_device
from .printer import PrinterError, build_printer
from .storage import Store


class PhotoBoothApp:
    def __init__(self, root: tk.Tk, config: PhotoboothConfig):
        self.root = root
        self.config = config
        self.data_dir = config.app.data_dir
        self.store = Store(self.data_dir / "photobooth.sqlite3")
        self.camera = build_camera(config.camera)
        self.printer = build_printer(config.printer, self.data_dir)
        self.money: MoneyDevice = build_money_device(config.money)
        self.event_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self.session_id: Optional[str] = None
        self.balance_cents = 0
        self.photo_paths: List[Path] = []
        self.print_path: Optional[Path] = None
        self.preview_image = None

        self.root.title(config.app.title)
        self.root.configure(bg="#0f172a")
        self.root.geometry("900x700")
        if config.app.fullscreen:
            self.root.attributes("-fullscreen", True)

        self.root.bind("<Escape>", self._toggle_fullscreen)
        self.root.bind("<Control-q>", lambda _event: self.shutdown())
        self.root.bind("<Control-a>", lambda _event: self.show_admin())
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self._configure_styles()

    def run(self) -> None:
        try:
            self.money.open()
            self.store.log_event("app_started", "Photobooth started")
            self.show_idle()
            self.root.after(100, self._drain_queue)
            self.root.mainloop()
        finally:
            self.money.close()
            self.store.close()

    def show_idle(self) -> None:
        self.session_id = None
        self.balance_cents = 0
        self.photo_paths = []
        self.print_path = None
        self._clear()
        self._header(self.config.app.title, "Ready")
        self._big_text(self._format_money(self.config.app.price_cents), "price.TLabel")
        self._button("Start", self.begin_payment, primary=True).pack(pady=20)
        self._button("Admin", self.show_admin).pack(pady=8)

    def begin_payment(self) -> None:
        self.session_id = self.store.create_session(self.config.app.price_cents, self.config.app.currency)
        self.balance_cents = 0
        self.money.start_transaction(self.config.app.price_cents)
        self.store.log_event("payment_started", "Payment started", payload={"session_id": self.session_id})
        self.show_payment()

    def show_payment(self) -> None:
        self._clear()
        self._header("Insert Payment", f"Due {self._format_money(self.config.app.price_cents)}")
        self.balance_label = self._big_text(self._format_money(self.balance_cents), "price.TLabel")
        due = max(0, self.config.app.price_cents - self.balance_cents)
        self.due_label = ttk.Label(self.root, text=f"Remaining {self._format_money(due)}", style="subtitle.TLabel")
        self.due_label.pack(pady=(0, 24))
        if isinstance(self.money, MockMoneyDevice):
            controls = ttk.Frame(self.root, style="surface.TFrame")
            controls.pack(pady=10)
            self._button("+ 1.00", lambda: self.money.credit(100), parent=controls).grid(row=0, column=0, padx=8)
            self._button("Pay Exact", lambda: self.money.credit(self.config.app.price_cents), parent=controls).grid(
                row=0, column=1, padx=8
            )
        self._button("Cancel", self.cancel_payment).pack(pady=18)
        self.root.after(self.config.money.poll_interval_ms, self._poll_payment)

    def cancel_payment(self) -> None:
        if self.session_id:
            self.store.set_session_status(self.session_id, "cancelled")
            if self.config.app.refund_on_cancel and self.balance_cents > 0:
                try:
                    event = self.money.dispense(self.balance_cents)
                    self.store.add_payment(self.session_id, "refund", -event.cents, event.message)
                except Exception as exc:
                    self.store.log_event("refund_failed", str(exc), level="error", payload={"session_id": self.session_id})
            self.money.cancel_transaction()
        self.show_idle()

    def _poll_payment(self) -> None:
        if not self.session_id:
            return
        try:
            events = self.money.poll_events()
        except MoneyError as exc:
            self.show_error("Payment Hardware Error", str(exc), self.show_idle)
            return

        paid = False
        for event in events:
            if event.kind == "credit":
                self.balance_cents += event.cents
                self.store.add_payment(self.session_id, "credit", event.cents, event.message)
            elif event.kind == "paid":
                paid = True
            elif event.kind == "error":
                self.store.log_event("money_error", event.message, level="error", payload={"session_id": self.session_id})
                self.show_error("Payment Error", event.message, self.show_idle)
                return

        if events:
            due = max(0, self.config.app.price_cents - self.balance_cents)
            self.balance_label.configure(text=self._format_money(self.balance_cents))
            self.due_label.configure(text=f"Remaining {self._format_money(due)}")

        if paid or self.balance_cents >= self.config.app.price_cents:
            self.money.finish_transaction()
            overpay = max(0, self.balance_cents - self.config.app.price_cents)
            if overpay:
                try:
                    event = self.money.dispense(overpay)
                    self.store.add_payment(self.session_id, "change", -event.cents, event.message)
                except Exception as exc:
                    self.store.log_event("change_failed", str(exc), level="error", payload={"session_id": self.session_id})
            self.start_capture()
            return

        self.root.after(self.config.money.poll_interval_ms, self._poll_payment)

    def start_capture(self) -> None:
        if not self.session_id:
            return
        self.store.set_session_status(self.session_id, "capturing")
        self.photo_paths = []
        self._countdown(1, self.config.app.countdown_seconds)

    def _countdown(self, photo_number: int, remaining: int) -> None:
        self._clear()
        self._header(f"Photo {photo_number} of {self.config.app.photo_count}", "Look at the camera")
        self._big_text(str(remaining) if remaining else "Smile", "countdown.TLabel")
        if remaining > 0:
            self.root.after(1000, lambda: self._countdown(photo_number, remaining - 1))
        else:
            self._capture_photo(photo_number)

    def _capture_photo(self, photo_number: int) -> None:
        assert self.session_id
        path = self.data_dir / "photos" / self.session_id / f"photo-{photo_number}.jpg"
        self._busy("Capturing")
        self._worker(
            lambda: self.camera.capture_photo(path),
            lambda result: self._after_capture(photo_number, Path(result)),
            lambda exc: self.show_error("Camera Error", str(exc), self.show_idle),
        )

    def _after_capture(self, photo_number: int, path: Path) -> None:
        self.photo_paths.append(path)
        self.store.attach_photos(self.session_id or "", self.photo_paths)
        if photo_number < self.config.app.photo_count:
            self._countdown(photo_number + 1, self.config.app.countdown_seconds)
        else:
            self._build_layout()

    def _build_layout(self) -> None:
        assert self.session_id
        self.store.set_session_status(self.session_id, "layout")
        self.print_path = self.data_dir / "prints" / self.session_id / "print.jpg"
        self._busy("Preparing Print")
        self._worker(
            lambda: create_print_layout(self.photo_paths, self.print_path, self.config.layout, self.config.app.title),
            lambda result: self._after_layout(Path(result)),
            lambda exc: self.show_error("Layout Error", str(exc), self.show_idle),
        )

    def _after_layout(self, path: Path) -> None:
        self.print_path = path
        if self.session_id:
            self.store.attach_print(self.session_id, path)
            self.store.set_session_status(self.session_id, "preview")
        self.show_preview()
        if self.config.app.auto_print:
            self.root.after(1200, self.print_current)

    def show_preview(self) -> None:
        self._clear()
        self._header("Preview", "Print is ready")
        if self.print_path:
            from PIL import Image, ImageTk

            with Image.open(self.print_path) as img:
                img.thumbnail((430, 560))
                self.preview_image = ImageTk.PhotoImage(img.copy())
            ttk.Label(self.root, image=self.preview_image, style="surface.TLabel").pack(pady=12)
        buttons = ttk.Frame(self.root, style="surface.TFrame")
        buttons.pack(pady=12)
        self._button("Print", self.print_current, parent=buttons, primary=True).grid(row=0, column=0, padx=8)
        if self.config.app.allow_retake:
            self._button("Retake", self.start_capture, parent=buttons).grid(row=0, column=1, padx=8)
        self._button("Finish", self.show_idle, parent=buttons).grid(row=0, column=2, padx=8)

    def print_current(self) -> None:
        if not self.session_id or not self.print_path:
            self.show_idle()
            return
        job_id = self.store.create_print_job(self.session_id, self.print_path)
        self.store.set_session_status(self.session_id, "printing")
        self._busy("Printing")
        self._worker(
            lambda: self.printer.print_file(self.print_path, copies=self.config.printer.copies),
            lambda _result: self._after_print(job_id),
            lambda exc: self._print_failed(job_id, exc),
        )

    def _after_print(self, job_id: str) -> None:
        self.store.complete_print_job(job_id)
        if self.session_id:
            self.store.set_session_status(self.session_id, "complete")
        self._clear()
        self._header("Done", "Thank you")
        self._button("Next Customer", self.show_idle, primary=True).pack(pady=28)
        self.root.after(6000, self.show_idle)

    def _print_failed(self, job_id: str, exc: BaseException) -> None:
        self.store.complete_print_job(job_id, str(exc))
        self.show_error("Printer Error", str(exc), self.show_preview)

    def show_admin(self) -> None:
        rows = self.store.recent_sessions(8)
        self._clear()
        self._header("Admin", "Local booth status")
        body = ttk.Frame(self.root, style="surface.TFrame")
        body.pack(pady=16, padx=24, fill="both", expand=True)
        stats = f"Sessions: {len(rows)}   Data: {self.data_dir}"
        ttk.Label(body, text=stats, style="body.TLabel", wraplength=760).pack(anchor="w", pady=(0, 12))
        for row in rows:
            text = (
                f"{row['created_at']}  {row['status']}  "
                f"paid {self._format_money(row['total_paid_cents'])}"
            )
            ttk.Label(body, text=text, style="small.TLabel").pack(anchor="w", pady=2)
        buttons = ttk.Frame(self.root, style="surface.TFrame")
        buttons.pack(pady=12)
        self._button("Test Payout", self._test_payout, parent=buttons).grid(row=0, column=0, padx=8)
        self._button("Back", self.show_idle, parent=buttons, primary=True).grid(row=0, column=1, padx=8)
        self._button("Quit", self.shutdown, parent=buttons).grid(row=0, column=2, padx=8)

    def _test_payout(self) -> None:
        try:
            event = self.money.dispense(self.config.money.payout_cents_per_pulse)
            self.store.log_event("test_payout", event.message, payload={"cents": event.cents})
            self.show_admin()
        except Exception as exc:
            self.show_error("Payout Error", str(exc), self.show_admin)

    def show_error(self, title: str, detail: str, next_action: Callable[[], None]) -> None:
        self._clear()
        self._header(title, "Action required")
        ttk.Label(self.root, text=detail, style="body.TLabel", wraplength=760, justify="center").pack(pady=20)
        self._button("Continue", next_action, primary=True).pack(pady=18)

    def shutdown(self) -> None:
        self.store.log_event("app_stopped", "Photobooth stopped")
        self.root.destroy()

    def _worker(
        self,
        work: Callable[[], object],
        done: Callable[[object], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        def run() -> None:
            try:
                result = work()
            except BaseException as exc:
                self.event_queue.put(lambda exc=exc: failed(exc))
            else:
                self.event_queue.put(lambda result=result: done(result))

        threading.Thread(target=run, daemon=True).start()

    def _drain_queue(self) -> None:
        while True:
            try:
                callback = self.event_queue.get_nowait()
            except queue.Empty:
                break
            callback()
        self.root.after(100, self._drain_queue)

    def _clear(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def _header(self, title: str, subtitle: str) -> None:
        ttk.Label(self.root, text=title, style="title.TLabel").pack(pady=(42, 8))
        ttk.Label(self.root, text=subtitle, style="subtitle.TLabel").pack(pady=(0, 18))

    def _big_text(self, text: str, style: str) -> ttk.Label:
        label = ttk.Label(self.root, text=text, style=style)
        label.pack(pady=10)
        return label

    def _button(
        self,
        text: str,
        command: Callable[[], None],
        parent=None,
        primary: bool = False,
    ) -> ttk.Button:
        return ttk.Button(parent or self.root, text=text, command=command, style="primary.TButton" if primary else "TButton")

    def _busy(self, title: str) -> None:
        self._clear()
        self._header(title, "Please wait")
        bar = ttk.Progressbar(self.root, mode="indeterminate", length=360)
        bar.pack(pady=30)
        bar.start(12)

    def _configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("surface.TFrame", background="#0f172a")
        style.configure("surface.TLabel", background="#0f172a")
        style.configure("title.TLabel", background="#0f172a", foreground="#f8fafc", font=("Helvetica", 40, "bold"))
        style.configure("subtitle.TLabel", background="#0f172a", foreground="#cbd5e1", font=("Helvetica", 20))
        style.configure("body.TLabel", background="#0f172a", foreground="#e2e8f0", font=("Helvetica", 18))
        style.configure("small.TLabel", background="#0f172a", foreground="#cbd5e1", font=("Helvetica", 12))
        style.configure("price.TLabel", background="#0f172a", foreground="#38bdf8", font=("Helvetica", 56, "bold"))
        style.configure("countdown.TLabel", background="#0f172a", foreground="#fbbf24", font=("Helvetica", 100, "bold"))
        style.configure("TButton", font=("Helvetica", 18), padding=(24, 14), background="#334155", foreground="#f8fafc")
        style.configure("primary.TButton", font=("Helvetica", 20, "bold"), padding=(32, 16), background="#0ea5e9", foreground="#082f49")
        style.map("TButton", background=[("active", "#475569")])
        style.map("primary.TButton", background=[("active", "#38bdf8")])

    def _toggle_fullscreen(self, _event) -> None:
        current = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not current)

    def _format_money(self, cents: int) -> str:
        sign = "-" if cents < 0 else ""
        return f"{sign}{self.config.app.currency} {abs(cents) / 100:.2f}"


def run_app(config: PhotoboothConfig) -> None:
    root = tk.Tk()
    app = PhotoBoothApp(root, config)
    app.run()
