# Copyright 2026 Bytedance Ltd. and/or its affiliates
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
"""Every recipe agent loop that reads ``self.turn_separator`` must also assign it.

``verl.utils.tokenizer.chat_template.initialize_turn_separator`` is the only producer of that
value, and nothing forces a caller to exist: a recipe can read the attribute, import cleanly,
pass every other test, and then raise ``AttributeError`` on its first injected turn -- which
is a dead trajectory, so an arm that hits it reports a passrate of exactly zero rather than a
crash anyone would notice in a smoke test. The arms are copies of one another, so the mistake
also travels by copy-paste.

This reads the sources as text instead of importing them: these modules pull in the agent
runtimes (``mimoagent`` and friends), which are not installed in a CPU test environment, and
the invariant is a property of the source anyway.
"""

import ast
from pathlib import Path

import pytest

_RECIPES = Path(__file__).resolve().parents[2] / "recipes"
_AGENT_LOOPS = sorted(_RECIPES.glob("*/agent_loop.py"))


def test_there_are_agent_loops_to_check():
    # Guards the glob itself: a layout change that finds nothing would make every
    # parametrized case below vacuously pass.
    assert _AGENT_LOOPS, f"no recipes/*/agent_loop.py under {_RECIPES}"


@pytest.mark.parametrize("path", _AGENT_LOOPS, ids=lambda p: p.parent.name)
def test_turn_separator_is_assigned_wherever_it_is_read(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))

    reads, writes = [], []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "turn_separator"):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == "self"):
            continue
        (writes if isinstance(node.ctx, ast.Store) else reads).append(node.lineno)

    if not reads:
        pytest.skip(f"{path.parent.name} does not use self.turn_separator")

    assert writes, (
        f"{path.relative_to(_RECIPES.parent)} reads self.turn_separator at line(s) {reads} but never "
        "assigns it; call initialize_turn_separator(...) in __init__"
    )
    # An assignment that only runs after the first read is the same bug with extra steps.
    assert min(writes) < min(reads), (
        f"{path.relative_to(_RECIPES.parent)} assigns self.turn_separator at line {min(writes)}, "
        f"after the first read at line {min(reads)}"
    )
