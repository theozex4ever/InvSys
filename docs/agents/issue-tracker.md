# Issue tracker: GitHub

Issues and specs live in GitHub Issues for theozex4ever/InvSys.
Use the gh CLI from the repository root.

## Conventions

- Read tickets: gh issue view <number> --comments
- Fetch structured ticket data:
  gh issue view <number> --json number,title,body,labels,comments
- List tickets:
  gh issue list --state open --json number,title,body,labels
- Create tickets:
  gh issue create --title "..." --body-file <file>
- Comment:
  gh issue comment <number> --body-file <file>
- Apply or remove labels:
  gh issue edit <number> --add-label "..."
  gh issue edit <number> --remove-label "..."
- Close tickets: gh issue close <number>

Use files containing actual newlines for multiline bodies.
Scope operations to this repository.

“Publish to the issue tracker” means create a GitHub issue.
“Fetch the relevant ticket” means read its body and comments.

## Pull requests as a triage surface

PRs as a request surface: no.
