from harmonia.accounts import YouTubeIdentity, parse_identities, same_login
from harmonia.models import LibraryItem


def account_item(name, datasync, handle="", selected=False):
    return {
        "accountItem": {
            "accountName": {"simpleText": name},
            "channelHandle": {"simpleText": handle},
            "accountPhoto": {"thumbnails": [{"url": "small"}, {"url": f"https://img/{name}"}]},
            "isSelected": selected,
            "serviceEndpoint": {
                "selectActiveIdentityEndpoint": {
                    "supportedTokens": [
                        {"pageIdToken": {"pageId": datasync.split("||")[0]}},
                        {"datasyncIdToken": {"datasyncIdToken": datasync}},
                    ]
                }
            },
        }
    }


ACCOUNTS_LIST = {
    "actions": [
        {
            "getMultiPageMenuAction": {
                "menu": {
                    "multiPageMenuRenderer": {
                        "sections": [
                            {
                                "accountSectionListRenderer": {
                                    "contents": [
                                        {
                                            "accountItemSectionRenderer": {
                                                "contents": [
                                                    account_item("Eu", "111||", "@eu", True),
                                                    account_item("Selo", "222||111", "@selo"),
                                                    account_item("Outra conta", "333||999"),
                                                ]
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }
    ]
}


def test_the_channel_switcher_lists_each_channel_once():
    identities = parse_identities(ACCOUNTS_LIST)
    assert [(i.name, i.id, i.handle, i.selected) for i in identities] == [
        ("Eu", "111", "@eu", True),
        ("Selo", "222", "@selo", False),
        ("Outra conta", "333", "", False),
    ]
    assert identities[0].thumbnail == "https://img/Eu"
    # Only the channels of the session's Google login can be acted as.
    assert [i.name for i in same_login(identities, "111||")] == ["Eu", "Selo"]
    assert [i.name for i in same_login(identities, "222||111")] == ["Eu", "Selo"]


def test_the_client_lists_channels_as_the_login_and_acts_as_the_chosen_one():
    from harmonia.innertube import InnerTubeClient

    requests = []

    def fake(endpoint, body, authenticated=True, as_identity=True):
        requests.append((endpoint, body, as_identity))
        return ACCOUNTS_LIST

    client = InnerTubeClient("SAPISID=x")
    client._bootstrapped, client.session_data_sync_id = True, "111||"
    client._api_post = fake
    assert [i.name for i in client.identities()] == ["Eu", "Selo"]
    endpoint, body, as_identity = requests[0]
    assert endpoint == "account/accounts_list" and as_identity is False
    assert body["requestType"] == "ACCOUNTS_LIST_REQUEST_TYPE_CHANNEL_SWITCHER"

    # The chosen channel replaces the session's in onBehalfOfUser.
    import io
    import json

    sent = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    acting = InnerTubeClient("SAPISID=x", identity="222")
    acting._open = lambda request, timeout=30: (
        sent.append(json.loads(request.data)) or Response(b"{}")
    )
    acting._bootstrapped, acting.data_sync_id = True, "222"
    acting._api_post("browse", {})
    acting._api_post("account/accounts_list", {}, as_identity=False)
    assert sent[0]["context"]["user"] == {"onBehalfOfUser": "222"}
    assert sent[1]["context"]["user"] == {}


def test_switching_channels_drops_the_previous_library(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from harmonia.accounts import IDENTITY_SETTING
    from harmonia.services import YouTubeMusicService
    from harmonia.storage import Storage

    storage = Storage()
    storage.save_library({"songs": [LibraryItem("v", "Do canal pessoal", kind="songs")]})
    storage.record_library_change("songs", LibraryItem("w", "Curtida"), True)
    service = YouTubeMusicService(storage)
    service.set_identity(YouTubeIdentity("Selo", "222||111"))
    assert storage.get_setting(IDENTITY_SETTING) == "222"
    assert storage.load_library() == {} and storage.pending_library_changes() == []
    # A new login, or leaving, goes back to the login's own channel.
    service.disconnect()
    assert storage.get_setting(IDENTITY_SETTING) == ""
