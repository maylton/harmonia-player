from harmonia.models import LibraryItem
from harmonia.playback_state import (
    filter_new_recommendations,
    move_queue_item,
    radio_seed_for_autoplay,
    remove_queue_item,
    shuffled_queue_keep_current,
)


def item(item_id: str) -> LibraryItem:
    return LibraryItem(item_id, item_id)


def test_shuffle_keeps_current_item_first_without_mutating_source() -> None:
    queue = [item("a"), item("b"), item("c")]

    shuffled, current_index = shuffled_queue_keep_current(
        queue,
        1,
        shuffle=lambda values: values.reverse(),
    )

    assert [entry.id for entry in shuffled] == ["b", "c", "a"]
    assert current_index == 0
    assert [entry.id for entry in queue] == ["a", "b", "c"]


def test_move_queue_item_adjusts_current_index_with_the_same_item() -> None:
    queue = [item("a"), item("b"), item("c")]

    current_index, moved = move_queue_item(queue, 1, 0, 1)

    assert moved is True
    assert [entry.id for entry in queue] == ["b", "a", "c"]
    assert current_index == 0


def test_invalid_queue_move_is_ignored() -> None:
    queue = [item("a"), item("b")]

    current_index, moved = move_queue_item(queue, 0, 0, -1)

    assert moved is False
    assert current_index == 0
    assert [entry.id for entry in queue] == ["a", "b"]


def test_remove_queue_item_preserves_selection_rules() -> None:
    queue = [item("a"), item("b"), item("c")]

    result = remove_queue_item(queue, 1, 0)

    assert result is not None
    assert result.index == 0
    assert result.removed_current is False
    assert result.empty is False
    assert [entry.id for entry in queue] == ["b", "c"]


def test_remove_current_item_selects_the_item_now_at_that_index() -> None:
    queue = [item("a"), item("b"), item("c")]

    result = remove_queue_item(queue, 1, 1)

    assert result is not None
    assert result.index == 1
    assert result.removed_current is True
    assert result.empty is False
    assert [entry.id for entry in queue] == ["a", "c"]


def test_remove_last_queue_item_reports_empty_queue() -> None:
    queue = [item("a")]

    result = remove_queue_item(queue, 0, 0)

    assert result is not None
    assert result.index == -1
    assert result.removed_current is True
    assert result.empty is True
    assert queue == []


def test_filter_new_recommendations_excludes_ids_already_in_queue() -> None:
    queue = [item("a"), item("b")]
    recommendations = [item("b"), item("c"), item("d")]

    filtered = filter_new_recommendations(queue, recommendations)

    assert [entry.id for entry in filtered] == ["c", "d"]


def test_autoplay_radio_seed_waits_while_more_than_five_items_remain() -> None:
    queue = [item(letter) for letter in "abcdefg"]

    seed = radio_seed_for_autoplay(queue, 0)

    assert seed is None


def test_autoplay_radio_seed_uses_queue_tail_at_prefetch_boundary() -> None:
    queue = [item(letter) for letter in "abcdefg"]

    seed = radio_seed_for_autoplay(queue, 1)

    assert seed is queue[-1]


def test_autoplay_radio_seed_force_bypasses_prefetch_boundary() -> None:
    queue = [item(letter) for letter in "abcdefg"]

    seed = radio_seed_for_autoplay(queue, 0, force=True)

    assert seed is queue[-1]


def test_autoplay_radio_seed_ignores_empty_queue() -> None:
    assert radio_seed_for_autoplay([], -1) is None
