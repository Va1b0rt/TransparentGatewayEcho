Integration check used for this release:

1. Deploy the unchanged Compose file with ECHO_DOMAIN=localhost (no email),
   HTTP_BIND=127.0.0.1:18080, HTTPS_BIND=127.0.0.1:18443, RATE_LIMIT=8, RATE_PERIOD=10.
2. Copy Caddy's local CA certificate from
   /data/caddy/pki/authorities/local/root.crt into an ignored local test directory.
3. Run verify.py https://localhost:18443/ --ca-file PATH_TO_CA --rate-test.
   TLS verification remains enabled with an explicitly trusted test CA.
4. Confirm the echo container has no published port and is unprivileged/read-only.
5. Send unique canaries in auth/cookie/query/client-ID fields and scan both container
   logs for them; log records must omit them.
6. Restart the stack, verify HTTPS again, then remove only the test stack and test volumes.

This checks local-CA TLS without ACME; it does not test public Cloudflare routing. That requires the
operator's remote server and real DNS and are performed after deployment.
