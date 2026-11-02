"""dnfw.checkout: a run states its checkout and refuses when dnfw comes from another one."""

import os
import pathlib
import sys

from dnfw import checkout


def test_this_run_imports_this_checkout_in_process_and_in_a_child():
    r = checkout.report()
    assert r["inside"] and r["inside_child"], checkout.lines(r)
    assert checkout.problems(r) == []


def test_a_child_with_another_src_first_is_named(tmp_path):
    """the trwr2f case: PYTHONPATH names another checkout, so a child imports its dnfw"""
    other = tmp_path / "other" / "src" / "dnfw"
    other.mkdir(parents=True)
    (other / "__init__.py").write_text("")
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "other" / "src")}
    child = checkout.child_dnfw(env)
    assert child == (other / "__init__.py").resolve()
    r = checkout.report(env=env)
    bad = checkout.problems(r)
    assert not r["inside_child"] and len(bad) == 1 and "PYTHONPATH=" in bad[0]


def test_src_first_puts_this_checkout_ahead_and_keeps_the_rest():
    env = checkout.with_src_first({"PYTHONPATH": os.pathsep.join(["/x", str(checkout.ROOT / "src"), "/y"])})
    assert env["PYTHONPATH"].split(os.pathsep) == [str(checkout.ROOT / "src"), "/x", "/y"]
    assert checkout.with_src_first({})["PYTHONPATH"] == str(checkout.ROOT / "src")


def test_the_report_lists_the_resources_present(tmp_path):
    (tmp_path / "00_Resources" / "00_Firmware").mkdir(parents=True)
    r = checkout.report(tmp_path)
    assert r["resources"] == ["00_Firmware"] and r["out"] is False
    assert not r["inside"]                      # dnfw is not under tmp_path: the control
    assert any("outside the checkout" in p for p in checkout.problems(r))


def test_the_cli_names_the_checkout_of_the_current_folder(tmp_path):
    """run from another checkout with this src first: the CLI refuses, as in the trwr2f case"""
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    env = checkout.with_src_first(dict(os.environ))
    r = subprocess.run([sys.executable, "-m", "dnfw.checkout"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "refuse:" in r.stdout and str(tmp_path.resolve()) in r.stdout
    here = subprocess.run([sys.executable, "-m", "dnfw.checkout"], cwd=checkout.ROOT, env=env, capture_output=True, text=True)
    assert here.returncode == 0, here.stdout                  # the control: its own checkout


def test_a_worktree_nested_under_the_checkout_is_not_the_checkout(tmp_path):
    """worktrees live under the main checkout (.claude/worktrees): their dnfw is not its dnfw"""
    nested = tmp_path / ".claude" / "worktrees" / "w" / "src" / "dnfw" / "__init__.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("")
    own = tmp_path / "src" / "dnfw" / "__init__.py"
    own.parent.mkdir(parents=True)
    own.write_text("")
    assert not checkout._inside(nested, tmp_path)
    assert checkout._inside(own, tmp_path)                    # the control
