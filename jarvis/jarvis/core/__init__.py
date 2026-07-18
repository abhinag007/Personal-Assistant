"""IMMUTABLE CORE — the safety kernel (§23).

Everything in this package is the trust anchor of the system: the sandbox guard,
the policy rules, the approval engine, and the kill switch. In the running system
the AI has NO write path into this directory — it is enforced by the sandbox guard
(which never allows writes outside the sandbox root) and, on the real machine, by
filesystem ownership/permissions.

Nothing here should import from higher-level, model-driven modules. The core must be
self-contained so a bug (or a bad generation) elsewhere can never disable it.
"""
