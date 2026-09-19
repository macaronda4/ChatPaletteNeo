# !pip install customtkinter
from pydoc import text
import tkinter as tk
from turtle import st
import customtkinter
import os
import config
import json

FONT_TYPE = config.FONT_TYPE

class App(customtkinter.CTk):

    def __init__(self):
        super().__init__()

        # メンバー変数の設定
        self.fonts = (FONT_TYPE, 15)

        # フォームのセットアップをする
        self.setup_form()

    def setup_form(self):
        # CustomTkinter のフォームデザイン設定
        customtkinter.set_appearance_mode("dark")  # Modes: system (default), light, dark
        customtkinter.set_default_color_theme("blue")  # Themes: blue (default), dark-blue, green

        # フォームサイズ設定
        self.geometry("720x480")
        self.title("Chat Palette NEO")

        # 行方向のマスのレイアウトを設定する。リサイズしたときに一緒に拡大したい行をweight 1に設定。
        self.grid_rowconfigure(1, weight=1)
        # 列方向のマスのレイアウトを設定する
        self.grid_columnconfigure(1, weight=1)

        self.tree = DragDropTree(
            self,
            on_change=self.tree_changed,
            label_text="Explorer"
        )

        self.tree.grid(
            row=1,
            column=0,
            columnspan=2,
#            fill="both",
#            expand=True,
            padx=20,
            pady=(20, 10),
            sticky="ns"
        )

        self.choosePjFile = ChoosePjFile(tree=self.tree, master=self)
        self.choosePjFile.grid(row=0, column=0, padx=20, pady=20, sticky="ew")

        self.url_input = UrlInput(master=self)
        self.url_input.grid(row=0, column=1, padx=20, pady=20, sticky="ew")

        
    def tree_changed(self, data):
        print(
            "===== Tree Changed ====="
        )
        self.print_tree(
            self.tree.root_nodes
        )
    
    def print_tree(
        self,
        nodes,
        depth=0
    ):
        for node in nodes:
            print(
                "    " * depth
                + "└─ "
                + node.text
            )
            self.print_tree(
                node.children,
                depth + 1
            )


