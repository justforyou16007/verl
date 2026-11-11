# Copyright 2025 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for warmup_process_groups, the startup pass that builds collective communicators.

Run on CPU over gloo. What the device backends add is where the communicator's memory
comes from, not when it is created, so the ordering and skip rules under test here are
the same ones that run on NPU.
"""

import os

import pytest
import torch
import torch.distributed as dist
import torch.multiprocessing as mp

from verl.utils.distributed import warmup_process_groups


def _run(rank: int, world_size: int, conn, port: int):
    os.environ["MASTER_ADDR"] = "127.0.0.1"
    os.environ["MASTER_PORT"] = str(port)
    dist.init_process_group("gloo", rank=rank, world_size=world_size)
    try:
        pair = dist.new_group(ranks=[0, 1])
        alone = dist.new_group(ranks=[rank])  # every rank gets a group of size 1

        def raises():
            raise AttributeError("this Megatron build has no such group")

        warmed = warmup_process_groups(
            (
                ("missing", raises),
                ("none", lambda: None),
                ("alone", lambda: alone),
                ("pair", lambda: pair),
            )
        )

        # The warm-up must not disturb the groups it touched: a real all-reduce
        # afterwards still has to produce the right answer.
        probe = torch.full((1,), rank + 1, dtype=torch.int32)
        dist.all_reduce(probe, group=pair)

        conn.send((warmed, int(probe.item())))
    finally:
        dist.destroy_process_group()


@pytest.mark.parametrize("world_size", [2])
def test_warmup_skips_unusable_groups_and_warms_the_rest(world_size):
    """Only groups with peers are warmed; a missing or size-1 group is skipped quietly."""
    ctx = mp.get_context("spawn")
    port = 29531
    conns, procs = [], []
    for rank in range(world_size):
        parent, child = ctx.Pipe()
        p = ctx.Process(target=_run, args=(rank, world_size, child, port))
        p.start()
        conns.append(parent)
        procs.append(p)

    results = [c.recv() for c in conns]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0, f"worker exited with {p.exitcode}"

    for warmed, probe in results:
        # "missing" raised, "none" returned nothing, "alone" has no peers: all skipped.
        # Only the two-rank group is worth a communicator.
        assert warmed == ["pair(size=2)"], warmed
        # 1 + 2, i.e. the group still works and the warm-up left no stale state.
        assert probe == 3


def test_warmup_is_a_noop_without_distributed():
    """Single-process code paths must not trip over the warm-up."""
    assert not dist.is_initialized()
    assert warmup_process_groups((("anything", lambda: None),)) == []
