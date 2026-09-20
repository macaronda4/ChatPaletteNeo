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
        page.get_by_label.return_value.input_value.return_value = 'actor'
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
        # Exactly one tab click and one submit click; no second submit.
        self.assertEqual(page.get_by_role.return_value.click.call_count, 2)


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
