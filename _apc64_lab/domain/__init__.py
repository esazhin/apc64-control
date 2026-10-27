"""The lab domain: pure values and rules, no I/O (contract §7 dependency direction).

It imports only the standard library, the host's domain value types (_apc64_host.domain: midi, oled, issues,
controls, effects, layout, outbound) and its own harmony core. The harmony core (domain/harmony/) is stricter
still: standard library only, so it can move into another music-theory project later (contract §2.7 q7)."""
