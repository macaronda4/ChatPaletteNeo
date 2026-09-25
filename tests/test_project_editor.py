import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ccfolia_connection import ConnectionEvent

import main
from main import App, ProjectStore, TreeNode


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'Project.cpn'
        self.project = ProjectStore()
        self.folder = self.project.create(None, 'シーン', TreeNode.DIRECTORY)
        self.file = self.project.create(self.folder, '台詞', TreeNode.FILE)
        self.payload = {'speaker': 'まかろん', 'text': 'こんにちは\n次の行', 'tab': 'メイン'}
        self.project.save_file(self.file, self.payload)

    def test_project_and_file_round_trip(self):
        self.project.save(self.path)
        self.assertEqual(json.loads((self.path.parent / 'シーン/台詞.json').read_text()), self.payload)
        loaded = ProjectStore.load(self.path)
        self.assertEqual(loaded.data(), self.project.data())
        self.assertEqual(loaded.read_file(loaded.roots[0].children[0]), self.payload)
        self.assertEqual(loaded.data()[0]['children'][0]['data']['path'], 'シーン/台詞.json')

    def test_rename_delete_and_legacy_tab_round_trip(self):
        self.project.save(self.path)
        self.project.rename(self.file, '変更後')
        self.assertFalse((self.path.parent / 'シーン/台詞.json').exists())
        self.assertEqual(self.project.read_file(self.file), self.payload)
        self.assertEqual(ProjectStore.load(self.path).data(), self.project.data())
        self.project.save_file(self.file, {'speaker': '', 'text': 'legacy'})
        self.assertEqual(self.project.read_file(self.file)['tab'], 'メイン')
        self.project.delete_file(self.file)
        self.assertEqual(self.folder.children, [])
        self.assertFalse((self.path.parent / 'シーン/変更後.json').exists())
        self.assertEqual(ProjectStore.load(self.path).data(), self.project.data())

    def test_file_actions_roll_back_if_project_save_fails(self):
        self.project.save(self.path)
        before = self.path.read_bytes()
        for action in (lambda: self.project.rename(self.file, 'renamed'),
                       lambda: self.project.delete_file(self.file)):
            with patch('main.atomic_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    action()
            self.assertEqual(self.file.text, '台詞.json')
            self.assertEqual(self.folder.children, [self.file])
            self.assertEqual(self.project.read_file(self.file), self.payload)
            self.assertEqual(self.path.read_bytes(), before)

    def test_rename_collision_and_pending_file_actions(self):
        other = self.project.create(self.folder, 'other', TreeNode.FILE)
        with self.assertRaises(ValueError):
            self.project.rename(self.file, 'other')
        self.project.rename(self.file, 'renamed')
        self.assertEqual(self.project.read_file(self.file), self.payload)
        self.project.delete_file(other)
        self.assertNotIn(other, self.project.pending)
        self.project.save(self.path)
        existing = self.path.parent / 'シーン/external.json'
        existing.write_text('keep')
        with self.assertRaises(FileExistsError):
            self.project.rename(self.file, 'external')
        self.assertEqual(existing.read_text(), 'keep')
        self.assertEqual(self.project.read_file(self.file), self.payload)

    def test_saved_file_and_directory_moves(self):
        self.project.save(self.path)
        other = self.project.create(None, '別シーン', TreeNode.DIRECTORY)
        self.assertTrue(self.project.move(self.file, other, 'inside'))
        self.assertFalse((self.path.parent / 'シーン/台詞.json').exists())
        self.assertEqual(self.project.read_file(self.file), self.payload)
        self.assertTrue(self.project.move(other, self.folder, 'inside'))
        self.assertTrue((self.path.parent / 'シーン/別シーン/台詞.json').exists())
        loaded = ProjectStore.load(self.path)
        self.assertEqual(loaded.data(), self.project.data())

    def test_move_collision_keeps_both_files(self):
        self.project.save(self.path)
        other = self.project.create(None, '別', TreeNode.DIRECTORY)
        conflicting = self.project.create(other, '台詞.json', TreeNode.FILE)
        before = self.path.read_bytes()
        with self.assertRaises((ValueError, FileExistsError)):
            self.project.move(self.file, other, 'inside')
        self.assertIs(self.file.parent, self.folder)
        self.assertEqual(self.project.read_file(self.file), self.payload)
        self.assertEqual(self.project.read_file(conflicting), {'speaker': '', 'text': '', 'tab': 'メイン'})
        self.assertEqual(self.path.read_bytes(), before)

    def test_move_rolls_back_when_project_write_fails(self):
        self.project.save(self.path)
        before = self.path.read_bytes()
        with patch('main.atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.project.move(self.file, None, 'root_end')
        self.assertIs(self.file.parent, self.folder)
        self.assertTrue((self.path.parent / 'シーン/台詞.json').exists())
        self.assertFalse((self.path.parent / '台詞.json').exists())
        self.assertEqual(self.path.read_bytes(), before)

    def test_create_rolls_back_if_project_save_fails(self):
        self.project.save(self.path)
        original = main.atomic_json
        def fail_project(path, data):
            if path == self.path:
                raise OSError('disk full')
            return original(path, data)
        with patch('main.atomic_json', side_effect=fail_project):
            with self.assertRaises(OSError):
                self.project.create(self.folder, '追加', TreeNode.FILE)
        self.assertEqual(self.folder.children, [self.file])
        self.assertFalse((self.path.parent / 'シーン/追加.json').exists())

    def test_unsaved_project_moves_preserve_content(self):
        self.project.move(self.file, None, 'root_end')
        self.project.save(self.path)
        self.assertTrue((self.path.parent / '台詞.json').exists())
        self.assertEqual(self.project.read_file(self.file), self.payload)

    def test_pending_save_does_not_overwrite_existing_files(self):
        (self.path.parent / 'シーン').mkdir()
        existing = self.path.parent / 'シーン/台詞.json'
        existing.write_text('existing')
        with self.assertRaises(FileExistsError):
            self.project.save(self.path)
        self.assertEqual(existing.read_text(), 'existing')
        self.assertIsNone(self.project.path)
        self.assertFalse(self.path.exists())

    def test_cycles_and_files_as_parents_rejected(self):
        child = self.project.create(self.folder, '子', TreeNode.DIRECTORY)
        self.assertFalse(self.project.move(self.folder, child, 'inside'))
        self.assertFalse(self.project.move(child, self.file, 'inside'))
        with self.assertRaises(ValueError):
            self.file.add_child(child)

    def test_sibling_order_persisted_without_rewriting_content(self):
        second = self.project.create(self.folder, '次', TreeNode.FILE)
        self.project.save(self.path)
        self.project.move(self.file, second, 'after')
        self.assertEqual(self.folder.children, [second, self.file])
        self.assertEqual(self.project.read_file(self.file), self.payload)
        self.assertEqual(ProjectStore.load(self.path).roots[0].children[0].text, '次.json')

    def test_invalid_names_rejected(self):
        for name in ('', '../outside', 'bad\\name', 'CON', 'NUL.json', 'foo:bar'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.project.create(None, name, TreeNode.FILE)

    def test_legacy_structure_and_invalid_children(self):
        self.path.write_text(json.dumps([{'text': 'old', 'children': [{'text': 'leaf'}]}]))
        loaded = ProjectStore.load(self.path)
        self.assertTrue(loaded.roots[0].is_directory)
        self.assertTrue(loaded.roots[0].children[0].is_file)
        with self.assertRaises(ValueError):
            TreeNode.from_dict({'text': 'bad', 'type': 'file', 'children': [{'text': 'child'}]})


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI tests require a display or Xvfb')
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App()
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def setUp(self):
        self.app.hide_login()
        self.app.set_connection_state('disconnected', '未接続')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = ProjectStore()
        self.first = self.project.create(None, 'first', TreeNode.FILE)
        self.folder = self.project.create(None, 'folder', TreeNode.DIRECTORY)
        self.second = self.project.create(self.folder, 'second', TreeNode.FILE)
        self.project.save(Path(self.temp.name) / 'Project.cpn')
        self.app.set_project(self.project)
        self.app.file_clicked(self.first)
        self.app.update()

    def test_selection_reuses_rows_and_updates_only_selected_style(self):
        app = self.app
        frames = dict(app.tree.item_frames)
        app.file_clicked(self.second)
        app.update()
        self.assertEqual(app.tree.item_frames, frames)
        self.assertEqual(frames[self.second].cget('fg_color'), main.TreeItem.SELECTED_COLOR)
        self.assertNotEqual(frames[self.first].cget('fg_color'), main.TreeItem.SELECTED_COLOR)

    def test_refresh_reuses_rows_after_move_rename_and_collapse(self):
        tree = self.app.tree
        first = tree.item_frames[self.first]
        second = tree.item_frames[self.second]
        self.project.move(self.first, self.folder, 'inside')
        tree.refresh()
        self.app.update()
        self.assertIs(tree.item_frames[self.first], first)
        self.assertIs(tree.item_frames[self.second], second)
        self.assertEqual(first.depth, 1)
        self.assertEqual(list(tree.item_frames), [self.folder, self.second, self.first])
        self.project.rename(self.first, 'changed')
        tree.refresh()
        self.assertEqual(first.label.cget('text'), 'changed.json')
        self.folder.expanded = False
        tree.refresh()
        self.assertEqual(list(tree.item_frames), [self.folder])
        self.app.file_clicked(self.second)
        self.app.update()
        self.assertIn(self.second, tree.item_frames)
        self.assertEqual(tree.item_frames[self.second].cget('fg_color'), main.TreeItem.SELECTED_COLOR)

    def test_drag_motion_coalesces_and_release_uses_latest_position(self):
        tree = self.app.tree
        tree.pressed_node = self.first
        tree.drag_active = True
        with patch.object(tree, 'update_drag') as update, patch.object(tree, 'finish_drag') as finish:
            for _ in range(20):
                tree.pointer_motion(self.first)
            update.assert_not_called()
            self.assertIsNotNone(tree._drag_job)
            tree.pointer_release(self.first)
            update.assert_called_once_with(self.first)
            finish.assert_called_once_with(self.first)
            self.assertIsNone(tree._drag_job)
        tree.drag_active = False

    def test_hit_cache_matches_rows_after_reordering(self):
        tree = self.app.tree
        for moved in (False, True):
            if moved:
                self.project.move(self.first, None, 'root_end')
                tree.refresh()
            self.app.update()
            for node, frame in tree.item_frames.items():
                self.assertIs(tree.get_node_under_mouse(frame.winfo_rooty() + 5), node)

    def test_grid_dimensions_and_selection(self):
        app = self.app
        for geometry in ('1000x650', '1200x750'):
            app.geometry(geometry)
            app.update()
            self.assertEqual(app.editor.grid_info()['row'], 1)
            self.assertEqual(app.editor.grid_info()['column'], 1)
            self.assertEqual(app.editor.winfo_width(), app.url_input.room_url.winfo_width())
            self.assertEqual(app.speaker.winfo_width(), app.url_input.room_connect.winfo_width())
            self.assertEqual(app.save_button.winfo_width(), app.url_input.room_connect.winfo_width())
            self.assertEqual(app.editor.winfo_rooty()+app.editor.winfo_height(), app.winfo_rooty()+app.winfo_height()-10)
        self.assertEqual(app.tree.item_frames[self.first].cget('fg_color'), main.TreeItem.SELECTED_COLOR)

    def test_mouse_click_context_menu_and_drag(self):
        app = self.app
        app.file_clicked(self.second)
        app.update()
        label = app.tree.item_frames[self.first].label._label
        label.event_generate('<Motion>', x=10, y=10, warp=True)
        app.update()
        label.event_generate('<ButtonPress-1>', x=10, y=10)
        label.event_generate('<ButtonRelease-1>', x=10, y=10)
        app.update()
        self.assertIs(app.current_node, self.first)
        with patch.object(app.tree, 'on_context_menu') as callback:
            label = app.tree.item_frames[self.first].label._label
            label.event_generate('<Button-3>', x=10, y=10)
            self.assertIs(callback.call_args.args[0], self.first)
            app.tree._parent_canvas.event_generate('<Button-3>', x=5, y=5)
            self.assertIsNone(callback.call_args.args[0])
        source = app.tree.item_frames[self.first].label._label
        destination = app.tree.item_frames[self.folder]
        source.event_generate('<Motion>', x=10, y=10, warp=True)
        app.update()
        source.event_generate('<ButtonPress-1>', x=10, y=10)
        x = destination.winfo_rootx() + 80 - source.winfo_rootx()
        y = destination.winfo_rooty() + destination.winfo_height() // 2 - source.winfo_rooty()
        source.event_generate('<Motion>', x=x, y=y, warp=True, state=256)
        app.update()
        self.assertTrue(app.tree.drag_active)
        source.event_generate('<ButtonRelease-1>', x=x, y=y)
        app.update()
        self.assertIs(self.first.parent, self.folder)
        self.assertTrue((self.project.path.parent / 'folder/first.json').exists())
        self.assertIs(app.tree.selected_node, self.first)

    def test_switch_cancel_discard_and_save(self):
        app = self.app
        app.editor.insert('1.0', 'edited')
        with patch('main.messagebox.askyesnocancel', return_value=None):
            app.file_clicked(self.second)
        self.assertIs(app.current_node, self.first)
        self.assertEqual(app.payload()['text'], 'edited')
        with patch('main.messagebox.askyesnocancel', return_value=True):
            app.file_clicked(self.second)
        self.assertIs(app.current_node, self.second)
        self.assertEqual(self.project.read_file(self.first)['text'], 'edited')
        app.editor.insert('1.0', 'discard')
        with patch('main.messagebox.askyesnocancel', return_value=False):
            app.file_clicked(self.first)
        self.assertEqual(self.project.read_file(self.second)['text'], '')

    def test_navigation_through_collapsed_directory_and_send(self):
        app = self.app
        self.folder.expanded = False
        app.tree.refresh()
        app.navigate(1)
        self.assertIs(app.current_node, self.second)
        self.assertTrue(self.folder.expanded)
        app.speaker.insert(0, 'actor')
        app.editor.insert('1.0', 'hello')
        app.set_connection_state('connected', '接続済み')
        with patch.object(app.connection, 'submit') as submit:
            app.send()
            app.send()  # Double-clicks must not post twice.
        submit.assert_called_once_with('send', {'speaker': 'actor', 'text': 'hello', 'tab': 'メイン'})
        self.assertEqual(app.connection_state, 'sending')
        self.assertEqual(app.payload()['text'], 'hello')

    def test_dirty_editor_survives_move_and_saves_to_new_path(self):
        app = self.app
        app.editor.insert('1.0', 'unsaved')
        self.assertTrue(app.move_node(self.first, self.folder, 'inside'))
        self.assertTrue(app.is_dirty())
        self.assertTrue(app.save_current())
        self.assertFalse((self.project.path.parent / 'first.json').exists())
        self.assertEqual(self.project.read_file(self.first)['text'], 'unsaved')

    def test_rename_preserves_draft_and_delete_cancel_preserves_file(self):
        app = self.app
        app.editor.insert('1.0', 'draft')
        with patch('main.ModernNameDialog.ask', return_value='renamed'):
            app.rename_file(self.first)
        self.assertEqual(app.editor.get('1.0', 'end-1c'), 'draft')
        self.assertTrue(app.is_dirty())
        self.assertEqual(self.first.text, 'renamed.json')
        with patch('main.messagebox.askyesno', return_value=False):
            app.delete_file(self.first)
        self.assertTrue(self.project.disk_path(self.first).exists())
        with patch('main.messagebox.askyesno', return_value=True):
            app.delete_file(self.first)
        self.assertIsNone(app.current_node)
        self.assertNotIn(self.first, self.project.roots)

    def test_tab_save_switch_and_send_defaults(self):
        app = self.app
        app.send_tab.delete(0, 'end')
        app.send_tab.insert(0, '情報')
        app.editor.insert('1.0', 'hello')
        self.assertTrue(app.is_dirty())
        app.save_current()
        app.file_clicked(self.second)
        app.file_clicked(self.first)
        self.assertEqual(app.send_tab.get(), '情報')
        app.send_tab.delete(0, 'end')
        app.set_connection_state('connected', '')
        with patch.object(app.connection, 'submit') as submit:
            app.send()
        submit.assert_called_once_with('send', {'speaker': 'KP', 'text': 'hello', 'tab': 'メイン'})
        self.assertEqual(app.speaker.get(), '')
        self.assertEqual(app.send_tab.get(), '')

    def test_control_s_saves_current_file(self):
        app = self.app
        app.editor.insert('1.0', 'shortcut')
        app.editor._textbox.focus_set()
        app.update()
        app.editor._textbox.event_generate('<Control-KeyPress-s>')
        app.update()
        self.assertEqual(self.project.read_file(self.first)['text'], 'shortcut')
        self.assertFalse(app.is_dirty())

    def history_key(self, field, sequence):
        widget = self.app.editor._textbox if field == 'text' else self.app.speaker._entry
        widget.focus_force()
        self.app.update()
        widget.event_generate(sequence)
        self.app.update()

    def test_undo_redo_shortcuts_for_both_fields(self):
        for field in ('text', 'speaker'):
            with self.subTest(field=field):
                widget = self.app.editor if field == 'text' else self.app.speaker
                widget.insert('1.0' if field == 'text' else 0, '編集内容')
                self.history_key(field, '<Control-KeyPress-z>')
                self.assertEqual(self.app.payload()[field], '')
                self.history_key(field, '<Control-Shift-KeyPress-Z>')
                self.assertEqual(self.app.payload()[field], '編集内容')
                self.history_key(field, '<Control-KeyPress-z>')
                self.history_key(field, '<Control-KeyPress-y>')
                self.assertEqual(self.app.payload()[field], '編集内容')
                self.history_key(field, '<Control-KeyPress-z>')
                self.assertFalse(self.app.is_dirty())

    def test_new_edit_discards_redo_for_both_fields(self):
        for field in ('text', 'speaker'):
            with self.subTest(field=field):
                widget = self.app.editor if field == 'text' else self.app.speaker
                index = '1.0' if field == 'text' else 0
                widget.insert(index, 'old')
                self.history_key(field, '<Control-KeyPress-z>')
                widget.insert(index, 'new')
                self.history_key(field, '<Control-KeyPress-y>')
                self.assertEqual(self.app.payload()[field], 'new')

    def test_file_switch_clears_both_edit_histories(self):
        self.app.editor.insert('1.0', 'old text')
        self.app.speaker.insert(0, 'old speaker')
        payload = {'speaker': 'next speaker', 'text': 'next text', 'tab': 'メイン'}
        self.project.save_file(self.second, payload)
        with patch('main.messagebox.askyesnocancel', return_value=False):
            self.app.file_clicked(self.second)
        for field in ('text', 'speaker'):
            self.history_key(field, '<Control-KeyPress-z>')
            self.history_key(field, '<Control-KeyPress-y>')
        self.assertEqual(self.app.payload(), payload)
        self.assertFalse(self.app.is_dirty())

    def test_undo_after_save_updates_dirty_state(self):
        self.app.editor.insert('1.0', 'saved text')
        self.app.speaker.insert(0, 'saved speaker')
        self.assertTrue(self.app.save_current())
        for field in ('text', 'speaker'):
            self.history_key(field, '<Control-KeyPress-z>')
            self.assertTrue(self.app.is_dirty())
            self.history_key(field, '<Control-KeyPress-y>')
            self.assertFalse(self.app.is_dirty())

    def test_connect_locks_url_until_disconnect_completes(self):
        app = self.app
        entry = app.url_input.room_url
        entry.delete(0, 'end')
        entry.insert(0, 'https://ccfolia.com/rooms/example')
        with patch.object(app.connection, 'submit') as submit:
            app.toggle_connection()
            app.toggle_connection()
            submit.assert_called_once_with('connect', 'https://ccfolia.com/rooms/example/chat', None)
            self.assertEqual(entry.cget('state'), 'disabled')
            self.assertEqual(app.send_button.cget('state'), 'disabled')
            app.connection.events.put(ConnectionEvent('connected', '接続済み'))
            app.after_cancel(app._connection_poll)
            app.poll_connection()
            self.assertEqual(app.url_input.room_connect.cget('text'), '切断')
            self.assertEqual(app.send_button.cget('state'), 'normal')
            app.toggle_connection()
            self.assertEqual(entry.cget('state'), 'disabled')
            submit.assert_called_with('disconnect')
            app.connection.events.put(ConnectionEvent('disconnected', '切断しました'))
            app.after_cancel(app._connection_poll)
            app.poll_connection()
            self.assertEqual(entry.cget('state'), 'normal')
            self.assertEqual(app.url_input.room_connect.cget('text'), '接続')

    def test_optional_login_is_inline_and_credentials_cleared(self):
        app = self.app
        app.url_input.room_url.delete(0, 'end')
        app.url_input.room_url.insert(0, 'https://ccfolia.com/rooms/example')
        app.set_connection_state('connecting', '接続中')
        app.connection.events.put(ConnectionEvent('disconnected', '投稿権限なし', True))
        app.after_cancel(app._connection_poll)
        app.poll_connection()
        self.assertEqual(app.url_input.room_url.cget('state'), 'normal')
        self.assertIsNone(app.login_panel)
        app.show_login()
        self.assertIs(app.login_panel.winfo_toplevel(), app)
        app.login_email.insert(0, 'user@example.invalid')
        app.login_password.insert(0, 'test-only-password')
        with patch.object(app.connection, 'submit') as submit:
            app.login_and_connect()
        submit.assert_called_once_with('connect', 'https://ccfolia.com/rooms/example/chat',
                                       ('user@example.invalid', 'test-only-password'))
        self.assertIsNone(app.login_panel)

    def test_login_button_opens_before_any_connection_attempt(self):
        app = self.app
        app.update()
        self.assertTrue(app.login_button.winfo_ismapped())
        self.assertEqual(app.login_button.cget('state'), 'normal')
        with patch.object(app.connection, 'submit') as submit:
            app.login_button.invoke()
            self.assertIsNotNone(app.login_panel)
            self.assertIs(app.login_panel.winfo_toplevel(), app)
            app.hide_login()
        submit.assert_not_called()

    def test_login_button_disabled_until_disconnected(self):
        app = self.app
        for state in ('connecting', 'connected', 'sending', 'disconnecting'):
            app.set_connection_state(state, '')
            app.update()
            self.assertTrue(app.login_button.winfo_ismapped())
            self.assertEqual(app.login_button.cget('state'), 'disabled')
            app.login_button.invoke()
            self.assertIsNone(app.login_panel)
        app.connection.events.put(ConnectionEvent('disconnected', '通信エラー', False))
        app.after_cancel(app._connection_poll)
        app.poll_connection()
        self.assertEqual(app.login_button.cget('state'), 'normal')

    def test_optional_login_invalid_url_shows_inline_error(self):
        app = self.app
        app.url_input.room_url.delete(0, 'end')
        app.login_button.invoke()
        app.login_email.insert(0, 'user@example.invalid')
        app.login_password.insert(0, 'test-only')
        with patch.object(app.connection, 'submit') as submit:
            app.login_and_connect()
        submit.assert_not_called()
        self.assertIsNotNone(app.login_panel)
        self.assertIn('https://ccfolia.com', app.login_error.cget('text'))

    def test_chat_url_is_not_appended_twice(self):
        for suffix in ('/chat', '/chat/'):
            with self.subTest(suffix=suffix):
                self.app.set_connection_state('disconnected', '')
                entry = self.app.url_input.room_url
                entry.delete(0, 'end')
                entry.insert(0, 'https://ccfolia.com/rooms/example' + suffix)
                with patch.object(self.app.connection, 'submit') as submit:
                    self.app.toggle_connection()
                submit.assert_called_once_with(
                    'connect', 'https://ccfolia.com/rooms/example/chat', None)

    def test_invalid_url_does_not_connect(self):
        app = self.app
        app.url_input.room_url.delete(0, 'end')
        app.url_input.room_url.insert(0, 'https://example.com')
        with patch.object(app.connection, 'submit') as submit:
            app.toggle_connection()
        submit.assert_not_called()
        self.assertEqual(app.url_input.room_url.cget('state'), 'normal')

    def test_modern_creation_ui(self):
        app = self.app
        event = type('Event', (), {'x_root': 100, 'y_root': 100})()
        app.context_menu(self.folder, event)
        app.update()
        self.assertIsInstance(app.context_popup, main.ModernContextMenu)
        self.assertTrue(app.context_popup.winfo_exists())
        app.context_popup.destroy()

        dialog = main.ModernNameDialog(app, TreeNode.FILE)
        app.update()
        dialog.entry.insert(0, '../invalid')
        dialog.submit()
        self.assertTrue(dialog.winfo_exists())
        self.assertTrue(dialog.error_label.cget('text'))
        dialog.entry.delete(0, 'end')
        dialog.entry.insert(0, 'scene')
        dialog.submit()
        self.assertEqual(dialog.result, 'scene')

    def test_failed_save_cancels_switch(self):
        app = self.app
        app.editor.insert('1.0', 'keep')
        with patch('main.messagebox.askyesnocancel', return_value=True), patch('main.messagebox.showerror'), patch.object(self.project, 'save_file', side_effect=OSError('disk full')):
            app.file_clicked(self.second)
        self.assertIs(app.current_node, self.first)
        self.assertTrue(app.is_dirty())

    def context_send_button(self, node):
        self.app.context_menu(node, type('Event', (), {'x_root': 100, 'y_root': 100})())
        self.app.update()
        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, main.customtkinter.CTkButton):
                    yield child
                yield from buttons(child)
        return next(button for button in buttons(self.app.context_popup)
                    if button.cget('text') == '送信')

    def test_context_send_uses_clicked_file(self):
        payload = {'speaker': 'target', 'text': 'second file', 'tab': '情報'}
        self.project.save_file(self.second, payload)
        self.app.set_connection_state('connected', '')
        button = self.context_send_button(self.second)
        with patch.object(self.app.connection, 'submit') as submit:
            button.invoke()
            self.app.send_file(self.second)
        submit.assert_called_once_with('send', payload)
        self.assertIs(self.app.current_node, self.second)

    def test_context_send_cancel_preserves_unsaved_editor(self):
        self.app.editor.insert('1.0', 'keep draft')
        self.app.set_connection_state('connected', '')
        button = self.context_send_button(self.second)
        with patch('main.messagebox.askyesnocancel', return_value=None), \
                patch.object(self.app.connection, 'submit') as submit:
            button.invoke()
        submit.assert_not_called()
        self.assertIs(self.app.current_node, self.first)
        self.assertEqual(self.app.payload()['text'], 'keep draft')

    def test_context_send_disabled_while_disconnected(self):
        button = self.context_send_button(self.second)
        self.assertEqual(button.cget('state'), 'disabled')
        with patch.object(self.app.connection, 'submit') as submit:
            button.invoke()
            self.app.send_file(self.second)
        submit.assert_not_called()
        self.assertIs(self.app.current_node, self.first)
        self.app.context_popup.destroy()

    def test_control_n_creates_sibling_and_opens_it(self):
        self.app.file_clicked(self.second)
        self.app.editor._textbox.focus_force()
        self.app.update()
        with patch.object(main.ModernNameDialog, 'ask', return_value='new sibling'):
            self.app.editor._textbox.event_generate('<Control-KeyPress-n>')
            self.app.update()
        self.assertEqual(self.app.current_node.text, 'new sibling.json')
        self.assertIs(self.app.current_node.parent, self.folder)
        self.assertTrue((self.project.path.parent / 'folder/new sibling.json').exists())

    def test_control_n_cancel_does_not_create_file(self):
        self.app.editor.insert('1.0', 'keep draft')
        with patch.object(main.ModernNameDialog, 'ask', return_value='cancelled'), \
                patch('main.messagebox.askyesnocancel', return_value=None):
            self.assertEqual(self.app.new_file_shortcut(), 'break')
        self.assertFalse((self.project.path.parent / 'cancelled.json').exists())
        self.assertIs(self.app.current_node, self.first)
        self.assertEqual(self.app.payload()['text'], 'keep draft')

    def test_new_project_save_cancel_keeps_draft(self):
        app = self.app
        project = ProjectStore()
        node = project.create(None, 'new', TreeNode.FILE)
        app.set_project(project)
        app.file_clicked(node)
        app.editor.insert('1.0', 'keep')
        with patch('main.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(app.save_current())
        self.assertTrue(app.is_dirty())
        self.assertEqual(project.pending[node]['text'], '')
        self.assertEqual(app.payload()['text'], 'keep')


if __name__ == '__main__':
    unittest.main()
