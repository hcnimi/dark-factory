## ADDED Requirements

### Requirement: Convention-based test-to-source mapping
The system SHALL map source files to their test files using language-specific naming conventions, checked in priority order.

#### Scenario: Python test file by prefix convention
- **WHEN** source file is `src/services/user.py`
- **THEN** the system checks for `tests/services/test_user.py`, `tests/test_user.py`, `test_user.py` (same directory)

#### Scenario: Python test file by suffix convention
- **WHEN** source file is `src/services/user.py`
- **THEN** the system also checks for `src/services/user_test.py`, `tests/services/user_test.py`

#### Scenario: TypeScript/JS test file conventions
- **WHEN** source file is `src/components/Button.tsx`
- **THEN** the system checks for `src/components/Button.test.tsx`, `src/components/Button.spec.tsx`, `__tests__/components/Button.test.tsx`

#### Scenario: Go test file convention
- **WHEN** source file is `pkg/handler/user.go`
- **THEN** the system checks for `pkg/handler/user_test.go` (same directory, language-enforced)

#### Scenario: No matching test file
- **WHEN** no convention-based test file exists for a source file
- **THEN** the mapping records `None` for that source file

### Requirement: Import-scan fallback
The system SHALL fall back to import scanning for test files that were not matched by convention. The system reads test files and checks if they import any source files in the change neighborhood.

#### Scenario: Test imports source module
- **WHEN** convention matching found no test for `src/auth/token.py`, but `tests/integration/test_auth_flow.py` contains `from src.auth.token import validate`
- **THEN** the mapping associates `src/auth/token.py` → `tests/integration/test_auth_flow.py`

#### Scenario: Import scan scope
- **WHEN** performing import-scan fallback
- **THEN** the system scans only files matching test naming patterns (`test_*.py`, `*_test.py`, `*.test.ts`, `*.spec.ts`, `*_test.go`), not all files in the repo

### Requirement: Output format
The system SHALL produce a `dict[str, str | None]` mapping source file paths (relative to repo root) to their test file path or `None`.

#### Scenario: Mapping structure
- **WHEN** the test-source mapping is built for source files in the change neighborhood
- **THEN** the result is a dictionary where every source file in the neighborhood has an entry, with matched test path or `None`

### Requirement: Mapping scope
The system SHALL build the mapping only for source files in the import graph's change neighborhood, not for the entire repository.

#### Scenario: Scoped to neighborhood
- **WHEN** the import graph contains 15 source files
- **THEN** the mapping contains at most 15 entries (excluding test files themselves from keys)
