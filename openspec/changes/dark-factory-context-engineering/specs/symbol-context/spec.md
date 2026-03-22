## ADDED Requirements

### Requirement: Extract signatures from change neighborhood
The system SHALL extract function, class, and type signatures from files in the import graph's 2-hop neighborhood using regex-based pattern matching.

#### Scenario: Python signatures
- **WHEN** a file contains `def get_user(self, user_id: str) -> User | None:` and `class UserService:` and `@dataclass class Config:`
- **THEN** the system extracts all three signatures (function name + parameters + return type, class name, dataclass with field names)

#### Scenario: TypeScript signatures
- **WHEN** a file contains `export function createUser(data: CreateUserInput): Promise<User>` and `export interface UserResponse { ... }` and `export type Status = 'active' | 'inactive'`
- **THEN** the system extracts all three signatures (function, interface name, type alias)

#### Scenario: Go signatures
- **WHEN** a file contains `func (s *Server) HandleRequest(w http.ResponseWriter, r *http.Request)` and `type Config struct { ... }`
- **THEN** the system extracts both signatures (method with receiver, struct name)

#### Scenario: Non-exported symbols excluded
- **WHEN** a Go file contains `func helperInternal()` (lowercase, unexported)
- **THEN** the system does NOT extract that symbol

### Requirement: Exclude function bodies
The system SHALL extract only signatures (names, parameters, return types), NOT function bodies, comments, or docstrings.

#### Scenario: Body excluded
- **WHEN** extracting from a 50-line function
- **THEN** the output contains only the signature line, not the implementation

### Requirement: Include export information
The system SHALL annotate symbols with export status where detectable.

#### Scenario: Python __all__ exports
- **WHEN** a Python file defines `__all__ = ["UserService", "get_user"]`
- **THEN** the symbol context marks those symbols as explicitly exported

#### Scenario: TypeScript export keyword
- **WHEN** a TypeScript function has the `export` keyword
- **THEN** the symbol context marks it as exported

### Requirement: Cap symbol context size
The system SHALL cap the total symbol context output at 200 lines to prevent context window bloat.

#### Scenario: Output exceeds cap
- **WHEN** the combined symbol extraction across all neighborhood files exceeds 200 lines
- **THEN** the system truncates, prioritizing files closer to seed files (by hop distance)

#### Scenario: Output within cap
- **WHEN** the combined extraction is 80 lines
- **THEN** all symbols are included

### Requirement: Output format
The system SHALL produce a `dict[str, list[str]]` mapping file paths to their extracted signature lines.

#### Scenario: Format structure
- **WHEN** symbol context is extracted for `src/services/user.py`
- **THEN** the entry is `{"src/services/user.py": ["class UserService:", "  def get_user(self, user_id: str) -> User | None:", "  def create_user(self, data: dict) -> User:"]}`

### Requirement: Render as API surface view
The system SHALL format the symbol context for prompt injection as a readable "API surface" view with file headers and indented signatures.

#### Scenario: Prompt rendering
- **WHEN** symbol context is rendered via `to_prompt_text()`
- **THEN** the output groups signatures under file path headers with `Used by:` annotations from the import graph
