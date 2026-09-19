# Project working instructions

## Automatic commits and GitHub synchronization

The repository owner requested automatic commits and GitHub synchronization.
After each completed change to this project:

- Run the checks appropriate to the change and inspect their results.
- Commit the relevant source, tests, documentation, and configuration changes.
- Push the commit to the current working branch on `origin`, setting its upstream
  if necessary. Do not automatically merge into another branch or force-push.
- Exclude credentials, personal projects, local audit output, generated decks,
  installed fonts, model files, and virtual environments. Small intentional test
  fixtures may be committed.
- Report the commit and whether the push succeeded. If authentication or network
  access prevents pushing, retain the local commit and state the blocker.

This is standing authorization; do not ask for routine commit/push confirmation.
Do not create a recurring scheduler or background watcher for this workflow.
