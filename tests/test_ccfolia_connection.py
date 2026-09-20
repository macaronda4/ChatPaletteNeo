"""No credentials or real rooms are needed for these connection lifecycle tests."""
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

from ccfolia_connection import (
    AccessUnavailable, ConnectionProblem, ConnectionWorker, HeadlessRoom, SendUncertain, room_url,
)


class URLTests(unittest.TestCase):
    def test_room_urls_only(self):
        self.assertEqual(room_url(' https://ccfolia.com/rooms/A_b-9/ '), 'https://ccfolia.com/rooms/A_b-9')
        for invalid in ('http://ccfolia.com/rooms/a', 'https://ccfolia.com.evil/rooms/a',
                        'https://u:p@ccfolia.com/rooms/a', 'file:///rooms/a',
                        'https://ccfolia.com/home', 'https://ccfolia.com/rooms/a?x=1',
                        'https://ccfolia.com/rooms/a#x', 'https://ccfolia.com/rooms/../home'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                room_url(invalid)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.client = HeadlessRoom()
        self.client.page = MagicMock()
        self.client.url = 'https://ccfolia.com/rooms/test'
        self.client.page.url = self.client.url
        self.api = MagicMock()
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {'playwright': MagicMock(), 'playwright.sync_api': self.api}).start()

    def test_launch_is_always_headless_and_ephemeral(self):
        self.client._launch()
        runtime = self.api.sync_playwright.return_value.start.return_value
        runtime.chromium.launch.assert_called_once_with(headless=True, timeout=20000)
        runtime.chromium.launch_persistent_context.assert_not_called()
        self.client.close()
        runtime.stop.assert_called_once()

    def test_anonymous_connect_does_not_login(self):
        self.client.page.get_by_role.return_value.get_attribute.return_value = 'true'
        with patch.object(self.client, '_launch'), patch.object(self.client, '_login') as login, patch.object(self.client, '_denied', return_value=False):
            self.client.connect(self.client.url)
        login.assert_not_called()

    def test_access_denied_offers_login(self):
        self.client.page.get_by_placeholder.return_value.wait_for.side_effect = TimeoutError()
        with patch.object(self.client, '_launch'), patch.object(self.client, '_denied', return_value=True):
            with self.assertRaises(AccessUnavailable):
                self.client.connect(self.client.url)

    def test_login_errors_do_not_expose_credentials(self):
        with patch.object(self.client, '_launch'), patch.object(self.client, '_login', side_effect=Exception('test-password-secret')):
            with self.assertRaises(AccessUnavailable) as caught:
                self.client.connect(self.client.url, ('user', 'test-password-secret'))
        self.assertNotIn('test-password-secret', str(caught.exception))

    def test_send_multiline_without_enter_and_no_auto_retry(self):
        page = self.client.page
        page.get_by_role.return_value.get_attribute.return_value = 'true'
        page.locator.return_value.input_value.return_value = 'actor'
        page.get_by_placeholder.return_value.input_value.return_value = 'line 1\nline 2'
        with patch.object(self.client, 'alive', return_value=True):
            result = self.client.send({'speaker': 'actor', 'text': 'line 1\nline 2'})
        self.assertIn('到達未確認', result)
        page.get_by_placeholder.return_value.fill.assert_called_once_with('line 1\nline 2')
        page.get_by_placeholder.return_value.press.assert_not_called()
        page.get_by_role.return_value.click.reset_mock()
        self.api.expect.return_value.to_have_value.side_effect = TimeoutError()
        with patch.object(self.client, 'alive', return_value=True), self.assertRaises(SendUncertain):
            self.client.send({'speaker': 'actor', 'text': 'line 1\nline 2'})
        # Exactly one submit click; no second submit.
        self.assertEqual(page.get_by_role.return_value.click.call_count, 1)

    def test_missing_or_ambiguous_tab_reports_counts_without_clicking(self):
        for candidates in (0, 2):
            with self.subTest(candidates=candidates):
                tab = MagicMock()
                tab.count.return_value = candidates
                self.client.page.get_by_role.return_value.and_.return_value.count.return_value = 3
                self.api.expect.return_value.to_have_count.side_effect = TimeoutError()
                with patch.object(self.client, '_main_tab', return_value=tab):
                    with self.assertRaises(ConnectionProblem) as caught:
                        self.client._select_main_tab()
                self.assertIn(f'候補: {candidates}', str(caught.exception))
                self.assertIn('表示中のtab要素: 3', str(caught.exception))
                tab.click.assert_not_called()

    def test_selection_waits_for_attribute_update(self):
        tab = MagicMock()
        with patch.object(self.client, '_main_tab', return_value=tab):
            self.client._select_main_tab()
        tab.click.assert_called_once()
        self.api.expect.return_value.to_have_attribute.assert_called_once_with(
            'aria-selected', 'true', timeout=8000)
        tab.get_attribute.assert_not_called()

    def test_unconfirmed_selection_stops_before_filling_or_sending(self):
        self.api.expect.return_value.to_have_attribute.side_effect = TimeoutError()
        self.client.page.get_by_role.return_value.locator.return_value.count.return_value = 1
        with patch.object(self.client, 'alive', return_value=True):
            with self.assertRaises(ConnectionProblem) as caught:
                self.client.send({'speaker': 'actor', 'text': 'hello'})
        self.assertIn('選択完了', str(caught.exception))
        self.client.page.get_by_placeholder.return_value.fill.assert_not_called()
        self.client.page.get_by_role.return_value.locator.assert_called_with('button#main[role="tab"]')
        self.assertNotIn(
            unittest.mock.call('button', name='送信', exact=True),
            self.client.page.get_by_role.call_args_list)

    def test_announcement_is_closed_before_selecting_main(self):
        dialog = self.client.page.get_by_role.return_value.filter.return_value
        dialog.count.return_value = 1
        dialog.is_visible.return_value = True
        tab = MagicMock()
        actions = []
        dialog.get_by_role.return_value.click.side_effect = lambda: actions.append('close')
        tab.click.side_effect = lambda: actions.append('select')
        with patch.object(self.client, '_main_tab', return_value=tab):
            self.client._select_main_tab()
        self.assertEqual(actions, ['close', 'select'])
        dialog.get_by_role.assert_called_once_with('button', name='閉じる', exact=True)
        dialog.wait_for.assert_called_once_with(state='hidden', timeout=8000)

    def test_late_announcement_retries_only_tab_selection(self):
        tab = MagicMock()
        tab.click.side_effect = [TimeoutError(), None]
        with patch.object(self.client, '_main_tab', return_value=tab), \
                patch.object(self.client, '_dismiss_announcement', side_effect=[False, True]):
            self.client._select_main_tab()
        self.assertEqual(tab.click.call_count, 2)

    def test_unknown_overlay_does_not_trigger_retry(self):
        tab = MagicMock()
        tab.count.return_value = 1
        tab.click.side_effect = TimeoutError()
        with patch.object(self.client, '_main_tab', return_value=tab), \
                patch.object(self.client, '_dismiss_announcement', return_value=False):
            with self.assertRaises(ConnectionProblem):
                self.client._select_main_tab()
        tab.click.assert_called_once()

    def test_missing_announcement_does_not_close_other_dialogs(self):
        dialog = self.client.page.get_by_role.return_value.filter.return_value
        dialog.count.return_value = 0
        self.assertFalse(self.client._dismiss_announcement())
        dialog.get_by_role.assert_not_called()


