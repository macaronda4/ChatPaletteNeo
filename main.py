import json
import math
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter
import config

FONT_TYPE = config.FONT_TYPE


def atomic_json(path, data):
    """同じフォルダに一時保存してから置換し、書き込み失敗で元データを壊さない。"""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".cpn-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class ProjectStore:
    """Explorerの順序・階層と、PJフォルダ内のJSONを管理する。"""

    def __init__(self, roots=None, path=None):
        self.roots = roots if roots is not None else []
        self.path = Path(path).resolve() if path else None
        self.pending = {}  # 新規Projectの、まだディスクへ保存していないファイル
        self.dirty = False

    def walk(self, nodes=None):
        for node in self.roots if nodes is None else nodes:
            yield node
            yield from self.walk(node.children)

    @staticmethod
    def validate_name(name):
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10))
        if (not isinstance(name, str) or not name or name in (".", "..")
                or name[-1:] in (" ", ".")
                or any(c in name for c in '/\\<>:"|?*')
                or any(ord(c) < 32 for c in name)
                or name.split(".")[0].upper() in reserved):
            raise ValueError("使用できない名前です。パス区切り文字などは含めないでください。")

    def relative_path(self, node):
        parts = []
        current = node
        while current is not None:
            self.validate_name(current.text)
            name = current.text
            if current.is_file and not name.lower().endswith(".json"):
                name += ".json"
            parts.append(name)
            current = current.parent
        return Path(*reversed(parts))

    def disk_path(self, node):
        if self.path is None:
            raise ValueError("先にProjectを保存してください。")
        result = self.path.parent / self.relative_path(node)
        # シンボリックリンクを含め、PJフォルダ外への書き込みを許可しない。
        if not result.resolve().is_relative_to(self.path.parent):
            raise ValueError("Projectフォルダの外を参照しています。")
        if any(p.is_symlink() for p in (result, *result.parents) if p != self.path.parent):
            raise ValueError("シンボリックリンクは扱えません。")
        if result.resolve() == self.path:
            raise ValueError("Projectファイルと同じ名前は使用できません。")
        return result

    def validate(self):
        seen = set()
        for node in self.walk():
            key = self.relative_path(node).as_posix().casefold()
            if key in seen:
                raise ValueError(f"同じ場所に同名の項目があります: {node.text}")
            seen.add(key)
            if node.is_file and node.children:
                raise ValueError("ファイルは子を持てません。")
            if self.path:
                self.disk_path(node)

    def data(self):
        def serialize(node):
            result = node.to_dict()
            metadata = dict(node.data) if isinstance(node.data, dict) else {}
            if node.data is not None and not isinstance(node.data, dict):
                metadata["legacy_data"] = node.data
            metadata["path"] = self.relative_path(node).as_posix()
            result["data"] = metadata
            result["children"] = [serialize(child) for child in node.children]
            return result
        return [serialize(node) for node in self.roots]

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, list):
            raise ValueError("CPNのルートはツリーの配列である必要があります。")
        project = cls([TreeNode.from_dict(item) for item in data], path)
        project.validate()
        return project

    def read_file(self, node):
        if node in self.pending:
            return dict(self.pending[node])
        with self.disk_path(node).open(encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict) or not all(
            isinstance(payload.get(key), str) for key in ("speaker", "text")
        ):
            raise ValueError("JSONには文字列のspeakerとtextが必要です。")
        return {"speaker": payload["speaker"], "text": payload["text"]}

    def save_file(self, node, payload):
        if self.path is None:
            self.pending[node] = dict(payload)
            self.dirty = True
        else:
            atomic_json(self.disk_path(node), payload)

    def save(self, path=None):
        old_path = self.path
        self.path = Path(path).resolve() if path else self.path
        created = []
        try:
            self.validate()
            if self.path is None:
                raise ValueError("保存先を選択してください。")
            # 新規ファイルは既存ファイルを上書きしない。
            for node in self.pending:
                if self.disk_path(node).exists():
                    raise FileExistsError(f"保存先に既存ファイルがあります: {self.relative_path(node)}")
            for node in self.walk():
                destination = self.disk_path(node)
                if node.is_directory:
                    if not destination.exists():
                        destination.mkdir()
                        created.append(destination)
                    elif not destination.is_dir():
                        raise FileExistsError(f"同名のファイルがあります: {destination.name}")
                elif node in self.pending:
                    atomic_json(destination, self.pending[node])
                    created.append(destination)
            atomic_json(self.path, self.data())
        except Exception:
            for entry in reversed(created):
                if entry.is_dir():
                    entry.rmdir()
                else:
                    entry.unlink()
            self.path = old_path
            raise
        self.pending.clear()
        self.dirty = False

    def create(self, parent, name, kind):
        name = name.strip()
        self.validate_name(name)
        if kind == TreeNode.FILE and not name.lower().endswith(".json"):
            name += ".json"
        self.validate_name(name)
        if parent is not None and not parent.is_directory:
            raise ValueError("ファイルの中に項目は作成できません。")
        node = TreeNode(name, node_type=kind, parent=parent)
        siblings = self.roots if parent is None else parent.children
        siblings.append(node)
        old_dirty = self.dirty
        try:
            self.validate()
            if self.path and self.disk_path(node).exists():
                raise FileExistsError("同名のファイルまたはディレクトリが既に存在します。")
            if node.is_file:
                self.pending[node] = {"speaker": "", "text": ""}
            self.dirty = True
            if self.path:
                self.save()
        except Exception:
            siblings.remove(node)
            self.pending.pop(node, None)
            self.dirty = old_dirty
            raise
        if parent is not None:
            parent.expanded = True
        return node

    def move(self, source, target, position):
        if target is source or (target and source.is_ancestor_of(target)):
            return False
        if position == "root_end":
            parent = None
        elif target is None:
            return False
        elif position == "inside" and target.is_directory:
            parent = target
        elif position in ("before", "after"):
            parent = target.parent
        else:
            return False
        old_parent = source.parent
        old_siblings = self.roots if old_parent is None else old_parent.children
        old_index = old_siblings.index(source)
        old_path = self.disk_path(source) if self.path else None
        old_dirty = self.dirty
        old_siblings.pop(old_index)
        siblings = self.roots if parent is None else parent.children
        index = len(siblings) if position in ("inside", "root_end") else siblings.index(target) + (position == "after")
        siblings.insert(index, source)
        source.parent = parent
        moved = False
        try:
            self.validate()
            if self.path:
                new_path = self.disk_path(source)
                if old_path != new_path:
                    if new_path.exists():
                        raise FileExistsError("移動先に同名のファイルまたはディレクトリがあります。")
                    old_path.rename(new_path)
                    moved = True
                self.save()
            else:
                self.dirty = True
        except Exception:
            if moved:
                new_path.rename(old_path)
            siblings.remove(source)
            old_siblings.insert(old_index, source)
            source.parent = old_parent
            self.dirty = old_dirty
            raise
        if parent:
            parent.expanded = True
        return True


