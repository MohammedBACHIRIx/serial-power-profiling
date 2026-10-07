import unittest
import socket
import threading
import time
from powerprofiler import config, protocol
from powerprofiler.device import TcpTransport, DeviceWorker

class TestTcpTransport(unittest.TestCase):
    def setUp(self):
        # Create a mock TCP server
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.server.listen(1)
        self.stop_server = False
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

    def _run_server(self):
        try:
            conn, _ = self.server.accept()
            conn.settimeout(0.5)
            while not self.stop_server:
                try:
                    data = conn.recv(128)
                    if not data:
                        break
                    # Echo back sample data upon receiving MA1
                    if b"MA1" in data:
                        conn.sendall(b"U3=230.0E+0 I2=0.500E+0 W=115.0E+0 PF=1.00E+0\r")
                except socket.timeout:
                    continue
            conn.close()
        except Exception:
            pass

    def tearDown(self):
        self.stop_server = True
        self.server.close()

    def test_tcp_open_read_write(self):
        t = TcpTransport("127.0.0.1", port=self.port, timeout=2.0)
        t.open()
        self.assertTrue(t.is_open)
        t.write(b"MA1\r")
        time.sleep(0.1)
        data = t.read()
        self.assertIn(b"U3=230.0E+0", data)
        t.close()
        self.assertFalse(t.is_open)

class TestConfigTransports(unittest.TestCase):
    def test_load_wiznet_config(self):
        cfg = config.load("config/devices.wiznet.example.json")
        self.assertEqual(len(cfg.devices), 2)
        dev1 = cfg.devices[0]
        self.assertEqual(dev1.transport, "tcp")
        self.assertEqual(dev1.tcp_host, "192.168.1.150")
        self.assertEqual(dev1.tcp_port, 5000)
        self.assertEqual(dev1.pair, "PSU-DC-OUT")

if __name__ == "__main__":
    unittest.main()