class WorkerTests(unittest.TestCase):
    def make_worker(self, backend):
        worker = ConnectionWorker(lambda: backend)
        def cleanup():
            worker.close()
            if worker.thread:
                worker.thread.join(timeout=3)
                self.assertFalse(worker.thread.is_alive())
        self.addCleanup(cleanup)
        return worker

    def test_connect_send_disconnect_use_same_background_thread(self):
        backend = MagicMock()
        backend.alive.return_value = True
        owner_threads = []
        backend.connect.side_effect = lambda *args: owner_threads.append(threading.get_ident())
        backend.send.side_effect = lambda *args: owner_threads.append(threading.get_ident()) or 'submitted'
        backend.close.side_effect = lambda: owner_threads.append(threading.get_ident())
        worker = self.make_worker(backend)
        worker.submit('connect', 'https://ccfolia.com/rooms/test', None)
        self.assertEqual(worker.events.get(timeout=3).state, 'connected')
        worker.submit('send', {'speaker': 'actor', 'text': 'hello'})
        self.assertEqual(worker.events.get(timeout=3).message, 'submitted')
        worker.submit('disconnect')
        self.assertEqual(worker.events.get(timeout=3).state, 'disconnected')
        self.assertEqual(len(set(owner_threads)), 1)
        self.assertNotEqual(owner_threads[0], threading.get_ident())

    def test_failed_connect_closes_browser_and_allows_retry(self):
        backend = MagicMock()
        backend.connect.side_effect = AccessUnavailable('denied')
        worker = self.make_worker(backend)
        worker.submit('connect', 'https://ccfolia.com/rooms/test', None)
        result = worker.events.get(timeout=3)
        self.assertEqual(result.state, 'disconnected')
        self.assertTrue(result.login_available)
        backend.close.assert_called_once()
        backend.connect.side_effect = None
        worker.submit('connect', 'https://ccfolia.com/rooms/test', None)
        self.assertEqual(worker.events.get(timeout=3).state, 'connected')

    def test_connection_loss(self):
        backend = MagicMock()
        backend.alive.return_value = False
        worker = self.make_worker(backend)
        worker.submit('connect', 'https://ccfolia.com/rooms/test', None)
        self.assertEqual(worker.events.get(timeout=3).state, 'connected')
        self.assertEqual(worker.events.get(timeout=3).state, 'disconnected')
        backend.close.assert_called_once()

    def test_close_during_connect_releases_browser(self):
        backend = MagicMock()
        entered, release = threading.Event(), threading.Event()
        def connect(*_args):
            entered.set()
            release.wait(timeout=3)
        backend.connect.side_effect = connect
        worker = self.make_worker(backend)
        worker.submit('connect', 'https://ccfolia.com/rooms/test', None)
        self.assertTrue(entered.wait(timeout=2))
        worker.close()
        release.set()
        worker.thread.join(timeout=3)
        self.assertFalse(worker.thread.is_alive())
        backend.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