class ChoosePjFile(customtkinter.CTkFrame):
    def __init__(self, tree, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.tree = tree
        self.fonts = (FONT_TYPE, 15)
        # フォームのセットアップをする
        self.setup_form()

    def setup_form(self):
        # 行方向のマスのレイアウトを設定する。リサイズしたときに一緒に拡大したい行をweight 1に設定。
        self.grid_rowconfigure(1, weight=1)
        # 列方向のマスのレイアウトを設定する
        self.grid_columnconfigure(0, weight=1)
        
        self.button_select = customtkinter.CTkButton(master=self, 
            fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"),   # ボタンを白抜きにする
            command=self.button_select_callback, text="PJファイルを選択", font=self.fonts)
        self.button_select.grid(row=0, column=0, padx=10, pady=0)

    def button_select_callback(self):
    # エクスプローラーを表示してファイルを選択する
        file_name = self.choose_pjfile()
        
    def choose_pjfile(self):
        current_dir = os.path.abspath(os.path.dirname(__file__))
        file_path = tk.filedialog.askopenfilename(filetypes=[("ChatPaletteNeoProject","*.cpn")],initialdir=current_dir)

        if len(file_path) != 0:
            self.read_pjfile(file_path)
        else:
            # ファイル選択がキャンセルされた場合
            return None

    def read_pjfile(self, file_path):
        # ファイルを読み込む処理をここに実装する
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.tree.load_data(data)
        print(f"選択されたファイル: {file_path}")

    def add_item(self,data):
        for key, value in data.items():
            for data in value:
                if type(data) is str:
                    self.add_item(  key, data)
                else:
                    self.add_dir(key, data)

class UrlInput(customtkinter.CTkFrame):
    def __init__(self, *args, header_name="UrlInput", **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fonts = (FONT_TYPE, 15)
        self.header_name = header_name

        # フォームのセットアップをする
        self.setup_form()

    def setup_form(self):
        # 行方向のマスのレイアウトを設定する。リサイズしたときに一緒に拡大したい行をweight 1に設定。
        self.grid_rowconfigure(0, weight=1)
        # 列方向のマスのレイアウトを設定する
        self.grid_columnconfigure(0, weight=1)

        # ファイルパスを指定するテキストボックス。これだけ拡大したときに、幅が広がるように設定する。
        self.room_url = customtkinter.CTkEntry(master=self, placeholder_text="CCFoliaのルームURLを入力", width=120, font=self.fonts)
        self.room_url.grid(row=0, column=0, padx=10, pady=(0,10), sticky="ew")

        self.room_connect = customtkinter.CTkButton(master=self, command=self.room_connect_callback, text="接続", font=self.fonts)
        self.room_connect.grid(row=0, column=1, padx=10, pady=(0,10))

    def room_connect_callback(self):
        # 入力されたURLを取得する
        room_url = self.room_url.get()
        print(f"接続ボタンが押されました。入力されたURL: {room_url}")


class TreeNode:

    def __init__(self, text, data=None, parent=None):
        self.text = text
        self.data = data
        self.parent = parent
        self.children = []
        self.expanded = True

    def add_child(self, node, index=None):
        # すでにどこかに所属しているなら外す
        if node.parent is not None:
            if node in node.parent.children:
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
            "data": self.data,
            "children": [
                child.to_dict()
                for child in self.children
            ]
        }

    @classmethod
    def from_dict(cls, data):
        node = cls(
            text=data["text"],
            data=data.get("data")
        )
        for child_data in data.get("children", []):
            child = cls.from_dict(child_data)
            node.add_child(child)
        return node

class TreeItem(customtkinter.CTkFrame):
    INDENT_WIDTH = 24
    def __init__(
        self,
        master,
        tree,
        node,
        depth
    ):
        super().__init__(
            master,
            height=42,
            corner_radius=6,
            border_width=0
        )
        self.tree = tree
        self.node = node
        self.depth = depth
        self.grid_columnconfigure(3, weight=1)
        self.indent = customtkinter.CTkFrame(
            self,
            width=depth * self.INDENT_WIDTH,
            height=1,
            fg_color="transparent"
        )
        self.indent.grid(
            row=0,
            column=0
        )
        self.toggle_button = customtkinter.CTkButton(
            self,
            text=self.get_arrow(),
            width=28,
            height=28,
            corner_radius=4,
            fg_color="transparent",
            hover_color=("gray85", "gray30"),
            command=self.toggle
        )
        self.toggle_button.grid(
            row=0,
            column=1,
            padx=(2, 0),
            pady=5
        )
        self.drag_handle = customtkinter.CTkLabel(
            self,
            text="☰",
            width=26,
            text_color=("gray40", "gray65"),
            cursor="hand2"
        )
        self.drag_handle.grid(
            row=0,
            column=2,
            padx=(1, 3)
        )
        self.label = customtkinter.CTkLabel(
            self,
            text=node.text,
            anchor="w"
        )
        self.label.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(2, 8),
            pady=7
        )
        draggable_widgets = [
            self,
            self.label,
            self.drag_handle
        ]
        for widget in draggable_widgets:
            widget.bind(
                "<ButtonPress-1>",
                self.drag_start
            )
            widget.bind(
                "<B1-Motion>",
                self.drag_motion
            )
            widget.bind(
                "<ButtonRelease-1>",
                self.drag_end
            )

    def get_arrow(self):
        if not self.node.children:
            return ""
        if self.node.expanded:
            return "▼"
        return "▶"

    def toggle(self):
        if not self.node.children:
            return
        self.node.expanded = not self.node.expanded
        self.tree.refresh()

    def drag_start(self, event):
        self.tree.start_drag(
            self.node,
            event
        )

    def drag_motion(self, event):
        self.tree.drag_motion(
            self.node,
            event
        )

    def drag_end(self, event):
        self.tree.end_drag(
            self.node,
            event
        )

    def set_inside_highlight(self, enabled):
        if enabled:
            self.configure(
                border_width=2,
                border_color="#3B8ED0"
            )
        else:
            self.configure(
                border_width=0
            )

class DragPreview:
    def __init__(self, parent, text):
        self.window = customtkinter.CTkToplevel(parent)
        self.window.overrideredirect(True)

        try:
            self.window.attributes(
                "-topmost",
                True
            )
            self.window.attributes(
                "-alpha",
                0.90
            )
        except Exception:
            pass
        self.label = customtkinter.CTkLabel(
            self.window,
            text=f"☰  {text}",
            height=36,
            corner_radius=6,
            fg_color=("gray80", "gray25")
        )
        self.label.pack(
            fill="both",
            expand=True,
            padx=1,
            pady=1
        )
        self.window.geometry(
            "220x38"
        )

    def move(self, x, y):
        self.window.geometry(
            f"+{x + 15}+{y + 15}"
        )

    def destroy(self):
        try:
            self.window.destroy()
        except Exception:
            pass


