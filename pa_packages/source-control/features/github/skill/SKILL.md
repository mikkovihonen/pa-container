### GitHub Integration (`gh`)

The GitHub CLI (`gh`) and GitHub MCP server allow managing issues, pull requests, and repository workflows directly.

#### Common Commands

- **List and View Pull Requests**:
    ```bash
    gh pr list
    gh pr view <number>
    ```
- **Create a Pull Request**:
    ```bash
    gh pr create --title "Feature summary" --body "Implementation details"
    ```
- **Query GitHub API**:
    ```bash
    gh api repos/{owner}/{repo}
    ```
- **MCP Server**: The `github` MCP server is registered at runtime and uses the `GH_TOKEN` placeholder, which the proxy substitutes in outgoing requests.