class ModernContextMenu(customtkinter.CTkToplevel):
    """CustomTkinterの外観に合わせた、軽量な右クリックメニュー。"""

    WIDTH = 230

    def __init__(self, master, title, items, x, y):
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(master)
        self.configure(fg_color=("#F5F6F8", "#202225"))

        panel = customtkinter.CTkFrame(
            self,
            corner_radius=10,
            border_width=1,
            border_color=("#D7DADE", "#41454B"),
            fg_color=("#F5F6F8", "#202225"),
        )
        panel.pack(fill="both", expand=True)
        customtkinter.CTkLabel(
            panel,
            text=title,
            anchor="w",
            font=(FONT_TYPE, 12),
            text_color=("#60656D", "#AEB4BC"),
        ).pack(fill="x", padx=13, pady=(10, 5))

        for item in items:
            if item is None:
                customtkinter.CTkFrame(
                    panel,
                    height=1,
                    corner_radius=0,
                    fg_color=("#D7DADE", "#41454B"),
                ).pack(fill="x", padx=10, pady=5)
                continue
            label, command = item
            customtkinter.CTkButton(
                panel,
                text=label,
                command=lambda callback=command: self._run(callback),
                anchor="w",
                height=36,
                corner_radius=6,
                fg_color="transparent",
                hover_color=("#E1E8F2", "#333A44"),
                text_color=("#1B1D20", "#F1F3F5"),
                font=(FONT_TYPE, 14),
            ).pack(fill="x", padx=7, pady=2)

        self.update_idletasks()
        width = self.WIDTH
        height = self.winfo_reqheight()
        x = min(max(0, x), self.winfo_screenwidth() - width)
        y = min(max(0, y), self.winfo_screenheight() - height)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.deiconify()
        self.lift()
        self.focus_force()
        # 子ボタンへのフォーカス移動を待ってから、外側クリックで閉じる。
        self.after(100, lambda: self.bind("<FocusOut>", self._close_if_focus_left))

    def _run(self, command):
        self.destroy()
        command()

    def _close_if_focus_left(self, _event):
        def check():
            if not self.winfo_exists():
                return
            focused = self.focus_get()
            if focused is None or focused.winfo_toplevel() is not self:
                self.destroy()

        self.after(20, check)