class DragDropTree(customtkinter.CTkScrollableFrame):
    DROP_TOP_RATIO = 0.25
    DROP_BOTTOM_RATIO = 0.75
    def __init__(
        self,
        master,
        on_change=None,
        **kwargs
    ):
        super().__init__(
            master,
            **kwargs
        )
        self.grid_columnconfigure(
            0,
            weight=1
        )
        self.root_nodes = []
        self.item_frames = {}
        self.dragged_node = None
        self.hover_node = None
        self.drop_position = None
        self.drag_preview = None
        self.on_change = on_change
        self.drop_indicator = customtkinter.CTkFrame(
            self,
            height=3,
            corner_radius=0,
            fg_color="#3B8ED0"
        )
        self.drop_indicator.place_forget()
    def add_root(self, node, index=None):
        self.detach_node(node)
        node.parent = None
        if index is None:
            self.root_nodes.append(node)
        else:
            self.root_nodes.insert(
                index,
                node
            )
        self.refresh()

    def remove_node(self, node):
        self.detach_node(node)
        self.refresh()
        self.call_on_change()

    def detach_node(self, node):
        if node.parent is None:
            if node in self.root_nodes:
                self.root_nodes.remove(node)
        else:
            parent = node.parent
            if node in parent.children:
                parent.children.remove(node)
        node.parent = None

    def refresh(self):
        self.hide_drop_indicator()
        self.clear_highlights()
        for frame in list(
            self.item_frames.values()
        ):
            frame.destroy()
        self.item_frames.clear()
        row = 0
        for node in self.root_nodes:
            row = self.render_node(
                node,
                depth=0,
                row=row
            )

    def render_node(
        self,
        node,
        depth,
        row
    ):
        item = TreeItem(
            self,
            self,
            node,
            depth
        )
        item.grid(
            row=row,
            column=0,
            sticky="ew",
            padx=6,
            pady=2
        )
        self.item_frames[node] = item
        row += 1
        if node.expanded:
            for child in node.children:
                row = self.render_node(
                    child,
                    depth + 1,
                    row
                )
        return row

    def get_node_under_mouse(
        self,
        pointer_y=None
    ):
        if pointer_y is None:
            pointer_y = self.winfo_pointery()
        for node, frame in self.item_frames.items():
            top = frame.winfo_rooty()
            height = frame.winfo_height()
            bottom = top + height
            if top <= pointer_y <= bottom:
                return node
        return None
    def get_drop_position(
        self,
        node,
        pointer_y=None
    ):
        frame = self.item_frames.get(node)
        if frame is None:
            return None
        if pointer_y is None:
            pointer_y = self.winfo_pointery()
        top = frame.winfo_rooty()
        height = frame.winfo_height()
        relative_y = pointer_y - top
        ratio = relative_y / max(
            height,
            1
        )
        if ratio < self.DROP_TOP_RATIO:
            return "before"
        elif ratio > self.DROP_BOTTOM_RATIO:
            return "after"
        return "inside"

    def start_drag(
        self,
        node,
        event=None
    ):
        self.dragged_node = node
        self.hover_node = None
        self.drop_position = None
        self.drag_preview = DragPreview(
            self.winfo_toplevel(),
            node.text
        )
        self.drag_preview.move(
            self.winfo_pointerx(),
            self.winfo_pointery()
        )
    def drag_motion(
        self,
        source,
        event=None
    ):
        if self.dragged_node is None:
            return
        pointer_x = self.winfo_pointerx()
        pointer_y = self.winfo_pointery()
        if self.drag_preview:
            self.drag_preview.move(
                pointer_x,
                pointer_y
            )
        target = self.get_node_under_mouse(
            pointer_y
        )
        self.clear_highlights()
        self.hide_drop_indicator()
        if target is None:
            self.hover_node = None
            self.drop_position = "root_end"
            self.show_root_end_indicator()
            return
        if target is source:
            self.hover_node = None
            self.drop_position = None
            return
        if source.is_ancestor_of(target):
            self.hover_node = None
            self.drop_position = None
            return
        position = self.get_drop_position(
            target,
            pointer_y
        )
        self.hover_node = target
        self.drop_position = position
        if position == "inside":
            frame = self.item_frames[target]
            frame.set_inside_highlight(
                True
            )
        elif position in (
            "before",
            "after"
        ):
            self.show_drop_indicator(
                target,
                position
            )

    def end_drag(
        self,
        source,
        event=None
    ):
        target = self.hover_node
        position = self.drop_position
        if self.drag_preview:
            self.drag_preview.destroy()
            self.drag_preview = None
        self.clear_highlights()
        self.hide_drop_indicator()
        self.dragged_node = None
        self.hover_node = None
        self.drop_position = None
        if position == "root_end":
            self.detach_node(source)
            source.parent = None
            self.root_nodes.append(
                source
            )
            self.refresh()
            self.call_on_change()
            return
        if target is None:
            return
        if target is source:
            return
        if source.is_ancestor_of(target):
            return
        if position == "inside":
            self.detach_node(source)
            target.add_child(
                source
            )
            target.expanded = True
        elif position in (
            "before",
            "after"
        ):
            target_parent = target.parent
            self.detach_node(source)
            if target_parent is None:
                siblings = self.root_nodes
                target_index = siblings.index(
                    target
                )
                if position == "after":
                    target_index += 1
                source.parent = None
                siblings.insert(
                    target_index,
                    source
                )
            else:
                siblings = target_parent.children
                target_index = siblings.index(
                    target
                )
                if position == "after":
                    target_index += 1
                source.parent = target_parent
                siblings.insert(
                    target_index,
                    source
                )
        else:
            return
        self.refresh()
        self.call_on_change()

    def show_drop_indicator(
        self,
        node,
        position
    ):
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
            y = (
                frame_top
                - tree_top
                + frame_height
                - 1
            )
        x = (
            10
            + frame.depth
            * TreeItem.INDENT_WIDTH
        )
        width = max(
            30,
            self.winfo_width() - x - 16
        )
        self.drop_indicator.place(
            x=x,
            y=y,
            width=width,
            height=3
        )
        self.drop_indicator.lift()

    def show_root_end_indicator(self):
        if not self.item_frames:
            return
        last_frame = list(
            self.item_frames.values()
        )[-1]
        self.update_idletasks()
        y = (
            last_frame.winfo_rooty()
            - self.winfo_rooty()
            + last_frame.winfo_height()
            + 2
        )
        self.drop_indicator.place(
            x=10,
            y=y,
            width=max(
                30,
                self.winfo_width() - 25
            ),
            height=3
        )
        self.drop_indicator.lift()

    def hide_drop_indicator(self):
        try:
            self.drop_indicator.place_forget()
        except Exception:
            pass

    def clear_highlights(self):
        for frame in self.item_frames.values():
            frame.set_inside_highlight(
                False
            )

    def get_data(self):
        return [
            node.to_dict()
            for node in self.root_nodes
        ]
    
    def load_data(self, data):
        self.root_nodes.clear()
        for item in data:
            node = TreeNode.from_dict(
                item
            )
            self.root_nodes.append(node)
        self.refresh()

    def call_on_change(self):
        if self.on_change:
            self.on_change(
                self.get_data()
            )


