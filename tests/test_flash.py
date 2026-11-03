import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.main import create_app

RID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def client():
    main.relay.slots.clear()
    main.relay.per_ip.clear()
    main._manifests.clear()
    with TestClient(create_app()) as c:
        yield c


def test_flasher_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "esptool-js@" in r.text
    assert "Embedded PSRAM 8MB" in r.text and '"16MB"' in r.text  # it checks the board before writing
    assert "/relay/" not in r.text  # the relay isn't advertised


def test_release_from_the_releases_branch(client, monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        return {"version": "0.13.0", "hardware": "sp-esp32-s3-1.28-box",
                "install": {"file": "v0.13.0/harkenn-speaker-0.13.0-install.bin", "size": 123, "sha256": "ab" * 32}}

    monkeypatch.setattr(main, "_get_json", fake)
    assert client.get("/release/stable.json").json() == {
        "version": "0.13.0", "hardware": "sp-esp32-s3-1.28-box",
        "url": main.RELEASES + "/v0.13.0/harkenn-speaker-0.13.0-install.bin", "size": 123, "sha256": "ab" * 32}
    client.get("/release/stable.json")
    assert calls == [main.RELEASES + "/latest.json"]  # cached
    assert client.get("/release/nightly.json").status_code == 404


def test_release_without_an_install_image(client, monkeypatch):
    monkeypatch.setattr(main, "_get_json", lambda url: {"version": "0.12.0"})
    assert client.get("/release/beta.json").status_code == 404


def test_relay_pairs_and_passes_binary_frames(client):
    with client.websocket_connect(f"/relay/speaker/{RID}") as speaker:
        assert main.relay.stats() == {"waiting": 1, "paired": 0}
        speaker.send_bytes(b"lost: nobody is listening yet")
        with client.websocket_connect(f"/relay/harkenn/{RID}") as harkenn:
            assert speaker.receive_json() == {"type": "paired"}
            assert harkenn.receive_json() == {"type": "paired"}
            speaker.send_bytes(b"\x01hello")
            assert harkenn.receive_bytes() == b"\x01hello"
            harkenn.send_text("text isn't relayed")
            harkenn.send_bytes(b"\x02back")
            assert speaker.receive_bytes() == b"\x02back"
        # Harkenn left: the speaker's side ends too, so both start over
        with pytest.raises(WebSocketDisconnect) as e:
            speaker.receive_bytes()
        assert e.value.code == 4001


def test_same_side_again_replaces_the_old_one(client):
    with client.websocket_connect(f"/relay/speaker/{RID}") as first:
        with client.websocket_connect(f"/relay/speaker/{RID}"):
            with pytest.raises(WebSocketDisconnect) as e:
                first.receive_bytes()
            assert e.value.code == 4000


def test_bad_relay_ids_are_refused(client):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/relay/speaker/not-an-id") as ws:
            ws.receive_bytes()
    assert e.value.code == 4404


def test_too_many_connections_from_one_address(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_PER_IP", 1)
    with client.websocket_connect(f"/relay/speaker/{RID}"):
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(f"/relay/harkenn/{'f' * 32}") as ws:
                ws.receive_bytes()
        assert e.value.code == 4429
