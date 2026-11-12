### Azure DevOps Integration

Provides seamless authentication for Azure DevOps Git remotes (`https://dev.azure.com/`).

#### Credentials

- Automatically injects `AZURE_DEVOPS_EXT_PAT` from the host OS Keyring.
- Transparently configures Git URL rewrite rules for `dev.azure.com` remotes.
