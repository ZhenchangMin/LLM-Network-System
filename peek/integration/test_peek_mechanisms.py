"""B2 deterministic mechanism tests for the pinned PEEK Online source."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import peek
import pytest
from peek import PendingTree
from peek.online.lpm_integration import peek_clpm_sort_inplace


def make_queue(specs):
    """Mock request containers; use the real PendingTree."""
    tree = PendingTree()
    queue = []
    rid_to_int = {}
    for index, (rid, tokens) in enumerate(specs, start=1):
        rid_to_int[rid] = index
        tree.insert(index, tokens)
        queue.append(SimpleNamespace(
            rid=rid,
            origin_input_ids=list(tokens),
            output_ids=[],
            prefix_indices=[],
        ))
    return queue, rid_to_int, tree


def sort_queue(queue, mapping, tree, *, group_major=False, hits=None):
    if hits is None:
        hits = {value: 0 for value in mapping.values()}
    return peek_clpm_sort_inplace(
        queue, mapping, tree,
        main_hits=hits,
        big_lane_share=1.0,
        group_major=group_major,
        dynamic_lane=False,
        age_alpha=0.0,
    )


def test_pending_tree_lifecycle_and_demand():
    tree = PendingTree()
    tree.insert(1, [1, 2, 3, 4])
    tree.insert(2, [1, 2, 9])
    tree.insert(3, [7, 8])

    assert len(tree) == 3
    assert tree.longest_shared_prefix(1) == 2
    assert tree.longest_shared_prefix(2) == 2
    assert tree.longest_shared_prefix(3) == 0
    assert tree.match_prefix([1, 2, 5]) == 2
    assert tree.pending_demand([1, 2]) == 2
    assert tree.pending_demand([7]) == 1
    assert tree.pending_demand([99]) == 0
    assert tree.has_sharing()

    tree.remove(2)
    assert 2 not in tree
    assert len(tree) == 2
    assert tree.pending_demand([1, 2]) == 1
    assert tree.longest_shared_prefix(1) == 0
    assert not tree.has_sharing()

    tree.remove(1)
    tree.remove(3)
    assert len(tree) == 0
    assert tree.pending_demand([1, 2]) == 0
    assert tree.node_count() == 1
    assert not tree.has_sharing()
    with pytest.raises(KeyError):
        tree.remove(2)
    assert tree.discard(2) is False

    # Removed request IDs can be reused.
    tree.insert(2, [9, 10])
    assert len(tree) == 1
    assert tree.pending_demand([9]) == 1


def test_duplicate_insert_preserves_original_request():
    tree = PendingTree()
    tree.insert(1, [1, 2, 3])
    with pytest.raises(ValueError):
        tree.insert(1, [99])
    assert len(tree) == 1
    assert tree.tokens(1) == [1, 2, 3]
    assert tree.pending_demand([1, 2]) == 1
    assert tree.pending_demand([99]) == 0


def test_dualwalk_exact_hits_and_queries():
    tree = PendingTree()
    tree.insert(1, [1, 2, 3, 4, 5])
    tree.insert(2, [1, 2, 3, 4, 6])
    calls = []
    cached_prefix = [1, 2, 3, 4, 5]

    def fake_cache(tokens):
        tokens = list(tokens)
        calls.append(tokens)
        length = 0
        for actual, cached in zip(tokens, cached_prefix):
            if actual != cached:
                break
            length += 1
        return length

    # Query singleton tails too, rather than approximating their hits.
    hits = tree.compute_main_hits(fake_cache, 1)
    assert hits == {1: 5, 2: 4}
    # Rust child traversal order is not part of the contract.
    assert sorted(calls) == [
        [1, 2, 3, 4],
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 6],
    ]


@pytest.mark.parametrize("group_major", [False, True])
def test_clpm_pioneers_and_siblings(group_major):
    queue, mapping, tree = make_queue([
        ("C", list(range(500, 540)) + [1]),
        ("B1", list(range(200, 240)) + [1]),
        ("A1", list(range(100, 140)) + [1]),
        ("B2", list(range(200, 240)) + [2]),
        ("A2", list(range(100, 140)) + [2]),
        ("A3", list(range(100, 140)) + [3]),
    ])
    deprioritized = sort_queue(
        queue, mapping, tree, group_major=group_major,
    )
    assert deprioritized == {"A2", "A3", "B2"}
    assert [r.rid for r in queue] == [
        "A1", "B1", "C", "A2", "A3", "B2",
    ]


def test_group_major_changes_interleaved_warm_order():
    # All requests are warm, so they belong to the same section.
    specs = [
        ("A1", list(range(100, 140)) + [1]),
        ("B1", list(range(200, 240)) + [1]),
        ("A2", list(range(100, 140)) + [2]),
        ("B2", list(range(200, 240)) + [2]),
    ]
    queue, mapping, tree = make_queue(specs)
    hits = {mapping[rid]: hit for rid, hit in [
        ("A1", 40), ("B1", 39), ("A2", 38), ("B2", 37),
    ]}
    arrivals = {
        rid: float(index + 1)
        for index, (rid, _) in enumerate(specs)
    }
    common = dict(
        main_hits=hits,
        arrival_ts=arrivals,
        big_lane_share=1.0,
        dynamic_lane=False,
        age_alpha=0.0,
    )

    normal = list(queue)
    grouped = list(queue)
    assert peek_clpm_sort_inplace(
        normal, mapping, tree, group_major=False, **common,
    ) == set()
    assert peek_clpm_sort_inplace(
        grouped, mapping, tree, group_major=True, **common,
    ) == set()

    assert [r.rid for r in normal] == ["A1", "B1", "A2", "B2"]
    assert [r.rid for r in grouped] == ["A1", "A2", "B1", "B2"]


@pytest.mark.parametrize("group_major", [False, True])
def test_no_sharing_equal_hits_preserves_arrival_order(group_major):
    # Equal sequence lengths avoid introducing a score difference.
    queue, mapping, tree = make_queue([
        ("C", list(range(500, 541))),
        ("A", list(range(100, 141))),
        ("B", list(range(200, 241))),
    ])
    assert not tree.has_sharing()
    assert sort_queue(
        queue, mapping, tree, group_major=group_major,
    ) == set()
    assert [r.rid for r in queue] == ["C", "A", "B"]


@pytest.fixture
def cluster_eviction(monkeypatch):
    # Load the official source in isolation: mode is read at import time.
    # Do not reload/mutate the module used by other collected tests.
    monkeypatch.setenv("PEEK_ONLINE_EVICTION_MODE", "cluster")
    monkeypatch.setenv("PEEK_ONLINE_EVICTION_DEBUG", "0")
    monkeypatch.setenv("PEEK_ONLINE_PROFILE", "0")
    path = Path(peek.__file__).resolve().parent / "online" / "eviction.py"
    spec = importlib.util.spec_from_file_location(
        "_b2_cluster_eviction", path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._EVICTION_MODE == "cluster"
    return module


def cache_nodes():
    def node(parent, tokens, accessed=100.0):
        return SimpleNamespace(
            parent=parent,
            key=SimpleNamespace(token_ids=list(tokens)),
            last_access_time=accessed,
        )

    root = node(None, [])
    shared = node(root, [1, 2])
    protected_leaf = node(shared, [3])
    unused_leaf = node(root, [8, 9, 5])
    return root, protected_leaf, unused_leaf


def test_eviction_ancestor_protection_and_queue_removal(cluster_eviction):
    tree = PendingTree()
    tree.insert(1, [1, 2, 7])
    tree.insert(2, [1, 2, 8])
    _, protected, unused = cache_nodes()
    strategy = cluster_eviction.PeekDemandStrategy(tree)

    # The leaf has no direct demand, but its ancestor does.
    assert tree.pending_demand([1, 2, 3]) == 0
    assert tree.pending_demand([1, 2]) == 2
    assert tree.pending_demand([8, 9, 5]) == 0
    assert strategy.get_priority(protected) == (12, 100.0)
    assert strategy.get_priority(unused) == (0, 100.0)
    assert strategy.get_priority(unused) < strategy.get_priority(protected)

    tree.remove(1)
    assert strategy.get_priority(protected) == (6, 100.0)
    tree.remove(2)
    assert strategy.get_priority(protected) == (0, 100.0)
    assert strategy.get_priority(unused) == (0, 100.0)


def test_eviction_initially_empty_queue_and_lru_tie(cluster_eviction):
    tree = PendingTree()
    root, protected, unused = cache_nodes()
    strategy = cluster_eviction.PeekDemandStrategy(tree)

    assert strategy.get_priority(root)[0] == 0
    assert strategy.get_priority(protected) == (0, 100.0)
    assert strategy.get_priority(unused) == (0, 100.0)

    # With zero demand, an older access time gets lower heap priority.
    unused.last_access_time = 50.0
    assert strategy.get_priority(unused) == (0, 50.0)
    assert strategy.get_priority(unused) < strategy.get_priority(protected)