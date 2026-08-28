# QA v9.7.129
Root cause: exact-date alternatives were filtered by the same ±3-day window as primary matches, so same-month DB alternatives disappeared.
Fix: primary remains strict; below-divider alternatives allow same-month dates outside flex and rank date tier then selected-condition points.
Checks: py_compile PASS; AST PASS.
