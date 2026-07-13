from pet_window import PetWindow
from shared_memory_ipc import encode_ipc_envelope


class _PeerStateHarness:
    def __init__(self):
        self._current_char = "Kasumi"
        self._peer_window_positions = {
            "Ran": (100, 200),
            "Aya": (300, 400),
        }
        self._peers_with_radial_menu = {"Ran"}
        self.gaze_updates = 0
        self.topmost_ticks = 0

    def _update_mutual_gaze(self):
        self.gaze_updates += 1

    def _tick_windows_topmost_guard(self):
        self.topmost_ticks += 1


class _UnregisterHarness:
    def __init__(self, *, registered=True, send_result=True):
        self._ipc_registered = registered
        self._current_char = "Kasumi"
        self.send_result = send_result
        self.sent = []

    def _send_ipc(self, line):
        self.sent.append(line)
        return self.send_result


class _ReadQueue:
    def __init__(self, lines):
        self.lines = list(lines)

    def is_attached(self):
        return True

    def read_available(self, max_messages=None):
        del max_messages
        lines, self.lines = self.lines, []
        return lines


class _ReadHarness:
    def __init__(self):
        self._ipc_peer_id = "pet-self"
        self._ipc_broadcast_queue = _ReadQueue([
            encode_ipc_envelope("main", 'PEER_POS\t{"character":"Ran","x":1,"y":2}'),
        ])
        self._ipc_control_queue = _ReadQueue([
            encode_ipc_envelope("main", 'PEER_OFFLINE\t{"character":"Ran"}', reliable=True),
        ])
        self.lines = []

    def _connect_ipc_bus(self):
        pass

    def _handle_ipc_line(self, line):
        self.lines.append(line)


def test_peer_offline_clears_gaze_and_radial_menu_state():
    harness = _PeerStateHarness()

    PetWindow._handle_peer_offline(harness, {"character": "Ran"})

    assert harness._peer_window_positions == {"Aya": (300, 400)}
    assert harness._peers_with_radial_menu == set()
    assert harness.gaze_updates == 1
    assert harness.topmost_ticks == 1


def test_peer_offline_ignores_invalid_and_current_character_payloads():
    harness = _PeerStateHarness()

    PetWindow._handle_peer_offline(harness, [])
    PetWindow._handle_peer_offline(harness, {"character": "Kasumi"})
    PetWindow._handle_peer_offline(harness, {"character": ""})

    assert set(harness._peer_window_positions) == {"Ran", "Aya"}
    assert harness._peers_with_radial_menu == {"Ran"}
    assert harness.gaze_updates == 0
    assert harness.topmost_ticks == 0


def test_registered_pet_sends_reliable_unregistration_once():
    harness = _UnregisterHarness()

    assert PetWindow._send_ipc_unregistration(harness) is True
    assert harness.sent == ["UNREGISTER\tPET\tKasumi"]
    assert harness._ipc_registered is False
    assert PetWindow._send_ipc_unregistration(harness) is False
    assert harness.sent == ["UNREGISTER\tPET\tKasumi"]


def test_failed_unregistration_keeps_registration_state_for_retry():
    harness = _UnregisterHarness(send_result=False)

    assert PetWindow._send_ipc_unregistration(harness) is False
    assert harness._ipc_registered is True


def test_pending_position_is_processed_before_reliable_offline_event():
    harness = _ReadHarness()

    PetWindow._read_ipc_messages(harness)

    assert harness.lines == [
        'PEER_POS\t{"character":"Ran","x":1,"y":2}',
        'PEER_OFFLINE\t{"character":"Ran"}',
    ]
