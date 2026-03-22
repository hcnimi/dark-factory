## ADDED Requirements

### Requirement: Build import graph from seed files
The system SHALL build a directed import graph starting from seed files (keyword-matched files from Phase 2a) by parsing import statements and resolving them to file paths within the repository.

#### Scenario: Python imports resolved
- **WHEN** a seed file contains `from .service import UserService` or `import dark_factory.service`
- **THEN** the system resolves the import to the corresponding `.py` file in the repo and adds it to the graph

#### Scenario: TypeScript/JavaScript imports resolved
- **WHEN** a seed file contains `import { foo } from './service'` or `const bar = require('../utils/helper')`
- **THEN** the system resolves the import to the corresponding `.ts`, `.tsx`, `.js`, or `.jsx` file (trying extensions in order) and adds it to the graph

#### Scenario: Go imports resolved
- **WHEN** a seed file contains `import "mymodule/pkg/handler"`
- **THEN** the system resolves the import to the corresponding directory within the repo (using `go.mod` module path) and adds it to the graph

#### Scenario: Unresolvable imports ignored
- **WHEN** an import references an external package (not within the repo) or cannot be resolved to a file path
- **THEN** the system SHALL skip that import without error

### Requirement: Traverse 2-hop neighborhood
The system SHALL traverse imports to a depth of 2 hops from seed files using breadth-first search, collecting both forward imports (what a file imports) and reverse imports (what imports a file).

#### Scenario: 2-hop forward traversal
- **WHEN** seed file A imports file B, and file B imports file C
- **THEN** the graph includes A → B and B → C (2 hops)

#### Scenario: Depth limited to 2
- **WHEN** file C (at hop 2) imports file D
- **THEN** file D is NOT included in the graph

#### Scenario: Reverse imports included
- **WHEN** file X imports seed file A, and file X was not found via forward traversal
- **THEN** file X is included in the graph as a reverse dependency of A

### Requirement: Cap graph size
The system SHALL cap the import graph output at 50 files to prevent context window bloat in large repositories.

#### Scenario: Graph exceeds cap
- **WHEN** the 2-hop neighborhood contains more than 50 files
- **THEN** the system returns only the 50 files closest to the seed files (by hop distance, then alphabetical)

#### Scenario: Graph within cap
- **WHEN** the 2-hop neighborhood contains 30 files
- **THEN** all 30 files are included

### Requirement: Output format
The system SHALL produce a `dict[str, list[str]]` mapping each file path (relative to repo root) to its list of imported file paths (also relative to repo root).

#### Scenario: Graph structure
- **WHEN** the import graph is built
- **THEN** the result is a dictionary where keys are file paths and values are lists of files that key imports
