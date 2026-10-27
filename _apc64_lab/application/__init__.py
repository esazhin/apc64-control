"""The lab's application layer: use cases over the lab domain and the lab ports (contract §7).

It imports the lab domain, host domain value types and the host's application port Protocols only, never an
adapter (infrastructure) or presentation; the host layering test enforces it. Only GuardedWriter holds the
WriteCapability (inv2).
"""
