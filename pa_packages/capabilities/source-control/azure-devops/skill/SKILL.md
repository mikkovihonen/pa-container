### Azure DevOps Integration

Provides seamless authentication for Azure DevOps Git remotes (`https://dev.azure.com/`).

#### Credentials

- Injects the `AZURE_DEVOPS_EXT_PAT` placeholder into the container. The proxy substitutes the real token from the host OS Keyring in outgoing requests.
- Transparently configures Git URL rewrite rules for `dev.azure.com` remotes.