class ModernNameDialog(customtkinter.CTkToplevel):
    """ファイル／ディレクトリ名を入力するモーダルダイアログ。"""

    def __init__(self, master, kind):
        super().__init__(master)
        self.result = None
        self.kind = kind
        label = "ファイル" if kind == TreeNode.FILE else "ディレクトリ"

        self.title(f"新規{label}")
        self.geometry("420x210")
        self.resizable(False, False)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        customtkinter.CTkLabel(
            self,
            text=f"新規{label}",
            anchor="w",
            font=(FONT_TYPE, 20, "bold"),
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="ew")

        content = customtkinter.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, padx=24, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(
            content,
            text=f"{label}名",
            anchor="w",
            text_color=("#555B63", "#B7BDC5"),
        ).grid(row=0, column=0, sticky="ew")
        placeholder = "例: scene01.json" if kind == TreeNode.FILE else "例: Chapter 1"
        self.entry = customtkinter.CTkEntry(
            content,
            height=40,
            corner_radius=8,
            placeholder_text=placeholder,
            font=(FONT_TYPE, 14),
        )
        self.entry.grid(row=1, column=0, pady=(5, 2), sticky="ew")
        self.error_label = customtkinter.CTkLabel(
            content,
            text="",
            anchor="w",
            height=20,
            text_color=("#C62828", "#FF7B72"),
            font=(FONT_TYPE, 12),
        )
        self.error_label.grid(row=2, column=0, sticky="ew")

        actions = customtkinter.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, padx=24, pady=(8, 20), sticky="e")
        customtkinter.CTkButton(
            actions,
            text="キャンセル",
            width=100,
            fg_color=("#D9DDE2", "#3A3D42"),
            hover_color=("#C8CDD3", "#4A4E54"),
            text_color=("#202124", "#F1F3F5"),
            command=self.destroy,
        ).grid(row=0, column=0, padx=(0, 8))
        customtkinter.CTkButton(
            actions,
            text="作成",
            width=100,
            command=self.submit,
        ).grid(row=0, column=1)

        self.bind("<Return>", self.submit)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after_idle(self._show)

    def _show(self):
        self.update_idletasks()
        master = self.master
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.entry.focus_set()

    def submit(self, _event=None):
        name = self.entry.get().strip()
        try:
            ProjectStore.validate_name(name)
            if self.kind == TreeNode.FILE and not name.lower().endswith(".json"):
                ProjectStore.validate_name(name + ".json")
        except ValueError as error:
            self.error_label.configure(text=str(error))
            self.entry.focus_set()
            return "break"
        self.result = name
        self.destroy()
        return "break"

    @classmethod
    def ask(cls, master, kind):
        dialog = cls(master, kind)
        master.wait_window(dialog)
        return dialog.result


