# Project instructions

This repository is the Baize / MultiAgentsControl project.

## Desktop packaging preferences

- The user uploads installers to GitHub Releases manually. Do not upload installers or publish Releases for them.
- Before each packaging batch, ask the user whether it is a small update or a big update, showing the current and proposed version. Wait for the answer. An explicit choice in the current request covers that batch, including its platform jobs and retries.
- Use three numeric version components. A small update increments the last component; after 9, reset it to 0 and increment the middle component: `1.2.8 -> 1.2.9 -> 1.3.0`. Do not automatically carry the middle component into the first.
- A big update increments the first component and resets the other two: `1.3.4 -> 2.0.0`.
- Each packaging batch goes into a new directory containing its version and build time, using Beijing time (`Asia/Shanghai`, UTC+8) down to seconds, for example `release/Baize-1.3.0_2026-11-22_17-35-40/`. Preserve previous build directories.
- Use the packaging entry point so the application version, bundled backend version, package names and output directory agree. Verify the outputs and report their directory; leave the manual upload to the user.
