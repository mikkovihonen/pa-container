### Bitbucket Integration

Provides authentication credentials and proxy access for Bitbucket Cloud (`https://bitbucket.org/`).

#### Credentials

- Injects the `BITBUCKET_TOKEN` placeholder into the container. The proxy substitutes the real token from the host OS Keyring in outgoing requests.
- Whitelists Bitbucket API and Git host egress through the container proxy.
