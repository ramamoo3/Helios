# Project Helios

Helios is a modular residential solar and LFP storage system for Tamil Nadu. Development is currently on one isolated battery port, scaled to a 12 V / 24 V laboratory fixture. The three-phase inverter and the production battery cabinet are later stages.

- [System architecture](HELIOS-ARCHITECTURE.md)
- [Build checklist](HELIOS-BUILD-CHECKLIST.md)
- [Whole-design software verification and fabrication status](HELIOS-VERIFICATION.md)
- [Open the KiCad bench project](circuits/battery-port/battery-port-bench.kicad_pro)
- [Bench component choices and current limits](circuits/battery-port/BENCH-PARTS.md)
- [Simulation and electrical checks](circuits/battery-port/README.md)

## Maintaining the project

GitHub `main` is the revision history. Before publishing, run the checks for the changed circuit or firmware and record the tool versions and known gaps. Keep KiCad caches and editor history local. Track independent engineering review and its findings against the revision under review. The verification tracker records fabrication status. [GitHub repository](https://github.com/ramamoo3/Helios) · [Verification tracker](HELIOS-VERIFICATION.md)
