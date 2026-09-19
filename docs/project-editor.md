# Project編集画面

- 左側は幅240のExplorer、中央は本文、右側は話者と操作ボタンです。
- 本文はURL入力欄と同じ幅、話者と各ボタンは「接続」と同じ幅になります。
- Explorerのファイルをクリックすると開き、青い背景と枠で開いているファイルを示します。
- 「前へ」「次へ」はExplorerの上から順のファイルへ移動します。折りたたまれたフォルダ内も対象です。
- 「保存」は話者と本文を保存します。「送信」は現在の話者と本文をJSONとして標準出力へprintします。
- 編集中に他のファイル・Projectへ切り替える場合やアプリを終了する場合は、保存／破棄／キャンセルを確認します。

## 作成と保存

Explorerを右クリックしてファイル／ディレクトリを作成できます。ディレクトリ上ではその中、ファイル上では同じ階層、空白部分ではルートに作成します。ファイル名には必要に応じて `.json` を付けます。

新規Projectは、左上の「新規」から開始します。Explorer上部の「Project保存」を押すと保存場所とProject名を選べます。既存Projectでは同じ `.cpn` を上書きします。新規Projectで最初にファイルの「保存」を押した場合も、Projectの保存先を選びます。

本文のJSON形式:

```json
{"speaker": "話者名", "text": "本文\n次の行"}
```

`.cpn` の内容はツリーの配列です。ファイルの保存先は `.cpn` のあるフォルダを基準にExplorerの階層から決定し、`data.path` に相対パスを記録します。

```json
[
  {
    "text": "シーン1",
    "type": "directory",
    "data": {"path": "シーン1"},
    "children": [
      {
        "text": "導入.json",
        "type": "file",
        "data": {"path": "シーン1/導入.json"},
        "children": []
      }
    ]
  }
]
```

この場合、本文は `.cpn` と同じフォルダの `シーン1/導入.json` に保存されます。

保存済みProjectでは新規作成やD&Dのたびに `.cpn` も更新します。D&Dでは実ファイル／ディレクトリも移動します。移動先に同名の項目がある場合は中止し、Project保存に失敗した場合は移動前へ戻します。編集中の本文はD&Dで自動保存せず、編集欄に保持します。

`type` のない旧形式も読み込めます（子あり＝directory、子なし＝file）。空ディレクトリは `"type": "directory"` を明示してください。旧形式に `data.path` があっても、保存先はExplorerの階層を基準とします。既存の本文JSONは上記の相対パスに置いてください。本文ファイルがない場合はエラーを表示し、空の内容で置き換えません。

## 実行・検証

Python 3.9以降とTkが必要です。

```sh
python -m pip install -r requirements.txt
python main.py
python -m unittest discover -s tests -v
```

GUIテストにはディスプレイが必要です。Linuxでは `xvfb-run -a python -m unittest discover -s tests -v` でも実行できます。ディスプレイのない環境ではGUIテストのみスキップされます。
