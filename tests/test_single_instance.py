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
            received.append(bytes(conn.readAll()).decode())
            conn.disconnectFromServer()

        server.newConnection.connect(on_conn)

        probe = QLocalSocket()
        probe.connectToServer(_NAME)
        assert probe.waitForConnected(300)
        probe.write(b"/home/user/Local de.skp")
        probe.flush()
        probe.waitForBytesWritten(300)
        # pump the server side
        for _ in range(50):
            app.processEvents()
            if received:
                break
        probe.disconnectFromServer()
        server.close()
        QLocalServer.removeServer(_NAME)
        assert received == ["/home/user/Local de.skp"]

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
