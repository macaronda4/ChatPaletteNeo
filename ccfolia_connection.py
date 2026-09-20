"""Headless CCFOLIA UI adapter. All browser operations belong to one worker.

No private API, credentials on disk, or visible browser windows are used.
Selectors follow the Japanese UI; unsupported UI changes fail closed.
"""
from dataclasses import dataclass
from queue import Empty, Queue
import re
from threading import Event, Thread
from urllib.parse import urlsplit


def room_url(value):
    value = value.strip()
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "ccfolia.com"
            or not re.fullmatch(r"/rooms/[A-Za-z0-9_-]+(/chat)?/?", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("https://ccfolia.com/rooms/ルームID/ の形式で入力してください。")
    return value.rstrip("/")


class AccessUnavailable(Exception):
    pass


class ConnectionProblem(Exception):
    pass


class SendUncertain(ConnectionProblem):
    pass


class HeadlessRoom:
    """Only call from the connection worker. Imported lazily for offline editing."""

    def __init__(self):
        self.runtime = self.browser = self.context = self.page = None
        self.url = None

    def _launch(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ConnectionProblem(
                "接続用ライブラリがありません。pip install -r requirements.txt と "
                "python -m playwright install chromium を実行してください。"
            ) from None
        try:
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch(headless=True, timeout=20000)
            self.context = self.browser.new_context(locale="ja-JP", viewport={"width": 1280, "height": 720})
            self.page = self.context.new_page()
            self.page.set_default_timeout(8000)
            self.page.set_default_navigation_timeout(25000)
        except Exception:
            self.close()
            raise ConnectionProblem(
                "バックグラウンドブラウザを起動できません。"
                "python -m playwright install chromium の実行を確認してください。"
            ) from None

    def _login(self, email, password):
        # User opts in to email/password login in the application's inline form.
        # Never log exception details: Playwright errors can contain field values.
        self.page.goto("https://ccfolia.com/home", wait_until="domcontentloaded")
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_role("textbox", name="メールアドレス", exact=True).fill(email)
        dialog.get_by_label("パスワード", exact=True).fill(password)
        dialog.get_by_role("button", name="ログイン", exact=True).click()
        try:
            dialog.wait_for(state="hidden", timeout=20000)
        except Exception:
            raise AccessUnavailable(
                "ログインを完了できませんでした。入力内容または認証方式を確認してください。"
                "追加認証やSNSログインには対応していません。"
            ) from None

    def _message_box(self):
        return self.page.get_by_placeholder("メッセージを入力", exact=True)

    def _denied(self):
        return (self.page.get_by_text("アクセスが制限されています", exact=True).is_visible()
                or self.page.get_by_text("見学者はメッセージを送信できません", exact=True).is_visible())

    def _main_tab(self):
        tabs = self.page.get_by_role("tab")
        # Accessible names can include notification badges or an aria-label.
        # Match the visible label as well, without matching e.g. "メイン相談".
        return (
            self.page.get_by_role("tab", name="メイン", exact=True)
            .or_(tabs.filter(has_text=re.compile(r"^\s*メイン\s*$")))
            .or_(tabs.filter(has=self.page.get_by_text("メイン", exact=True)))
            .and_(self.page.locator(":visible"))
        )

    def _select_main_tab(self):
        from playwright.sync_api import expect
        tab = self._main_tab()
        try:
            # Do not silently choose the first match if the target is ambiguous.
            expect(tab).to_have_count(1, timeout=8000)
        except Exception:
            tabs = self.page.get_by_role("tab").and_(self.page.locator(":visible"))
            labels = self.page.get_by_text("メイン", exact=True).and_(self.page.locator(":visible"))
            raise ConnectionProblem(
                "送信先の「メイン」を特定できません。"
                f"（表示中のtab要素: {tabs.count()}、"
                f"「メイン」の表示: {labels.count()}、候補: {tab.count()}）"
                "タブ名やHTMLのroleを確認してください。送信は行っていません。"
            ) from None
        try:
            tab.click()
            # React updates aria-selected asynchronously after the click.
            expect(tab).to_have_attribute("aria-selected", "true", timeout=8000)
        except Exception:
            raise ConnectionProblem(
                "「メイン」の選択完了を確認できません。送信は行っていません。"
            ) from None

    def connect(self, url, credentials=None):
        print(url)
        self.url = room_url(url)
        self._launch()
        try:
            if credentials:
                try:
                    self._login(*credentials)
                except Exception:
                    raise AccessUnavailable(
                        "ログインできませんでした。入力内容・通信状態・認証方式を確認してください。"
                        "SNS認証や追加認証には対応していません。"
                    ) from None
            self.page.goto(self.url, wait_until="domcontentloaded")
            try:
                self._message_box().wait_for(state="visible", timeout=20000)
            except Exception:
                if self._denied() or self.page.get_by_role("heading", name="Signin", exact=True).is_visible():
                    raise AccessUnavailable("このルームへ投稿できません。必要な場合のみログインしてください。") from None
                raise ConnectionProblem(
                    "チャット欄を確認できません。URL・通信・ルームの公開状態を確認してください。"
                ) from None
            if self._denied() or not self._message_box().is_enabled():
                raise AccessUnavailable("投稿権限がありません。別のアカウントでのログインは任意です。")
            if room_url(self.page.url) != self.url:
                raise ConnectionProblem("指定したルームと接続先が一致しません。")
            # Never inherit a secret/group channel implicitly.
            self._select_main_tab()
        except (AccessUnavailable, ConnectionProblem):
            raise
        except Exception as e:
            print(e)
            raise ConnectionProblem("接続に失敗しました。通信状態やココフォリアの画面変更を確認してください。") from None

    def alive(self):
        try:
            return (self.browser is not None and self.browser.is_connected()
                    and not self.page.is_closed() and room_url(self.page.url) == self.url
                    and not self._denied() and self._message_box().is_visible()
                    and self._message_box().is_enabled())
        except Exception:
            return False

    def send(self, payload):
        if not self.alive():
            raise ConnectionProblem("接続が失われています。再接続してください。")
        text = payload["text"]
        speaker = payload["speaker"]
        if not text.strip() or not speaker.strip():
            raise ConnectionProblem("話者と本文を入力してください。")
        try:
            self._select_main_tab()
            name = self.page.get_by_label("名前", exact=True)
            name.fill(speaker)
            name.press("Tab")
            if name.input_value() != speaker:
                raise ConnectionProblem("話者を設定できません。")
            box = self._message_box()
            box.fill(text)
            if box.input_value() != text:
                raise ConnectionProblem("本文を設定できません。")
            button = self.page.get_by_role("button", name="送信", exact=True)
            button.wait_for(state="visible")
            if not button.is_enabled():
                raise ConnectionProblem("送信ボタンが無効です。")
        except ConnectionProblem:
            raise
        except Exception:
            raise ConnectionProblem("チャットの入力操作に失敗しました。送信は行っていません。") from None
        try:
            button.click()
            from playwright.sync_api import expect
            expect(box).to_have_value("", timeout=10000)
        except Exception:
            # Clicking may already have posted the message. Never retry it.
            raise SendUncertain("送信結果を確認できません。再送する前にルームのログを確認してください。") from None
        # Input reset is NOT proof of server delivery.
        return "送信操作完了（到達未確認）"

    def close(self):
        for obj in (self.context, self.browser):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        if self.runtime is not None:
            try:
                self.runtime.stop()
            except Exception:
                pass
        self.runtime = self.browser = self.context = self.page = None


@dataclass(frozen=True)
class ConnectionEvent:
    state: str
    message: str = ""
    login_available: bool = False


class ConnectionWorker:
    """Serial queue prevents concurrent connects/sends and cross-thread Tk calls."""

    def __init__(self, backend_factory=HeadlessRoom):
        self.events = Queue()
        self.commands = Queue()
        self.stopping = Event()
        self.backend_factory = backend_factory
        self.thread = None

    def submit(self, command, *args):
        if self.stopping.is_set():
            return
        if self.thread is None:
            self.thread = Thread(target=self._run, name="ccfolia-connection", daemon=True)
            self.thread.start()
        self.commands.put((command, args))

    def close(self):
        self.stopping.set()
        self.commands.put(("close", ()))

    def _run(self):
        backend = None
        try:
            while not self.stopping.is_set():
                try:
                    command, args = self.commands.get(timeout=1)
                except Empty:
                    if backend and not backend.alive():
                        backend.close()
                        backend = None
                        self.events.put(ConnectionEvent("disconnected", "接続が失われました。再接続してください。"))
                    continue
                if self.stopping.is_set() or command == "close":
                    break
                if command == "connect":
                    try:
                        if backend:
                            backend.close()
                        backend = self.backend_factory()
                        backend.connect(*args)
                        self.events.put(ConnectionEvent("connected", "接続済み・送信先: メイン"))
                    except Exception as error:
                        if backend:
                            backend.close()
                        backend = None
                        message = str(error) if isinstance(error, (AccessUnavailable, ConnectionProblem)) else "接続に失敗しました。"
                        self.events.put(ConnectionEvent("disconnected", message, isinstance(error, AccessUnavailable)))
                    finally:
                        args = ()  # Do not retain the password while waiting for another command.
                elif command == "disconnect":
                    if backend:
                        backend.close()
                    backend = None
                    self.events.put(ConnectionEvent("disconnected", "切断しました。"))
                elif command == "send":
                    try:
                        if backend is None:
                            raise ConnectionProblem("接続されていません。")
                        message = backend.send(*args)
                        self.events.put(ConnectionEvent("connected", message))
                    except Exception as error:
                        message = str(error) if isinstance(error, ConnectionProblem) else "送信結果が不明です。ルームのログを確認してください。"
                        self.events.put(ConnectionEvent("connected" if backend and backend.alive() else "disconnected", message))
                        if backend and not backend.alive():
                            backend.close()
                            backend = None
        finally:
            if backend:
                backend.close()
            while True:
                try:
                    self.commands.get_nowait()
                except Empty:
                    break
