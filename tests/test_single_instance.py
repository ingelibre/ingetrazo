# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The single-instance socket: a second launch hands its file to the first
window instead of spawning a rival the desktop then kills as a duplicate."""
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_NAME = "ingetrazo-single-instance-test"


def _app():
    return QCoreApplication.instance() or QCoreApplication([])


class TestSingleInstanceSocket:
    def test_no_server_means_probe_fails_fast(self):
        _app()
        QLocalServer.removeServer(_NAME)
        probe = QLocalSocket()
        probe.connectToServer(_NAME)
        assert probe.waitForConnected(150) is False   # nobody home → launch

    def test_second_launch_delivers_the_path_to_the_first(self):
        app = _app()
        received = []
        server = QLocalServer()
        QLocalServer.removeServer(_NAME)
        assert server.listen(_NAME)

        def on_conn():
            conn = server.nextPendingConnection()
            assert conn.waitForReadyRead(300)
            received.append(bytes(conn.readAll()).decode().strip())
            conn.write(b"ok\n")          # ACK, mirroring main()
            conn.flush()
            conn.waitForBytesWritten(300)
            conn.disconnectFromServer()

        server.newConnection.connect(on_conn)

        probe = QLocalSocket()
        probe.connectToServer(_NAME)
        assert probe.waitForConnected(300)
        probe.write(b"/home/user/Local de.skp\n")
        probe.flush()
        probe.waitForBytesWritten(300)
        # pump the server side, then read the ACK
        acked = False
        for _ in range(50):
            app.processEvents()
            if probe.waitForReadyRead(50) and bytes(probe.readAll()).startswith(b"ok"):
                acked = True
                break
        probe.disconnectFromServer()
        server.close()
        QLocalServer.removeServer(_NAME)
        assert received == ["/home/user/Local de.skp"]
        assert acked                    # the caller got its go-ahead to cede

    def test_unresponsive_peer_gives_no_ack(self):
        # a server that accepts but never answers: the caller must NOT cede
        app = _app()
        QLocalServer.removeServer(_NAME)
        server = QLocalServer()
        assert server.listen(_NAME)
        # deliberately connect NO handler → the connection is never serviced
        probe = QLocalSocket()
        probe.connectToServer(_NAME)
        assert probe.waitForConnected(300)
        probe.write(b"x\n")
        probe.flush()
        got_ack = probe.waitForReadyRead(400)
        probe.disconnectFromServer()
        server.close()
        QLocalServer.removeServer(_NAME)
        assert got_ack is False         # → main() falls through and launches

    def test_stale_socket_is_reclaimed(self):
        _app()
        QLocalServer.removeServer(_NAME)
        s1 = QLocalServer()
        assert s1.listen(_NAME)
        # a crash would leave s1's socket file; a new instance removes + relistens
        s1.close()
        QLocalServer.removeServer(_NAME)
        s2 = QLocalServer()
        assert s2.listen(_NAME)          # reclaimed, no "address in use"
        s2.close()
        QLocalServer.removeServer(_NAME)
