import json
import threading
import unittest
from unittest.mock import patch
import requests
from web_server import make_server


class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def headers(self, origin=None):
        return {'Origin': origin or self.url, 'X-Bridge-Key': self.server.key}

    def post(self, endpoint, data, headers=None):
        return requests.post(self.url + '/api/' + endpoint, json=data,
                             headers=headers or self.headers(), timeout=5)

    def test_static_and_session(self):
        r = requests.get(self.url, timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Un espacio para', r.text)
        r = requests.get(self.url + '/api/session', timeout=5)
        self.assertEqual(r.json()['key'], self.server.key)
        r = requests.get(self.url + '/api/session', headers={'Origin': 'https://evil.example'}, timeout=5)
        self.assertEqual(r.status_code, 403)
        r = requests.get(self.url + '/api/session', headers={'Host': 'evil.example'}, timeout=5)
        self.assertEqual(r.status_code, 403)

    def test_origin_and_session_key_required(self):
        self.assertEqual(self.post('validate', {}, self.headers('https://evil.example')).status_code, 403)
        self.assertEqual(self.post('validate', {}, {'Origin': self.url}).status_code, 403)
        r = requests.options(self.url + '/api/validate', headers={'Origin': 'https://elektraec.github.io'}, timeout=5)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers['Access-Control-Allow-Origin'], 'https://elektraec.github.io')

    def test_write_requires_validated_one_use_ticket_and_fresh_state(self):
        data = {'url': 'https://canvas.example.edu/courses/1/assignments/2', 'token': 'test-only', 'grades': {'schema_version': 2}}
        row = {'user_id': 1, 'total': 2}
        with patch('web_server.check_live', return_value=([row], [], [], [])), patch('web_server.register_grades', return_value=[{'user_id': 1, 'status': 'CONFIRMADO'}]) as register:
            r = self.post('register', {**data, 'confirmation': 'REGISTRAR', 'ticket': 'invalid'})
            self.assertEqual(r.status_code, 400)
            ticket = self.post('validate', data).json()['ticket']
            r = self.post('register', {**data, 'confirmation': 'REGISTRAR', 'ticket': ticket})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['results'][0]['status'], 'CONFIRMADO')
            self.assertEqual(self.post('register', {**data, 'confirmation': 'REGISTRAR', 'ticket': ticket}).status_code, 400)
            register.assert_called_once()
        with patch('web_server.check_live', side_effect=[([row], [], [], []), ([], [], ['Ya tiene nota.'], [])]), patch('web_server.register_grades') as register:
            ticket = self.post('validate', data).json()['ticket']
            r = self.post('register', {**data, 'confirmation': 'REGISTRAR', 'ticket': ticket})
            self.assertEqual(r.status_code, 400)
            register.assert_not_called()


if __name__ == '__main__':
    unittest.main()
