### GitLab Integration (`glab`)

The GitLab CLI (`glab`) enables interacting with GitLab projects, merge requests, and pipelines.

#### Common Commands

- **List and View Merge Requests**:
    ```bash
    glab mr list
    glab mr view <id>
    ```
- **Create a Merge Request**:
    ```bash
    glab mr create --title "Feature summary" --description "Implementation details"
    ```
- **Check CI/CD Pipelines**:
    ```bash
    glab ci status
    ```
