# Release Notes for geoff-codes-things/scripts

## 2025-03-04

### New Features
_None_

### Enhancements
* Updated the .gitignore file to prevent macOS system files from being tracked in version control. Previously, .DS_Store files (hidden metadata files created by Finder on macOS) could be accidentally committed to the repository, causing clutter and potential conflicts across different operating systems. The change adds a pattern `**/.DS_Store` that ignores these files at any directory level, ensuring they remain local to each developer's machine. ([545c029]())

### Bug Fixes
* Corrected a documentation comment in the `readTextFile` function. Previously, the comment incorrectly stated that the function reads "a text file," when it actually processes CSV files with specific column headers ('beforeReplacement' and 'afterReplacement'). The change ensures developers reading the code understand the actual data format expected by this utility function. ([f428bf4](https://github.com/geoff-codes-things/scripts/commit/20bc2f7f4dc86b30c46350a21a5a9e862391ab40))

**Files changed:**
- `textReplacer/textReplacer.py` (+1/-1)
- `.gitignore` (+3/-0)

---

