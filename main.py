# !pip install customtkinter
import tkinter as tk
import customtkinter
import os
import config

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

        # 1つ目のフレームの設定
        # stickyは拡大したときに広がる方向のこと。nsew で4方角で指定する。
        self.choosePjFile = ChoosePjFile(master=self)
        self.choosePjFile.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        self.url_input = UrlInput(master=self)
        self.url_input.grid(row=0, column=1, padx=20, pady=20, sticky="ew")

class ChoosePjFile(customtkinter.CTkFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
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
        file_name = choose_pjfile()


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

class Explorer(customtkinter.CTkScrollableFrame):
    def __init__(self, *args, header_name="Explorer", **kwargs):
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

    def update(self, pjfile=None):
        self.grid_propagate  # 既存のウィジェットをクリアする


def choose_pjfile():
    current_dir = os.path.abspath(os.path.dirname(__file__))
    file_path = tk.filedialog.askopenfilename(filetypes=[("ChatPaletteNeoProject","*.cpn")],initialdir=current_dir)

    if len(file_path) != 0:
        return file_path
    else:
        # ファイル選択がキャンセルされた場合
        return None


if __name__ == "__main__":
    app = App()
    app.mainloop()