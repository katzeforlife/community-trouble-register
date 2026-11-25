# Security and launch checklist

Before public launch:
- Replace development secrets and enforce HTTPS.
- Use PostgreSQL, migrations, backups, monitoring, and restore tests.
- Replace the simple development admin cookie with robust sessions, CSRF protection, session expiry/rotation, and account recovery.
- Add Steam OpenID login and verified email if community identity matters.
- Add rate limiting by key, account, and IP.
- Add server ownership verification (challenge response, DNS/HTTP proof, or admin review).
- Store and display evidence carefully; restrict sensitive evidence to authorized reviewers.
- Define reason categories and require specific, reviewable evidence.
- Add independent review, dispute/correction flow, expiration/review dates, and an audit log.
- Prevent a server from voting on its own report; add duplicate detection and abuse controls.
- Avoid irreversible automatic enforcement based solely on a raw percentage threshold.
- Keep secrets out of client code and public repositories.
- Add automated tests for auth, report submission, voting, status checks, and admin workflows.