class App(customtkinter.CTk):
    EXPLORER_WIDTH = 240
    CONTROL_WIDTH = 140

    def __init__(self):
        super().__init__()
        self.project = ProjectStore()
        self.current_node = None
        self.context_popup = None
        self.saved_payload = {"speaker": "", "text": ""}
        self.fonts = (FONT_TYPE, 15)
        self.setup_form()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

    def setup_form(self):
        customtkinter.set_appearance_mode("dark")
        self.geometry("1000x650")
        self.minsize(760, 400)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=self.CONTROL_WIDTH + 20)

        self.choosePjFile = ChoosePjFile(self, self.open_project, self.new_project)
        self.choosePjFile.grid(row=0, column=0, padx=(10, 0), pady=10, sticky="ew")
        self.url_input = UrlInput(self, self.fonts, self.CONTROL_WIDTH)
        self.url_input.room_url.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.url_input.room_connect.grid(row=0, column=2, padx=10, pady=10, sticky="ew")

        explorer = customtkinter.CTkFrame(self, width=self.EXPLORER_WIDTH)
        explorer.grid(row=1, column=0, padx=(10, 0), pady=(0, 10), sticky="nsew")
        explorer.grid_propagate(False)
        explorer.grid_columnconfigure(0, weight=1)
        explorer.grid_rowconfigure(1, weight=1)
        self.project_button = customtkinter.CTkButton(explorer, text="Project保存", command=self.save_project)
        self.project_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.tree = DragDropTree(
            explorer, on_file_click=self.file_clicked, on_move=self.move_node,
            on_context_menu=self.context_menu, label_text=""
        )
        self.tree.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="nsew")
        self.tree.root_nodes = self.project.roots

        # URL入力欄と同じ親・列・余白にして幅を一致させる。
        self.editor = customtkinter.CTkTextbox(self, font=self.fonts, wrap="word")
        self.editor.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="nsew")
        controls = customtkinter.CTkFrame(self, fg_color="transparent", width=self.CONTROL_WIDTH)
        controls.grid(row=1, column=2, padx=10, pady=(0, 10), sticky="nsew")
        controls.grid_columnconfigure(0, weight=1)
        self.speaker = customtkinter.CTkEntry(controls, placeholder_text="話者", width=self.CONTROL_WIDTH, font=self.fonts)
        self.speaker.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.previous_button = customtkinter.CTkButton(controls, text="前へ", command=lambda: self.navigate(-1), width=self.CONTROL_WIDTH)
        self.next_button = customtkinter.CTkButton(controls, text="次へ", command=lambda: self.navigate(1), width=self.CONTROL_WIDTH)
        self.save_button = customtkinter.CTkButton(controls, text="保存", command=self.save_current, width=self.CONTROL_WIDTH)
        self.send_button = customtkinter.CTkButton(controls, text="送信", command=self.send, width=self.CONTROL_WIDTH)
        for row, button in enumerate((self.previous_button, self.next_button, self.save_button, self.send_button), 1):
            button.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        self.current_label = customtkinter.CTkLabel(controls, text="ファイル未選択", wraplength=140, justify="left")
        self.current_label.grid(row=5, column=0, sticky="ew")
        self.editor.bind("<KeyRelease>", lambda event: self.update_status(), add="+")
        self.speaker.bind("<KeyRelease>", lambda event: self.update_status(), add="+")
        self.bind("<Control-s>", self.save_shortcut, add="+")
        self.clear_editor()

    def payload(self):
        return {"speaker": self.speaker.get(), "text": self.editor.get("1.0", "end-1c")}

    def is_dirty(self):
        return self.current_node is not None and self.payload() != self.saved_payload

    def update_status(self):
        dirty = self.is_dirty()
        project_name = self.project.path.name if self.project.path else "新規Project"
        self.title(f"{'* ' if dirty else ''}Chat Palette NEO — {project_name}")
        self.project_button.configure(text="Project保存" + (" *" if self.project.dirty else ""))
        if self.current_node:
            self.current_label.configure(text=f"{self.current_node.text}\n" + ("未保存" if dirty else "保存済み"))
        files = [n for n in self.project.walk() if n.is_file]
        index = files.index(self.current_node) if self.current_node in files else -1
        self.previous_button.configure(state="normal" if index > 0 else "disabled")
        self.next_button.configure(state="normal" if 0 <= index < len(files) - 1 else "disabled")

    def clear_editor(self):
        self.current_node = None
        self.tree.selected_node = None
        self.editor.configure(state="normal")
        self.speaker.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.speaker.delete(0, "end")
        self.editor.configure(state="disabled")
        self.speaker.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.send_button.configure(state="disabled")
        self.current_label.configure(text="ファイル未選択")
        self.update_status()

    def confirm_edits(self):
        if not self.is_dirty():
            return True
        answer = messagebox.askyesnocancel(
            "未保存の変更", f"{self.current_node.text} の変更を保存しますか？\n「いいえ」で破棄します。", parent=self
        )
        if answer is None:
            return False
        return self.save_current() if answer else True

    def confirm_project(self):
        if not self.confirm_edits():
            return False
        if self.project.dirty:
            answer = messagebox.askyesnocancel("Project未保存", "Projectを保存しますか？", parent=self)
            if answer is None:
                return False
            if answer and not self.save_project():
                return False
        return True

    def report_error(self, error):
        messagebox.showerror("操作できませんでした", str(error), parent=self)

    def file_clicked(self, node):
        if node is self.current_node:
            return
        try:
            payload = self.project.read_file(node)
        except (OSError, ValueError, TypeError) as error:
            self.report_error(error)
            return
        if not self.confirm_edits():
            return
        self.current_node = node
        self.saved_payload = dict(payload)
        self.editor.configure(state="normal")
        self.speaker.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", payload["text"])
        self.speaker.delete(0, "end")
        self.speaker.insert(0, payload["speaker"])
        self.save_button.configure(state="normal")
        self.send_button.configure(state="normal")
        self.tree.selected_node = node
        ancestor = node.parent
        while ancestor:
            ancestor.expanded = True
            ancestor = ancestor.parent
        self.tree.refresh()
        self.tree.after_idle(lambda: self.tree.reveal(node))
        self.update_status()

    def navigate(self, offset):
        files = [node for node in self.project.walk() if node.is_file]
        if self.current_node not in files:
            return
        index = files.index(self.current_node) + offset
        if 0 <= index < len(files):
            self.file_clicked(files[index])

    def save_current(self):
        if self.current_node is None:
            return True
        payload = self.payload()
        try:
            if self.project.path is None:
                # Project保存をキャンセルしたときも編集欄をそのまま保つ。
                previous = dict(self.project.pending[self.current_node])
                self.project.save_file(self.current_node, payload)
                if not self.save_project():
                    self.project.pending[self.current_node] = previous
                    return False
            else:
                self.project.save_file(self.current_node, payload)
        except (OSError, ValueError) as error:
            self.report_error(error)
            return False
        self.saved_payload = dict(payload)
        self.update_status()
        return True

    def save_shortcut(self, _event=None):
        """Ctrl+Sで、現在開いているファイルを保存する。"""
        self.save_current()
        return "break"

    def send(self):
        if self.current_node:
            print(json.dumps(self.payload(), ensure_ascii=False))

    def save_project(self):
        path = None
        if self.project.path is None:
            path = filedialog.asksaveasfilename(
                parent=self, title="Projectの保存場所と名前", defaultextension=".cpn",
                filetypes=[("ChatPaletteNeo Project", "*.cpn")], initialfile="Project.cpn"
            )
            if not path:
                return False
        try:
            self.project.save(path)
        except (OSError, ValueError) as error:
            self.report_error(error)
            return False
        self.update_status()
        return True

    def set_project(self, project):
        self.project = project
        self.tree.root_nodes = project.roots
        self.clear_editor()
        self.tree.refresh()

    def open_project(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("ChatPaletteNeo Project", "*.cpn")])
        if not path:
            return
        try:
            project = ProjectStore.load(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.report_error(error)
            return
        if self.confirm_project():
            # 同じProjectを再読み込みする場合も、保存後の内容を使用する。
            try:
                project = ProjectStore.load(path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.report_error(error)
                return
            self.set_project(project)

    def new_project(self):
        if self.confirm_project():
            self.set_project(ProjectStore())

    def close_app(self):
        if self.confirm_project():
            self.destroy()

    def move_node(self, source, target, position):
        try:
            changed = self.project.move(source, target, position)
        except (OSError, ValueError) as error:
            self.report_error(error)
            return False
        self.update_status()
        return changed

    def context_menu(self, node, event):
        parent = node if node and node.is_directory else (node.parent if node else None)
        if self.context_popup is not None and self.context_popup.winfo_exists():
            self.context_popup.destroy()
        location = parent.text if parent else "Projectルート"
        items = [
            ("＋  新規ファイル", lambda: self.create_node(parent, TreeNode.FILE)),
            ("▰  新規ディレクトリ", lambda: self.create_node(parent, TreeNode.DIRECTORY)),
        ]
        if parent:
            items.extend([
                None,
                ("＋  ルートに新規ファイル", lambda: self.create_node(None, TreeNode.FILE)),
                ("▰  ルートに新規ディレクトリ", lambda: self.create_node(None, TreeNode.DIRECTORY)),
            ])
        self.context_popup = ModernContextMenu(
            self, f"作成先: {location}", items, event.x_root, event.y_root
        )

    def create_node(self, parent, kind):
        name = ModernNameDialog.ask(self, kind)
        if name is None:
            return
        try:
            node = self.project.create(parent, name, kind)
        except (OSError, ValueError) as error:
            self.report_error(error)
            return
        self.tree.refresh()
        self.update_status()
        if node.is_file:
            self.file_clicked(node)


class ChoosePjFile(customtkinter.CTkFrame):
    def __init__(self, master, open_project, new_project):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        customtkinter.CTkButton(self, text="PJファイルを選択", command=open_project, width=145).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        customtkinter.CTkButton(self, text="新規", command=new_project, width=55).grid(row=0, column=1)


class UrlInput:
    """Appとグリッド列を共有し、編集欄／操作欄の幅を揃える。"""
    def __init__(self, master, fonts, control_width):
        self.room_url = customtkinter.CTkEntry(master, placeholder_text="CCFoliaのルームURLを入力", font=fonts)
        self.room_connect = customtkinter.CTkButton(master, text="接続", command=self.room_connect_callback, width=control_width)

    def room_connect_callback(self):
        print(f"接続ボタンが押されました。入力されたURL: {self.room_url.get()}")


class TreeNode:
    DIRECTORY = "directory"
    FILE = "file"

    def __init__(self, text, node_type=FILE, data=None, parent=None):
        if node_type not in (self.DIRECTORY, self.FILE):
            raise ValueError("node_type must be 'directory' or 'file'")

        self.text = text
        self.node_type = node_type
        self.data = data
        self.parent = parent
        self.children = []
        self.expanded = True

    @property
    def is_directory(self):
        return self.node_type == self.DIRECTORY

    @property
    def is_file(self):
        return self.node_type == self.FILE

    def add_child(self, node, index=None):
        if self.is_file:
            raise ValueError(
                f"ファイル '{self.text}' の下には子要素を作成できません。"
            )
        if node is self:
            raise ValueError("自分自身を子にすることはできません。")
        if node.is_ancestor_of(self):
            raise ValueError("自分の子孫を親にすることはできません。")

        if node.parent is not None and node in node.parent.children:
            node.parent.children.remove(node)

        node.parent = self
        if index is None:
            self.children.append(node)
        else:
            self.children.insert(index, node)

    def remove_child(self, node):
        if node in self.children:
            self.children.remove(node)
            node.parent = None

    def is_ancestor_of(self, node):
        current = node.parent
        while current is not None:
            if current is self:
                return True
            current = current.parent
        return False

    def to_dict(self):
        return {
            "text": self.text,
            "type": self.node_type,
            "data": self.data,
            "children": [child.to_dict() for child in self.children]
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise ValueError("ツリー項目には文字列のtextが必要です。")
        children = data.get("children", [])
        if not isinstance(children, list):
            raise ValueError("childrenは配列で指定してください。")
        node_type = data.get("type")

        # 旧形式にはtypeがないため、子を持つ項目をディレクトリとして扱う。
        if node_type is None:
            node_type = cls.DIRECTORY if children else cls.FILE

        node = cls(
            text=data["text"],
            node_type=node_type,
            data=data.get("data")
        )

        if node.is_file and children:
            raise ValueError("ファイルに子要素が含まれています。")
        if node.is_directory:
            for child_data in children:
                node.add_child(cls.from_dict(child_data))

        return node


class TreeItem(customtkinter.CTkFrame):
    INDENT_WIDTH = 24
    NORMAL_COLOR = "transparent"
    HOVER_COLOR = ("gray88", "gray24")
    DROP_COLOR = ("#D9EAF7", "#1F4D6D")
    SELECTED_COLOR = ("#B9D9F5", "#24547A")

    def __init__(self, master, tree, node, depth):
        super().__init__(
            master,
            height=42,
            corner_radius=6,
            fg_color=self.NORMAL_COLOR,
            border_width=0
        )
        self.tree = tree
        self.node = node
        self.depth = depth
        self._hovered = False
        self._drop_inside = False
        self._hover_job = None

        self.grid_columnconfigure(3, weight=1)

        self.indent = customtkinter.CTkFrame(
            self,
            width=depth * self.INDENT_WIDTH,
            height=1,
            fg_color="transparent"
        )
        self.indent.grid(row=0, column=0)

        if node.is_directory:
            self.icon = customtkinter.CTkButton(
                self,
                text=self.get_arrow(),
                width=28,
                height=28,
                corner_radius=4,
                fg_color="transparent",
                hover_color=("gray80", "gray35"),
                command=self.toggle
            )
        else:
            self.icon = customtkinter.CTkLabel(
                self,
                text="📄",
                width=28,
                cursor="hand2"
            )
        self.icon.grid(row=0, column=1, padx=(3, 0), pady=5)

        self.drag_handle = customtkinter.CTkLabel(
            self,
            text="☰",
            width=25,
            text_color=("gray45", "gray65"),
            cursor="hand2"
        )
        self.drag_handle.grid(row=0, column=2, padx=(2, 3))

        display_text = f"📁  {node.text}" if node.is_directory else node.text
        self.label = customtkinter.CTkLabel(
            self,
            text=display_text,
            anchor="w",
            cursor="hand2"
        )
        self.label.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(3, 8),
            pady=7
        )

        draggable_widgets = [self, self.label, self.drag_handle, self.indent]
        if node.is_file:
            draggable_widgets.append(self.icon)

        for widget in draggable_widgets:
            widget.bind("<ButtonPress-1>", self.mouse_press)
            widget.bind("<B1-Motion>", self.mouse_motion)
            widget.bind("<ButtonRelease-1>", self.mouse_release)

        for widget in (self, self.label, self.drag_handle, self.icon, self.indent):
            widget.bind("<Enter>", self.mouse_enter, add="+")
            widget.bind("<Leave>", self.mouse_leave, add="+")
            widget.bind("<Button-3>", self.context_menu, add="+")
        self.update_style()

    def context_menu(self, event):
        if self.tree.on_context_menu:
            self.tree.on_context_menu(self.node, event)

    def destroy(self):
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
            self._hover_job = None
        super().destroy()

    def get_arrow(self):
        if not self.node.children:
            return "▷"
        return "▼" if self.node.expanded else "▶"

    def toggle(self):
        if not self.node.is_directory:
            return
        self.node.expanded = not self.node.expanded
        self.tree.refresh()

    def mouse_enter(self, event=None):
        self._hovered = True
        self.update_style()

    def mouse_leave(self, event=None):
        # 子Widget間の移動ではハイライトがちらつかないよう後で確認する。
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
        self._hover_job = self.after(10, self.check_hover)

    def check_hover(self):
        self._hover_job = None
        try:
            pointer_x = self.winfo_pointerx()
            pointer_y = self.winfo_pointery()
            left = self.winfo_rootx()
            top = self.winfo_rooty()
            self._hovered = (
                left <= pointer_x <= left + self.winfo_width()
                and top <= pointer_y <= top + self.winfo_height()
            )
            self.update_style()
        except tk.TclError:
            pass

    def update_style(self):
        if self._drop_inside:
            self.configure(
                fg_color=self.DROP_COLOR,
                border_width=2,
                border_color="#3B8ED0"
            )
        elif self.tree.selected_node is self.node:
            self.configure(fg_color=self.SELECTED_COLOR, border_width=2, border_color="#3B8ED0")
        elif self._hovered:
            self.configure(fg_color=self.HOVER_COLOR, border_width=0)
        else:
            self.configure(fg_color=self.NORMAL_COLOR, border_width=0)

    def set_inside_highlight(self, enabled):
        self._drop_inside = enabled
        self.update_style()

    def mouse_press(self, event):
        self.tree.pointer_press(self.node)

    def mouse_motion(self, event):
        self.tree.pointer_motion(self.node)

    def mouse_release(self, event):
        self.tree.pointer_release(self.node)


class DragPreview:
    def __init__(self, parent, node):
        self.window = customtkinter.CTkToplevel(parent)
        self.window.overrideredirect(True)

        try:
            self.window.attributes("-topmost", True)
            self.window.attributes("-alpha", 0.90)
        except Exception:
            pass

        icon = "📁" if node.is_directory else "📄"
        self.label = customtkinter.CTkLabel(
            self.window,
            text=f"{icon}  {node.text}",
            width=220,
            height=38,
            corner_radius=6,
            fg_color=("gray80", "gray25")
        )
        self.label.pack(fill="both", expand=True)

    def move(self, x, y):
        self.window.geometry(f"+{x + 15}+{y + 15}")

    def destroy(self):
        try:
            self.window.destroy()
        except Exception:
            pass


class DragDropTree(customtkinter.CTkScrollableFrame):
    DRAG_THRESHOLD = 6
    DIRECTORY_TOP_RATIO = 0.25
    DIRECTORY_BOTTOM_RATIO = 0.75

    def __init__(
        self,
        master,
        on_change=None,
        on_file_click=None,
        on_move=None,
        on_context_menu=None,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.root_nodes = []
        self.item_frames = {}
        self.on_change = on_change
        self.on_file_click = on_file_click
        self.on_move = on_move
        self.on_context_menu = on_context_menu
        self.selected_node = None
        self.bind("<Button-3>", self.blank_context_menu, add="+")
        self._parent_canvas.bind("<Button-3>", self.blank_context_menu, add="+")

        self.pressed_node = None
        self.press_x = 0
        self.press_y = 0
        self.drag_active = False
        self.dragged_node = None
        self.hover_node = None
        self.drop_position = None
        self.drag_preview = None

        # CustomTkinterではwidth/heightをplace()ではなくWidget側に渡す。
        self.drop_indicator = customtkinter.CTkFrame(
            self,
            width=100,
            height=3,
            corner_radius=0,
            fg_color="#3B8ED0"
        )
        self.drop_indicator.place_forget()

    def blank_context_menu(self, event):
        if self.on_context_menu:
            self.on_context_menu(None, event)

    def reveal(self, node):
        frame = self.item_frames.get(node)
        if frame is None:
            return
        self.update_idletasks()
        canvas = self._parent_canvas
        y = frame.winfo_y()
        top = canvas.canvasy(0)
        height = canvas.winfo_height()
        if y < top:
            canvas.yview_moveto(y / max(self.winfo_height(), 1))
        elif y + frame.winfo_height() > top + height:
            canvas.yview_moveto((y + frame.winfo_height() - height) / max(self.winfo_height(), 1))

    def add_root(self, node, index=None):
        self.detach_node(node)
        node.parent = None
        if index is None:
            self.root_nodes.append(node)
        else:
            self.root_nodes.insert(index, node)
        self.refresh()

    def remove_node(self, node):
        self.detach_node(node)
        self.refresh()
        self.call_on_change()

    def detach_node(self, node):
        if node.parent is None:
            if node in self.root_nodes:
                self.root_nodes.remove(node)
        elif node in node.parent.children:
            node.parent.children.remove(node)
        node.parent = None

    def refresh(self):
        self.hide_drop_indicator()
        for frame in list(self.item_frames.values()):
            frame.destroy()
        self.item_frames.clear()

        row = 0
        for node in self.root_nodes:
            row = self.render_node(node, depth=0, row=row)

    def render_node(self, node, depth, row):
        item = TreeItem(self, self, node, depth)
        item.grid(
            row=row,
            column=0,
            sticky="ew",
            padx=6,
            pady=2
        )
        self.item_frames[node] = item
        row += 1

        if node.is_directory and node.expanded:
            for child in node.children:
                row = self.render_node(child, depth + 1, row)
        return row

    def pointer_press(self, node):
        self.pressed_node = node
        self.press_x = self.winfo_pointerx()
        self.press_y = self.winfo_pointery()
        self.drag_active = False
        self.dragged_node = None

    def pointer_motion(self, node):
        if self.pressed_node is not node:
            return

        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        distance = math.hypot(x - self.press_x, y - self.press_y)

        if not self.drag_active and distance >= self.DRAG_THRESHOLD:
            self.begin_drag(node)
        if self.drag_active:
            self.update_drag(node)

    def pointer_release(self, node):
        pressed = self.pressed_node
        self.pressed_node = None
        if self.drag_active:
            self.update_drag(node)
            self.finish_drag(node)
        elif pressed is node and node.is_file and self.on_file_click:
            frame = self.item_frames.get(node)
            x, y = self.winfo_pointerxy()
            if frame and frame.winfo_rootx() <= x < frame.winfo_rootx() + frame.winfo_width() and frame.winfo_rooty() <= y < frame.winfo_rooty() + frame.winfo_height():
                self.on_file_click(node)

    def begin_drag(self, node):
        self.drag_active = True
        self.dragged_node = node
        self.hover_node = None
        self.drop_position = None
        self.drag_preview = DragPreview(self.winfo_toplevel(), node)
        self.drag_preview.move(self.winfo_pointerx(), self.winfo_pointery())

    def update_drag(self, source):
        pointer_x = self.winfo_pointerx()
        pointer_y = self.winfo_pointery()

        if self.drag_preview:
            self.drag_preview.move(pointer_x, pointer_y)

        self.clear_drop_highlights()
        self.hide_drop_indicator()
        self.hover_node = None
        self.drop_position = None
        canvas = self._parent_canvas
        if not (canvas.winfo_rootx() <= pointer_x < canvas.winfo_rootx() + canvas.winfo_width()
                and canvas.winfo_rooty() <= pointer_y < canvas.winfo_rooty() + canvas.winfo_height()):
            return
        target = self.get_node_under_mouse(pointer_y)

        if target is None:
            self.hover_node = None
            self.drop_position = "root_end"
            self.show_root_end_indicator()
            return
        if target is source or source.is_ancestor_of(target):
            self.hover_node = None
            self.drop_position = None
            return

        position = self.get_drop_position(target, pointer_y)
        self.hover_node = target
        self.drop_position = position

        if position == "inside":
            self.item_frames[target].set_inside_highlight(True)
        elif position in ("before", "after"):
            self.show_drop_indicator(target, position)

    def get_drop_position(self, target, pointer_y):
        frame = self.item_frames.get(target)
        if frame is None:
            return None

        top = frame.winfo_rooty()
        height = max(frame.winfo_height(), 1)
        ratio = (pointer_y - top) / height

        # ファイルには子を作れないため、前後への挿入だけを許可する。
        if target.is_file:
            return "before" if ratio < 0.5 else "after"
        if ratio < self.DIRECTORY_TOP_RATIO:
            return "before"
        if ratio > self.DIRECTORY_BOTTOM_RATIO:
            return "after"
        return "inside"

    def finish_drag(self, source):
        target = self.hover_node
        position = self.drop_position

        if self.drag_preview:
            self.drag_preview.destroy()
            self.drag_preview = None

        self.clear_drop_highlights()
        self.hide_drop_indicator()
        self.drag_active = False
        self.dragged_node = None
        self.hover_node = None
        self.drop_position = None

        if self.on_move:
            if self.on_move(source, target, position):
                self.refresh()
                self.call_on_change()
            return

        if position == "root_end":
            self.detach_node(source)
            source.parent = None
            self.root_nodes.append(source)
            self.refresh()
            self.call_on_change()
            return
        if target is None or target is source or source.is_ancestor_of(target):
            return

        if position == "inside":
            if not target.is_directory:
                return
            self.detach_node(source)
            target.add_child(source)
            target.expanded = True
        elif position in ("before", "after"):
            target_parent = target.parent
            self.detach_node(source)

            if target_parent is None:
                siblings = self.root_nodes
                target_index = siblings.index(target)
                if position == "after":
                    target_index += 1
                source.parent = None
            else:
                siblings = target_parent.children
                target_index = siblings.index(target)
                if position == "after":
                    target_index += 1
                source.parent = target_parent

            siblings.insert(target_index, source)
        else:
            return

        self.refresh()
        self.call_on_change()

    def get_node_under_mouse(self, pointer_y):
        for node, frame in self.item_frames.items():
            top = frame.winfo_rooty()
            # 行間の余白は次の行の「前」として扱う。
            if pointer_y < top + frame.winfo_height():
                return node
        return None

    def show_drop_indicator(self, node, position):
        frame = self.item_frames.get(node)
        if frame is None:
            return

        self.update_idletasks()
        tree_top = self.winfo_rooty()
        frame_top = frame.winfo_rooty()
        frame_height = frame.winfo_height()
        if position == "before":
            y = frame_top - tree_top - 2
        else:
            y = frame_top - tree_top + frame_height - 1

        x = 10 + frame.depth * TreeItem.INDENT_WIDTH
        width = max(30, self.winfo_width() - x - 16)
        self.drop_indicator.configure(width=width, height=3)
        self.drop_indicator.place(x=x, y=y)
        self.drop_indicator.lift()

    def show_root_end_indicator(self):
        if not self.item_frames:
            return

        last_frame = list(self.item_frames.values())[-1]
        self.update_idletasks()
        y = (
            last_frame.winfo_rooty()
            - self.winfo_rooty()
            + last_frame.winfo_height()
            + 2
        )
        width = max(30, self.winfo_width() - 25)
        self.drop_indicator.configure(width=width, height=3)
        self.drop_indicator.place(x=10, y=y)
        self.drop_indicator.lift()

    def hide_drop_indicator(self):
        try:
            self.drop_indicator.place_forget()
        except Exception:
            pass

    def clear_drop_highlights(self):
        for frame in self.item_frames.values():
            frame.set_inside_highlight(False)

    def get_data(self):
        return [node.to_dict() for node in self.root_nodes]

    def load_data(self, data):
        self.root_nodes.clear()
        for item in data:
            self.root_nodes.append(TreeNode.from_dict(item))
        self.refresh()

    def call_on_change(self):
        if self.on_change:
            self.on_change(self.get_data())


if __name__ == "__main__":
    app = App()
    app.mainloop()
