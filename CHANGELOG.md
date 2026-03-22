# Changelog

## [0.1.0] - 2026-03-21

### Added
- Initial extraction from [ai-dev](https://github.com/hcnimi/ai-dev) (`dark-factory-sdk-migration` branch)
- Full 12-phase pipeline: ingestion, exploration, scaffolding, implementation, verification, PR creation
- TDD + holdout test generation (Phase 6.5)
- Parallel task execution with dependency DAG (Phase 7)
- Context engineering: import graph, test-source mapping, symbol extraction (Phase 2a)
- Security policy enforcement on every tool invocation
- State persistence and `--resume` support
- Claude Code plugin structure with `/dark-factory` slash command
