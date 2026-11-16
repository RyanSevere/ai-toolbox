# Runbook: stand up a new profile

Creates a new profile repository from a released core, with `toolboxctl.py init`. `init`
is the one subcommand that runs from a release archive instead of `core/`: a new profile
has no `core/` yet. It vendors the release the archive is into `core/`, then runs setup.

Every command below is pasteable as written. Where a command takes a value of yours, the
value is a synthetic example and a line under the command says "replace with yours". Use
the same values in every step.

| Example value | What it stands for |
|---|---|
| `acme-owner` | the GitHub owner of the new profile repository and of the core |
| `acme-profile` | the new profile repository |
| `acme-core` | the core repository |
| `v0.1.19` | a release tag that carries `init` |
| `acme-owner-acme-core-1a2b3c4` | the folder the release archive extracts to |
| `work` and `scratch` | two new folders side by side: one for the clone, one for the archive |

## Before you start

- `git`, Python 3 and a signed-in `gh` (`gh auth status`).
- On Linux, a `python` on `PATH`. On Debian and Ubuntu: `sudo apt install python-is-python3`.
- The core repository and a release tag that carries `init`.
- Be ready to answer setup's questions at the console. Or write an answers file holding
  `identity:`, `source:`, `answers:` and the leak-gate keys (`personal`, `profile_name`,
  `leak_extra`, `not_onboarded`), and pass it with `--answers answers.yaml`. Setup locks
  the push gates only when you answer at the console; after an answers file, `init`'s next
  steps tell you to run `python core/consent.py --profile . --init`.
- Any text editor works for `profile.yaml`. Notepad, nano and VS Code are all fine.

## Steps

1. **Create the empty private repository and give it a git identity and a `main` branch.**
   Shell: bash, PowerShell or any shell with `gh`. Folder: the new folder `work`.

   ```
   gh repo create acme-owner/acme-profile --private --clone
   ```

   Replace `acme-owner/acme-profile` with yours. Give it no `--add-readme`, `--license`
   or `--gitignore` option. The repository must be empty: setup refuses a folder that
   holds anything but `.git` and `core`.

   Cloning an empty repository prints `warning: You appear to have cloned an empty
   repository.` That warning is expected. It is not an error.

   Move into the clone.

   ```
   cd acme-profile
   ```

   Replace `acme-profile` with yours.

   A clean machine has no git identity, and the first commit fails without one. Set one
   for this repository only. Run these two commands, each with your own value:

   ```
   git config user.name "Dev Example"
   ```

   ```
   git config user.email "dev@acme.example"
   ```

   Replace `Dev Example` and `dev@acme.example` with yours. Use your own name and email,
   not the examples.

   A clean machine may also name its default branch `master`, and the push gates expect
   `main`. Name the branch `main` now.

   ```
   git checkout -b main
   ```

   If this reports that `main` already exists, you are on it and can go on. If you have
   already made a commit, run `git branch -M main` instead.

2. **Download a release archive into a scratch folder.** Shell: as above. Folder:
   `scratch`, a new folder next to `work`, outside the clone.

   A release is a tag. The release workflow creates no GitHub Release, so
   `gh release download` finds nothing. Fetch the tag's archive instead:

   ```
   gh api repos/acme-owner/acme-core/tarball/v0.1.19 > core.tar.gz
   ```

   Replace `acme-owner/acme-core` and `v0.1.19` with yours.

   Extract it.

   ```
   tar -xzf core.tar.gz
   ```

   The archive holds one top-level folder, named `<owner>-<core-repo>-<short sha>`, for
   example `acme-owner-acme-core-1a2b3c4`. List the folder to read its real name.

3. **Run `init`.** Shell: as above. Folder: `scratch`.

   ```
   python acme-owner-acme-core-1a2b3c4/toolboxctl.py init --profile ../work/acme-profile --source acme-owner/acme-core
   ```

   Replace `acme-owner-acme-core-1a2b3c4` with the folder from step 2, `../work/acme-profile`
   with the path to your clone, and `acme-owner/acme-core` with your core repository.

   `init` refuses, and changes nothing, if the folder is not a git work tree or already
   holds `core/` or `profile.yaml`. Otherwise it writes `core/` (with `core/VENDORED`
   recording the tag and commit) and `profile.yaml`, and prints a dry-run render.

   Setup asks its questions at the console. If it asks you to lock the push gates, type
   `yes`. If you stop it part-way, delete `core/` in the clone and run this step again.

4. **Review the render.** Shell: as above. Folder: `work/acme-profile`.

   ```
   git status
   ```

   Read `profile.yaml` and the files `init` listed, in any editor. Nothing is committed
   yet. Replace the example targets (`example-app`, `example-scratch`) under `targets:`
   with your own repositories.

5. **Commit.** Shell and folder as step 4.

   ```
   git add -A
   ```

   ```
   git commit -m "Create the profile from core v0.1.19"
   ```

   Replace `v0.1.19` with your tag. The commit needs the identity from step 1; if it
   reports `unable to auto-detect email address`, go back and set it.

   Then render the profile into itself, and commit that render too:

   ```
   python core/sync.py --profile . --self --write
   ```

   ```
   git add -A
   ```

   ```
   git commit -m "Render the profile"
   ```

6. **Push.** Shell and folder as step 4.

   ```
   git push -u origin main
   ```

   If the push gates ask for consent, answer as the prompt says.

7. **Delete the archive folder.** Shell: as above. Folder: `scratch`'s parent. From here
   on everything runs from `core/`.

   ```
   rm -rf scratch
   ```

   Replace `scratch` with yours. On PowerShell: `Remove-Item -Recurse -Force scratch`.

8. **Confirm.** Shell: as above. Folder: `work/acme-profile`.

   ```
   python core/toolboxctl.py version
   ```

   It prints `acme-owner/acme-core v0.1.19 <commit>`, with your values.

Update later with `python core/toolboxctl.py update`.
