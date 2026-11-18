# Project Helios

Helios is a modular residential solar and LFP storage system for Tamil Nadu. Development is currently on one isolated battery port, scaled to a 12 V / 24 V laboratory fixture. The three-phase inverter and the production battery cabinet are later stages.

- [System architecture](HELIOS-ARCHITECTURE.md)
- [Build checklist](HELIOS-BUILD-CHECKLIST.md)
- [Open the KiCad bench project](circuits/battery-port/battery-port-bench.kicad_pro)
- [Bench component choices and current limits](circuits/battery-port/BENCH-PARTS.md)
- [Simulation and electrical checks](circuits/battery-port/README.md)

## Maintaining the project

GitHub `main` is the revision history. Google Drive holds a browsable working copy with the same relative paths. For each published change, run the circuit checks, commit the reviewed files and push to GitHub. Update changed files in the existing Drive folder by file ID, create files for new paths, and verify the folder listing and changed file checksums against the committed bytes. Review Drive-side edits before replacing a file. Handle renames by moving the existing Drive item to preserve its revision history. Local KiCad settings, caches and Git internals stay in the workspace. [GitHub repository](https://github.com/ramamoo3/Helios) · [Drive folder](https://drive.google.com/drive/folders/13YH5-dz5PDKOuJbiFNVk8IivuOcVDVno)
