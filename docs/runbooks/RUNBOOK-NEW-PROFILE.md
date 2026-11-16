# Runbook: stand up a new profile

Creates a new profile repository from a released core, with `toolboxctl.py init`. `init`
is the one subcommand that runs from a release archive instead of `core/`: a new profile
has no `core/` yet. It vendors the release the archive is into `core/`, then runs setup.

Placeholders are in angle brackets. Replace each one, including the brackets.

## Before you start

- `git`, Python 3 and a signed-in `gh` (`gh auth status`).
- On Linux, a `python` on `PATH`. On Debian and Ubuntu: `sudo apt install python-is-python3`.
- The core repository, as `<owner>/<core-repo>`, and a release tag that carries `init`,
  as `vX.Y.Z`.
- Be ready to answer setup's questions at the console, or write an answers file
  (identity and answers only) and pass it with `--answers <file>`.

## Steps

1. **Create the empty private repository.** Shell: bash, PowerShell or any shell with `gh`.
   Folder: the folder that should hold the new clone, `<work-folder>`.

   ```
   gh repo create <owner>/<profile-repo> --private --clone
   ```

   Give it no `--add-readme`, `--license` or `--gitignore` option. The repository must be
   empty: setup refuses a folder that holds anything but `.git` and `core`.

2. **Download a release archive into a scratch folder.** Shell: as above. Folder:
   `<scratch>`, any new folder outside the clone.

   ```
   gh release download vX.Y.Z --repo <owner>/<core-repo> --archive tar.gz
   ```

   Extract it. The archive holds one top-level folder, `<archive>`.

   ```
   tar -xzf <core-repo>-X.Y.Z.tar.gz
   ```

3. **Run `init`.** Shell: as above. Folder: `<scratch>`.

   ```
   python <archive>/toolboxctl.py init --profile <work-folder>/<profile-repo> --source <owner>/<core-repo>
   ```

   `init` refuses, and changes nothing, if the folder is not a git work tree or already
   holds `core/` or `profile.yaml`. Otherwise it writes `core/` (with `core/VENDORED`
   recording the tag and commit) and `profile.yaml`, and prints a dry-run render.

4. **Review the render.** Shell: as above. Folder: `<work-folder>/<profile-repo>`.

   ```
   git status
   ```

   Read `profile.yaml` and the files `init` listed. Nothing is committed yet.

5. **Commit.** Shell and folder as step 4.

   ```
   git add -A
   git commit -m "Create the profile from core vX.Y.Z"
   ```

6. **Push.** Shell and folder as step 4.

   ```
   git push
   ```

7. **Delete the archive folder.** Shell: as above. Folder: `<scratch>`. From here on
   everything runs from `core/`.

   ```
   rm -rf <scratch>
   ```

   On PowerShell: `Remove-Item -Recurse -Force <scratch>`.

8. **Confirm.** Shell: as above. Folder: `<work-folder>/<profile-repo>`.

   ```
   python core/toolboxctl.py version
   ```

   It prints `<owner>/<core-repo> vX.Y.Z <commit>`.

Update later with `python core/toolboxctl.py update`.