class ExplorerItem(customtkinter.CTkFrame):
    def __init__(self, key, path, explorer, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fonts = (FONT_TYPE, 15)
        self.path = path
        self.key = key
        self.explorer = explorer

        # フォームのセットアップをする
        self.setup_form()
        print(f"path: {self.path}")
        self.label = customtkinter.CTkLabel(
            master=self,
            text=os.path.basename(self.path),
            anchor="w"
        )
        self.label.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=10
        )

        # FrameだけでなくLabelをクリックした場合にも反応させる
        for widget in (self, self.label):
            widget.bind("<ButtonPress-1>", self.drag_start)
            widget.bind("<B1-Motion>", self.drag_motion)
            widget.bind("<ButtonRelease-1>", self.drag_end)

    def drag_start(self, event):
        self.sortable_list.dragged_item = self

    def drag_motion(self, event):
        self.sortable_list.move_item(self)

    def drag_end(self, event):
        self.sortable_list.dragged_item = None

    def setup_form(self):
        # 行方向のマスのレイアウトを設定する。リサイズしたときに一緒に拡大したい行をweight 1に設定。
        self.grid_rowconfigure(0, weight=1)
        # 列方向のマスのレイアウトを設定する
        self.grid_columnconfigure(0, weight=1)


class Explorer(customtkinter.CTkScrollableFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fonts = (FONT_TYPE, 15)
        self.items = {}
        self.select_item = None
        self.tree = DragDropTree(
            self,
            on_change=self.tree_changed,
            label_text="Explorer"
        )

        self.tree.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=(20, 10)
        )
        # フォームのセットアップをする
        self.setup_form()

    def setup_form(self):
        # 行方向のマスのレイアウトを設定する。リサイズしたときに一緒に拡大したい行をweight 1に設定。
        self.grid_rowconfigure(0, weight=1)
        # 列方向のマスのレイアウトを設定する
        self.grid_columnconfigure(0, weight=1)

    def tree_changed(self, data):
        print(
            "===== Tree Changed ====="
        )
        self.print_tree(
            self.tree.root_nodes
        )
    
    def print_tree(
        self,
        nodes,
        depth=0
    ):
        for node in nodes:
            print(
                "    " * depth
                + "└─ "
                + node.text
            )
            self.print_tree(
                node.children,
                depth + 1
            )


if __name__ == "__main__":
    app = App()
    app.mainloop()