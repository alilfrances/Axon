from __future__ import annotations

GOOD_PATCH = """--- a/calc/core.py
+++ b/calc/core.py
@@ -2,6 +2,8 @@
     return a + b
 
 def divide(a, b):
-    return a / b
+    if b == 0:
+        return None
+    return a / b
 
 def safe_divide(a, b):
"""

BAD_PATCH = """--- a/calc/core.py
+++ b/calc/core.py
@@ -1,5 +1,5 @@
 def add(a, b):
-    return a + b
+    return a - b
 
 def divide(a, b):
     return a / b
"""


def test_rank_patches_prefers_working_patch(git_fixture_repo):
    from axon.tools.rank_patches import rank_patches

    root = git_fixture_repo()
    result = rank_patches(
        str(root),
        [BAD_PATCH, GOOD_PATCH],
        "tests/test_calc.py::test_divide_zero_returns_none",
        timeout=120,
    )
    assert result["best_index"] == 1
    assert result["ranked"][0]["patch_index"] == 1
    assert result["ranked"][0]["verdict"] == "pass"
    assert "return a / b" in (root / "calc" / "core.py").read_text(encoding="utf-8")


def test_rank_patches_dedupes_identical_patches(git_fixture_repo):
    from axon.tools.rank_patches import rank_patches

    root = git_fixture_repo()
    result = rank_patches(
        str(root),
        [GOOD_PATCH, GOOD_PATCH],
        "tests/test_calc.py::test_divide_zero_returns_none",
        timeout=120,
    )
    dupes = [r for r in result["ranked"] if r["duplicate_of"] is not None]
    assert len(dupes) == 1 and dupes[0]["duplicate_of"] == 0
