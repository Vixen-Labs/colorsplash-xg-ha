# Captures

This directory is intentionally gitignored except for this README.

BLE captures (`btsnoop_hci.log`, `*.pcap`, `*.pcapng`) and decompiled APK output never get committed, for two reasons:

1. They may include pairing material or device identifiers specific to one installation.
2. Redistributing decompiled third-party app code is out of scope for this project. We document what we learned from the captures in `docs/PROTOCOL.md` instead.

To reproduce the captures locally, see the procedures documented in the Phase 1 issues once they land.
