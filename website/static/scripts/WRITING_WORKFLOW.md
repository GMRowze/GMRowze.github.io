# Static Writer Workflow

Project structure:

```text
drafts/      private working tree
published/  Hugo content tree
website/layouts/shortcodes/encrypted-block.html
website/static/js/encrypted-block.js
website/static/css/encrypted-block.css
website/static/scripts/writer.py
website/static/scripts/writer
```

Commands:

```bash
website/static/scripts/writer beta drafts/books/detectives/mitau/chapter_01.md
website/static/scripts/writer publish drafts/books/detectives/mitau/chapter_01.md
website/static/scripts/writer publish drafts/books/detectives/mitau/chapter_01.md --delete-draft
website/static/scripts/writer check
```

You can also call the Python file directly:

```bash
python3 website/static/scripts/writer.py beta drafts/books/detectives/mitau/chapter_01.md
```

Paths are resolved from the current directory first, then from the repository root. In WSL/bash, prefer forward slashes or quote Windows-style backslashes:

```bash
static/scripts/writer beta ../drafts/books/detectives/revolver/chapter_01.md
static/scripts/writer beta "../drafts\\books\\detectives\\revolver\\chapter_01.md"
```

Beta drafts require YAML frontmatter with `status: beta`, a `password`, and a `<!-- MORE -->` marker. The generated page is written to the mirrored path under `published/`, and the password is removed from the generated frontmatter.

Published pages are fully public Markdown with `status: public`. The tool removes `password`, `<!-- MORE -->`, and any generated encrypted block.
