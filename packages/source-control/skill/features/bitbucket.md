### Bitbucket Integration

Provides authentication credentials and proxy access for Bitbucket Cloud (`https://bitbucket.org/`).

#### Credentials

- Automatically injects `BITBUCKET_TOKEN` from the host OS Keyring.
- Whitelists Bitbucket API and Git host egress through the container proxy.
