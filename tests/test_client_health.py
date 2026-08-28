from harmonia.client_health import ClientHealthTracker


def test_known_dead_android_vr_profile_is_not_considered_available():
    tracker = ClientHealthTracker()

    assert tracker.available("ANDROID_VR_1_65_10") is False
    assert tracker.available("VISIONOS") is True
    assert tracker.order_key("ANDROID_VR_1_65_10", 0) > tracker.order_key("VISIONOS", 0)
