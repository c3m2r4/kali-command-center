import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exporter.socket_inventory_exporter import (
    InventoryCollector, classify_exposure, decode_processes, parse_ss_output,
    check_application, render_metrics, run_ss, split_endpoint,
)


SAMPLE = '''tcp LISTEN 0 4096 127.0.0.1:22 0.0.0.0:* users:(("sshd",pid=501,fd=3))
tcp LISTEN 0 4096 0.0.0.0%pan1:8081 0.0.0.0:* users:(("python3",pid=502,fd=4))
tcp LISTEN 0 4096 [::]:443 [::]:* users:(("web server",pid=503,fd=5))
udp UNCONN 0 0 127.0.0.1:53 0.0.0.0:* users:(("unbound",pid=504,fd=6))
udp UNCONN 0 0 0.0.0.0:67 0.0.0.0:*\n'''


class ExporterParserTests(unittest.TestCase):
    def test_split_endpoint_ipv4_ipv6_and_wildcard(self):
        self.assertEqual(split_endpoint('127.0.0.1:80'), ('127.0.0.1', '80'))
        self.assertEqual(split_endpoint('[fe80::1%eth0]:443'), ('fe80::1%eth0', '443'))
        self.assertEqual(split_endpoint('*:*'), ('*', '*'))

    def test_exposure_classification(self):
        self.assertEqual(classify_exposure('0.0.0.0'), ('wildcard', 'all'))
        self.assertEqual(classify_exposure('::'), ('wildcard', 'all'))
        self.assertEqual(classify_exposure('127.0.0.1'), ('loopback', 'lo'))
        self.assertEqual(classify_exposure('10.0.0.3'), ('private', 'unknown'))

    def test_parse_tcp_udp_process_and_unknown_pid(self):
        rows = parse_ss_output(SAMPLE, metadata_available=True)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]['process_name'], 'sshd')
        self.assertEqual(rows[0]['pid'], '501')
        self.assertEqual(rows[1]['interface'], 'pan1')
        self.assertEqual(rows[1]['exposure'], 'wildcard')
        self.assertEqual(rows[2]['local_address'], '::')
        self.assertEqual(rows[2]['process_name'], 'web server')
        self.assertEqual(rows[3]['protocol'], 'udp')
        self.assertEqual(rows[4]['process_name'], 'unavailable')
        self.assertEqual(rows[4]['pid'], 'unavailable')

    def test_process_unavailable_is_not_invented(self):
        row = parse_ss_output(SAMPLE.splitlines()[0], metadata_available=False)[0]
        self.assertEqual(row['process_name'], 'unavailable')
        self.assertEqual(row['pid'], 'unavailable')

    def test_multiple_process_owners(self):
        rows = parse_ss_output('tcp LISTEN 0 1 *:80 *:* users:(("a",pid=1,fd=2),("b",pid=2,fd=3))', True)
        self.assertEqual([(r['process_name'], r['pid']) for r in rows], [('a', '1'), ('b', '2')])

    def test_privileged_ss_then_unprivileged_fallback(self):
        calls = []
        def fake(args, **kwargs):
            calls.append(args)
            if args[0].endswith('/sudo'):
                return type('Result', (), {'returncode': 1, 'stdout': '', 'stderr': 'a password is required'})()
            return type('Result', (), {'returncode': 0, 'stdout': SAMPLE, 'stderr': ''})()
        output, metadata, status = run_ss(runner=fake)
        self.assertFalse(metadata)
        self.assertEqual(status, 'process_metadata_unavailable')
        self.assertTrue(calls[0][0].endswith('/sudo'))
        self.assertEqual(calls[1][0], '/usr/bin/ss')
        self.assertIn('tcp', output)

    def test_change_detection_baseline_new_and_disappeared(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps({'expected_listeners':[{'protocol':'tcp','port':22,'service':'ssh'}]}))
            state = Path(tmp) / 'state.json'
            snapshots = [
                'tcp LISTEN 0 1 127.0.0.1:22 *:* users:(("sshd",pid=1,fd=1))',
                'tcp LISTEN 0 1 127.0.0.1:22 *:* users:(("sshd",pid=1,fd=1))\ntcp LISTEN 0 1 0.0.0.0:9000 *:* users:(("python",pid=2,fd=2))',
                'tcp LISTEN 0 1 127.0.0.1:22 *:* users:(("sshd",pid=1,fd=1))',
            ]
            now = [1000]
            def ss(_sudo):
                return snapshots.pop(0), True, 'ok'
            collector = InventoryCollector(state, config, ss_runner=ss, now=lambda: now[0])
            with patch('exporter.socket_inventory_exporter.address_interfaces', return_value={}), patch('exporter.socket_inventory_exporter.docker_port_map', return_value={}):
                first = collector.collect()
                now[0] += 30
                second = collector.collect()
                now[0] += 30
                third = collector.collect()
            self.assertEqual(first['events'], [])
            self.assertTrue(any(e['change']=='new' and e['row']['local_port']=='9000' for e in second['events']))
            self.assertTrue(any(e['change']=='disappeared' and e['row']['local_port']=='9000' for e in third['events']))
            self.assertEqual(third['expected'][0]['present'], True)

    def test_allowlisted_health_check_uses_head_without_redirect_following(self):
        class Response:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *_args): return False
        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response()
        opener = Opener()
        with patch('exporter.socket_inventory_exporter.urllib.request.build_opener', return_value=opener):
            result = check_application('https://localhost:9443/', 'Portainer', '9443')
        self.assertEqual(result['up'], 1)
        self.assertEqual(result['status_code'], 204)
        self.assertEqual(opener.request.get_method(), 'HEAD')

    def test_legacy_port_only_baseline_migrates_without_false_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps({'expected_listeners':[]}))
            state = Path(tmp) / 'state.json'
            previous = {'protocol':'tcp','socket_state':'LISTEN','local_address':'127.0.0.1','local_port':'22',
                        'peer_address':'0.0.0.0','peer_port':'*','process_name':'sshd','pid':'1',
                        'interface':'lo','exposure':'loopback','application_name':'OpenSSH','browser_url':'',
                        'container_name':'unavailable','availability':'available'}
            state.write_text(json.dumps({'baseline_initialized':True,'listeners':{'tcp:22':previous},'events':[]}))
            collector = InventoryCollector(state, config, ss_runner=lambda _sudo: ('tcp LISTEN 0 1 127.0.0.1:22 *:*', True, 'ok'))
            with patch('exporter.socket_inventory_exporter.address_interfaces', return_value={}), patch('exporter.socket_inventory_exporter.docker_port_map', return_value={}):
                data = collector.collect()
            self.assertEqual(data['events'], [])

    def test_bind_address_change_is_new_exposure_even_on_existing_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps({'expected_listeners':[{'protocol':'tcp','port':8080,'service':'web'}]}))
            state = Path(tmp) / 'state.json'
            snapshots = [
                'tcp LISTEN 0 1 127.0.0.1:8080 *:* users:(("web",pid=1,fd=1))',
                'tcp LISTEN 0 1 0.0.0.0:8080 *:* users:(("web",pid=1,fd=1))',
            ]
            collector = InventoryCollector(state, config, ss_runner=lambda _sudo: (snapshots.pop(0), True, 'ok'))
            with patch('exporter.socket_inventory_exporter.address_interfaces', return_value={}), patch('exporter.socket_inventory_exporter.docker_port_map', return_value={}):
                collector.collect()
                result = collector.collect()
            self.assertTrue(any(e['change']=='new' and e['row']['exposure']=='wildcard' for e in result['events']))
            self.assertTrue(any(e['change']=='disappeared' and e['row']['exposure']=='loopback' for e in result['events']))
            self.assertTrue(result['expected'][0]['present'])

    def test_prometheus_metrics_are_escaped_and_show_missing_metadata(self):
        row = parse_ss_output('tcp LISTEN 0 1 0.0.0.0:80 *:*', False)[0]
        data = {'rows':[row], 'sockets':[row], 'metadata':False, 'status':'process_metadata_unavailable',
                'timestamp':123, 'events':[], 'initialized':True, 'expected':[]}
        text = render_metrics(data).decode()
        self.assertIn('process_name="unavailable"', text)
        self.assertIn('pid="unavailable"', text)
        self.assertIn('kali_socket_inventory_process_metadata_available 0', text)
        self.assertIn('kali_socket_inventory_last_seen_timestamp_seconds', text)


if __name__ == '__main__':
    unittest.main()
